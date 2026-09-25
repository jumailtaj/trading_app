"""Central configuration, mode safety, and credential loading.

Units: every `*_pct` value is a PERCENT (0.5 means 0.5%, not 50%). Money is in INR.
The default numbers below are EXAMPLES from the spec. Review them; they are not advice.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, fields
from datetime import time
from typing import Any, Mapping, Optional

from models import TradingMode
from utils.logger import register_secret

# --- exchange facts / guard rails (edit deliberately) ---------------------------------
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)
SUPPORTED_EXCHANGES = ("NSE",)
SUPPORTED_TIMEFRAMES = {"5minute": 5}  # Kite interval name -> minutes (v1: 5-minute only)
MAX_RISK_PER_TRADE_PCT = 5.0           # typo guard: 0.5 vs 50
MAX_SLIPPAGE_PCT = 5.0


class ConfigError(ValueError):
    """Invalid configuration or an attempt to skip a safety step."""


# --- validation helpers ---------------------------------------------------------------
def _number(name: str, value: Any, *, gt: Optional[float] = None, ge: Optional[float] = None,
            lt: Optional[float] = None, le: Optional[float] = None) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ConfigError(f"{name} must be finite, got {value!r}")
    if gt is not None and not value > gt:
        raise ConfigError(f"{name} must be > {gt}, got {value}")
    if ge is not None and not value >= ge:
        raise ConfigError(f"{name} must be >= {ge}, got {value}")
    if lt is not None and not value < lt:
        raise ConfigError(f"{name} must be < {lt}, got {value}")
    if le is not None and not value <= le:
        raise ConfigError(f"{name} must be <= {le}, got {value}")


def _integer(name: str, value: Any, *, ge: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be a whole number, got {value!r}")
    if value < ge:
        raise ConfigError(f"{name} must be >= {ge}, got {value}")


# --- trading configuration ------------------------------------------------------------
@dataclass(frozen=True)
class TradingConfig:
    """Strategy-independent trading + risk settings. Immutable; use dataclasses.replace().

    Deliberately contains NO mode and NO live flag: those are runtime state (RuntimeMode)
    and are never saved, so a stored config can never turn live trading on.
    """
    symbol: str
    exchange: str = "NSE"
    timeframe: str = "5minute"
    capital: float = 100_000.0
    risk_per_trade_pct: float = 0.5
    max_daily_loss: float = 1_000.0
    max_trades_per_day: int = 5
    max_quantity: int = 100
    stop_loss_pct: float = 1.0          # mandatory: there is no "no stop" option
    enable_target: bool = False
    target_pct: float = 2.0
    slippage_pct: float = 0.05
    trading_start: time = time(9, 20)   # earliest time a new entry may be placed
    trading_end: time = time(15, 0)     # latest time a new entry may be placed (inclusive)
    square_off_time: time = time(15, 15)  # any open position is closed at this candle's open (intraday only)

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ConfigError("symbol must be a non-empty string")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())
        if self.exchange not in SUPPORTED_EXCHANGES:
            raise ConfigError(f"exchange must be one of {SUPPORTED_EXCHANGES}, got {self.exchange!r}")
        if self.timeframe not in SUPPORTED_TIMEFRAMES:
            raise ConfigError(f"timeframe must be one of {sorted(SUPPORTED_TIMEFRAMES)}, got {self.timeframe!r}")
        _number("capital", self.capital, gt=0)
        _number("risk_per_trade_pct", self.risk_per_trade_pct, gt=0, le=MAX_RISK_PER_TRADE_PCT)
        _number("max_daily_loss", self.max_daily_loss, gt=0, le=self.capital)
        _integer("max_trades_per_day", self.max_trades_per_day, ge=1)
        _integer("max_quantity", self.max_quantity, ge=1)
        _number("stop_loss_pct", self.stop_loss_pct, gt=0, lt=100)
        if not isinstance(self.enable_target, bool):
            raise ConfigError(f"enable_target must be True/False, got {self.enable_target!r}")
        _number("target_pct", self.target_pct, ge=0, lt=1000)
        if self.enable_target and not self.target_pct > 0:
            raise ConfigError("target_pct must be > 0 when the target is enabled")
        _number("slippage_pct", self.slippage_pct, ge=0, le=MAX_SLIPPAGE_PCT)
        for name in ("trading_start", "trading_end", "square_off_time"):
            if not isinstance(getattr(self, name), time):
                raise ConfigError(f"{name} must be a datetime.time")
        if not (MARKET_OPEN <= self.trading_start < self.trading_end <= MARKET_CLOSE):
            raise ConfigError(
                f"trading window must satisfy {MARKET_OPEN:%H:%M} <= start < end <= {MARKET_CLOSE:%H:%M}"
            )
        if not (self.trading_end < self.square_off_time <= MARKET_CLOSE):
            raise ConfigError(
                f"square_off_time must be after trading_end ({self.trading_end:%H:%M}) "
                f"and no later than {MARKET_CLOSE:%H:%M}"
            )

    @property
    def timeframe_minutes(self) -> int:
        return SUPPORTED_TIMEFRAMES[self.timeframe]

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            out[f.name] = value.strftime("%H:%M") if isinstance(value, time) else value
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TradingConfig":
        known = {f.name for f in fields(cls)}
        unknown = set(data) - known
        if unknown:
            raise ConfigError(f"unknown config keys: {sorted(unknown)}")
        kwargs = dict(data)
        for name in ("trading_start", "trading_end", "square_off_time"):
            if isinstance(kwargs.get(name), str):
                try:
                    hh, mm = kwargs[name].split(":")
                    kwargs[name] = time(int(hh), int(mm))
                except ValueError as exc:
                    raise ConfigError(f"{name} must look like HH:MM, got {kwargs[name]!r}") from exc
        return cls(**kwargs)


# --- runtime mode safety --------------------------------------------------------------
class RuntimeMode:
    """Which mode the app is in, and whether LIVE has been explicitly enabled.

    In-memory only and never persisted: every process start is PAPER with live disabled,
    even if Kite credentials exist. Live orders are allowed only when is_live_allowed().
    """

    def __init__(self) -> None:
        self._mode = TradingMode.PAPER
        self._live_enabled = False

    @property
    def mode(self) -> TradingMode:
        return self._mode

    @property
    def live_enabled(self) -> bool:
        return self._live_enabled

    def set_mode(self, mode: TradingMode) -> None:
        if not isinstance(mode, TradingMode):
            raise ConfigError(f"mode must be a TradingMode, got {mode!r}")
        if mode is not TradingMode.LIVE:
            self._live_enabled = False       # leaving LIVE always switches it off
        self._mode = mode

    def enable_live(self, *, confirmed: bool) -> None:
        if self._mode is not TradingMode.LIVE:
            raise ConfigError("select LIVE mode before enabling live trading")
        if confirmed is not True:
            raise ConfigError("live trading needs explicit confirmation (confirmed=True)")
        self._live_enabled = True

    def disable_live(self) -> None:
        self._live_enabled = False

    def is_live_allowed(self) -> bool:
        return self._mode is TradingMode.LIVE and self._live_enabled


# --- broker credentials ---------------------------------------------------------------
@dataclass(frozen=True)
class BrokerCredentials:
    """Kite credentials. Values never appear in repr/str; use status() for the UI."""
    api_key: str = field(default="", repr=False)
    api_secret: str = field(default="", repr=False)
    access_token: str = field(default="", repr=False)

    @property
    def is_complete(self) -> bool:
        return bool(self.api_key and self.api_secret and self.access_token)

    def status(self) -> dict[str, str]:
        return {
            "api_key": "set" if self.api_key else "missing",
            "api_secret": "set" if self.api_secret else "missing",
            "access_token": "set" if self.access_token else "missing",
        }

    def __repr__(self) -> str:
        s = self.status()
        return f"BrokerCredentials(api_key={s['api_key']}, api_secret={s['api_secret']}, access_token={s['access_token']})"

    __str__ = __repr__


def load_credentials(env: Optional[Mapping[str, str]] = None) -> BrokerCredentials:
    """Read KITE_API_KEY / KITE_API_SECRET / KITE_ACCESS_TOKEN.

    With env=None, loads a local .env file (if present) and then os.environ.
    Loaded values are registered with the logger so they are masked if ever logged.
    """
    if env is None:
        from dotenv import load_dotenv
        load_dotenv()
        env = os.environ
    creds = BrokerCredentials(
        api_key=env.get("KITE_API_KEY", "").strip(),
        api_secret=env.get("KITE_API_SECRET", "").strip(),
        access_token=env.get("KITE_ACCESS_TOKEN", "").strip(),
    )
    for secret in (creds.api_key, creds.api_secret, creds.access_token):
        register_secret(secret)
    return creds
