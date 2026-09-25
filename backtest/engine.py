"""Deterministic backtest engine.

    candles -> Strategy -> Signal -> RiskManager -> SimulatedBroker -> trades, equity, metrics

Nothing here imports or calls a real broker. Same data + same config + same strategy always gives
the same result (no randomness anywhere).

Per-candle order of events (candle i):
  1. Execute the signal pending from candle i-1 at THIS candle's open.
  2. If the candle starts at/after square_off_time and a position is open: close it at the open.
  3. If a position is open: check this candle's high/low against its stop and target.
  4. On the last candle of the data: close anything still open at the close.
  5. Mark equity at this candle's close.
  6. Take the strategy's signal for candle i (it used candles 0..i only) and queue it for candle i+1.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, time
from typing import Optional

import numpy as np
import pandas as pd

from backtest.broker import ExitReason, SimulatedBroker
from backtest.metrics import Metrics, compute_metrics
from config import TradingConfig
from models import Signal, Trade
from strategy.base_strategy import Strategy
from trading.risk_manager import RiskManager
from utils.charges import RATES_CHECKED, ChargesConfig
from utils.timeutil import IST, to_iso

ASSUMPTIONS = [
    "Signals come from a CLOSED candle and execute at the NEXT candle's open, same day only "
    "(a signal on a day's last candle expires).",
    "Long-only, one position at a time. SELL exits a long; SELL while flat and BUY while long are ignored.",
    "Intraday only: entries allowed from trading_start to trading_end (inclusive); an open position is "
    "closed at the open of the first candle at/after square_off_time, or at the last candle's close if the data ends first.",
    "Position size uses the configured capital as a fixed amount (no compounding): the smaller of "
    "risk-based size, what capital can buy with no leverage, and max_quantity.",
    "The stop is set from the actual fill price and is live from the entry candle itself. If one candle touches "
    "both stop and target, the STOP is assumed to hit first. A candle that opens beyond the stop fills at the "
    "open, not at the stop price. Targets fill at the target price with no price improvement.",
    "Slippage worsens every market-type fill (entry, signal exit, stop, square-off, end-of-data); target fills get none.",
    f"Charges are ESTIMATES for NSE equity intraday (rates {RATES_CHECKED}), deducted when a trade closes; "
    "P&L figures are net of them.",
    "The equity curve is marked to each candle's close, so drawdowns inside a candle are not captured.",
    "Timestamps are candle start times; exact time inside a candle is unknown. Prices are not rounded to the "
    "0.05 tick. Exchange holidays, circuit limits, liquidity and partial fills are not modelled.",
]


class BacktestDataError(ValueError):
    """The candle data cannot be backtested."""


class LookAheadError(RuntimeError):
    """A strategy's whole-series signals disagree with its one-candle-at-a-time signals."""


@dataclass
class BacktestResult:
    config: TradingConfig
    strategy_name: str
    charges: ChargesConfig
    trades: list[Trade]
    equity_curve: pd.Series
    metrics: Metrics
    skipped_signals: dict[str, int]
    signal_counts: dict[str, int]
    candles: int
    assumptions: list[str]

    def to_dict(self) -> dict:
        """JSON-safe form (for db.save_backtest and the UI)."""
        return {
            "strategy": self.strategy_name,
            "config": self.config.to_dict(),
            "charges_config": asdict(self.charges),
            "metrics": self.metrics.to_dict(),
            "skipped_signals": self.skipped_signals,
            "signal_counts": self.signal_counts,
            "candles": self.candles,
            "assumptions": self.assumptions,
            "trades": [
                {"side": t.side.value, "quantity": t.quantity, "entry_time": to_iso(t.entry_time),
                 "entry_price": t.entry_price, "exit_time": to_iso(t.exit_time), "exit_price": t.exit_price,
                 "pnl": t.pnl, "charges": t.charges, "reason": t.reason}
                for t in self.trades
            ],
            "equity_curve": [[to_iso(ts), float(v)] for ts, v in self.equity_curve.items()],
        }


class Backtester:
    def __init__(self, config: TradingConfig, strategy: Strategy, charges: Optional[ChargesConfig] = None,
                 lookahead_check_samples: int = 25, filter_hours: bool = True):
        """charges=None means the estimated Zerodha intraday rates; pass ChargesConfig.none() to switch charges off.
        lookahead_check_samples: how many candles to spot-check the strategy's whole-series signals against
        one-candle-at-a-time signals (0 disables the check)."""
        self.config = config
        self.strategy = strategy
        self.charges = charges if charges is not None else ChargesConfig()
        self.lookahead_check_samples = lookahead_check_samples
        self.filter_hours = filter_hours

    # ------------------------------------------------------------------ data checks
    @staticmethod
    def _prepare(data: pd.DataFrame, config: Optional[TradingConfig] = None,
                 filter_hours: bool = True) -> pd.DataFrame:
        if not isinstance(data, pd.DataFrame):
            raise BacktestDataError(f"candles must be a DataFrame, got {type(data).__name__}")
        missing = {"open", "high", "low", "close"} - set(data.columns)
        if missing:
            raise BacktestDataError(f"candles are missing columns: {sorted(missing)}")
        if data.empty:
            raise BacktestDataError("no candles supplied")
        if not isinstance(data.index, pd.DatetimeIndex) or data.index.tz is None:
            raise BacktestDataError("candle index must be a timezone-aware DatetimeIndex (Kite data is IST)")
        if not (data.index.is_unique and data.index.is_monotonic_increasing):
            raise BacktestDataError("candle index must be unique and sorted oldest to newest")

        idx_ist = data.index.tz_convert(IST)

        if filter_hours:
            in_hours = (idx_ist.time >= time(9, 15)) & (idx_ist.time < time(15, 30))
            if not in_hours.any():
                raise BacktestDataError("no candles within market hours (09:15-15:30 IST)")
            if not in_hours.all():
                data = data[in_hours]
                idx_ist = idx_ist[in_hours]
        else:
            in_hours = (idx_ist.time >= time(9, 15)) & (idx_ist.time < time(15, 30))
            if not in_hours.all():
                raise BacktestDataError("candles outside market hours (09:15-15:30 IST) present")

        if config is not None and len(data) > 1:
            diffs = np.diff(idx_ist.asi8) // 1_000_000_000
            if len(diffs) > 0:
                modal_spacing = Counter(diffs).most_common(1)[0][0]
                expected_secs = config.timeframe_minutes * 60
                if modal_spacing != expected_secs:
                    raise BacktestDataError(
                        f"candle spacing mode is {modal_spacing}s, expected {expected_secs}s for timeframe '{config.timeframe}'"
                    )

        ohlc = data[["open", "high", "low", "close"]].apply(pd.to_numeric, errors="coerce").astype(float)
        values = ohlc.to_numpy()
        if not np.isfinite(values).all() or not (values > 0).all():
            raise BacktestDataError("open/high/low/close must all be positive, finite numbers")
        o, h, l, c = (ohlc[k].to_numpy() for k in ("open", "high", "low", "close"))
        if not ((h >= l) & (h >= o) & (h >= c) & (l <= o) & (l <= c)).all():
            raise BacktestDataError("inconsistent candles found (high must be the highest and low the lowest)")
        out = ohlc.copy()
        if "volume" in data.columns:
            out["volume"] = data["volume"].to_numpy()
        out.index = idx_ist
        return out

    def _check_no_lookahead(self, candles: pd.DataFrame, signals: pd.Series) -> None:
        n, k = len(candles), self.lookahead_check_samples
        if k <= 0 or n == 0:
            return
        first = max(self.strategy.warmup_candles - 1, 0)
        for i in sorted(set(np.linspace(first, n - 1, num=min(k, n - first)).astype(int).tolist())):
            expected = self.strategy.generate_signal(candles.iloc[: i + 1])
            if signals.iloc[i] is not expected:
                raise LookAheadError(
                    f"{self.strategy.name}: whole-series signal at candle {i} is {signals.iloc[i]} but the signal "
                    f"from candles up to {i} is {expected}. The strategy is using future data."
                )

    # ------------------------------------------------------------------ the run
    def run(self, data: pd.DataFrame) -> BacktestResult:
        cfg = self.config
        candles = self._prepare(data, config=cfg, filter_hours=self.filter_hours)
        signals = self.strategy.generate_signals(candles)
        if len(signals) != len(candles):
            raise BacktestDataError("strategy returned the wrong number of signals")
        self._check_no_lookahead(candles, signals)

        broker = SimulatedBroker(cfg, self.charges)
        risk = RiskManager(cfg)
        n = len(candles)
        o, h, l, c = (candles[k].to_numpy() for k in ("open", "high", "low", "close"))
        times = list(candles.index.to_pydatetime())
        days = [t.date() for t in times]
        clock = [t.time() for t in times]

        equity = np.empty(n)
        realized_total = 0.0
        realized_by_day: Counter = Counter()
        entries_by_day: Counter = Counter()
        skipped: Counter = Counter()
        pending: Optional[tuple[Signal, datetime]] = None

        def realise(trade: Optional[Trade]) -> None:
            nonlocal realized_total
            if trade is not None:
                realized_total += trade.pnl
                realized_by_day[trade.exit_time.date()] += trade.pnl

        timeframe_secs = cfg.timeframe_minutes * 60

        for i in range(n):
            t, d = times[i], days[i]

            # 1. execute the signal queued by the previous candle, at this candle's open
            if pending is not None:
                sig, sig_time = pending
                pending = None
                if (t - sig_time).total_seconds() != timeframe_secs:
                    skipped["GAP_SIGNAL_EXPIRED"] += 1
                elif sig is Signal.BUY:
                    if broker.position is not None:
                        skipped["BUY_WHILE_LONG"] += 1
                    else:
                        decision = risk.check_entry(when=t, entry_price=float(o[i]),
                                                    realized_pnl_today=realized_by_day[d],
                                                    entries_today=entries_by_day[d])
                        if decision.allowed:
                            broker.enter_long(t, float(o[i]), decision.quantity)
                            entries_by_day[d] += 1
                        else:
                            skipped[decision.reason] += 1
                elif sig is Signal.SELL:
                    if broker.position is None:
                        skipped["SELL_WHILE_FLAT"] += 1
                    else:
                        realise(broker.exit_long(t, float(o[i]), ExitReason.SIGNAL))

            # 2. end-of-day square-off at the open
            if broker.position is not None and clock[i] >= cfg.square_off_time:
                realise(broker.exit_long(t, float(o[i]), ExitReason.SQUARE_OFF))

            # 3. stop / target inside this candle
            if broker.position is not None:
                realise(broker.check_stop_and_target(t, float(o[i]), float(h[i]), float(l[i])))

            # 4. last candle: nothing is left open
            if i == n - 1 and broker.position is not None:
                realise(broker.exit_long(t, float(c[i]), ExitReason.END_OF_DATA))

            # 5. mark equity at the close
            pos = broker.position
            unrealised = (float(c[i]) - pos.entry_price) * pos.quantity if pos is not None else 0.0
            equity[i] = cfg.capital + realized_total + unrealised

            # 6. queue this candle's signal for the next candle (same day only)
            sig = signals.iloc[i]
            if sig is not Signal.HOLD:
                if i + 1 < n and days[i + 1] == d:
                    pending = (sig, t)
                else:
                    skipped["NO_NEXT_CANDLE_TODAY"] += 1

        trades = broker.trades
        curve = pd.Series(equity, index=candles.index, name="equity")
        if abs(curve.iloc[-1] - (cfg.capital + sum(tr.pnl for tr in trades))) > 1e-6:
            raise RuntimeError("accounting error: final equity does not equal capital + sum of trade P&L")
        counts = Counter(s.value for s in signals if s is not Signal.HOLD)
        return BacktestResult(
            config=cfg, strategy_name=self.strategy.name, charges=self.charges, trades=trades,
            equity_curve=curve, metrics=compute_metrics(trades, curve, cfg.capital),
            skipped_signals=dict(sorted(skipped.items())), signal_counts=dict(sorted(counts.items())),
            candles=n, assumptions=list(ASSUMPTIONS),
        )
