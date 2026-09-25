import dataclasses
import math
from datetime import time

import pytest

from config import (
    BrokerCredentials, ConfigError, RuntimeMode, TradingConfig, load_credentials,
)
from models import TradingMode


def make(**overrides):
    return TradingConfig(symbol="hdfcbank", **overrides)


# ---------------------------------------------------------------- TradingConfig
def test_valid_config_and_symbol_normalised():
    cfg = make()
    assert cfg.symbol == "HDFCBANK"
    assert cfg.timeframe_minutes == 5


def test_config_is_immutable():
    with pytest.raises(dataclasses.FrozenInstanceError):
        make().capital = 5


@pytest.mark.parametrize("field,value", [
    ("symbol", ""), ("symbol", "   "),
    ("exchange", "BSE"),
    ("timeframe", "1minute"),
    ("capital", 0), ("capital", -1), ("capital", math.nan), ("capital", math.inf), ("capital", True), ("capital", "100"),
    ("risk_per_trade_pct", 0), ("risk_per_trade_pct", -0.5), ("risk_per_trade_pct", 50), ("risk_per_trade_pct", math.nan),
    ("max_daily_loss", 0), ("max_daily_loss", -10), ("max_daily_loss", 200_000),  # > capital
    ("max_trades_per_day", 0), ("max_trades_per_day", 2.5), ("max_trades_per_day", True),
    ("max_quantity", 0), ("max_quantity", -3), ("max_quantity", 1.5),
    ("stop_loss_pct", 0), ("stop_loss_pct", -1), ("stop_loss_pct", 100),
    ("target_pct", -1), ("target_pct", math.nan),
    ("slippage_pct", -0.01), ("slippage_pct", 50),
    ("enable_target", "yes"),
    ("trading_start", "09:20"),
])
def test_invalid_values_rejected(field, value):
    kwargs = {field: value}
    if field == "symbol":
        with pytest.raises(ConfigError):
            TradingConfig(**kwargs)
    else:
        with pytest.raises(ConfigError):
            make(**kwargs)


def test_target_must_be_positive_only_when_enabled():
    make(enable_target=False, target_pct=0)              # fine: target unused
    with pytest.raises(ConfigError):
        make(enable_target=True, target_pct=0)
    assert make(enable_target=True, target_pct=1.5).target_pct == 1.5


@pytest.mark.parametrize("start,end", [
    (time(9, 0), time(15, 0)),     # before market open
    (time(9, 20), time(15, 45)),   # after market close
    (time(11, 0), time(10, 0)),    # start after end
    (time(10, 0), time(10, 0)),    # empty window
])
def test_trading_window_validated(start, end):
    with pytest.raises(ConfigError):
        make(trading_start=start, trading_end=end)


def test_round_trip_dict_and_no_live_flag():
    cfg = make(enable_target=True, target_pct=2.5, trading_end=time(14, 45))
    data = cfg.to_dict()
    assert data["trading_end"] == "14:45"
    assert "live_enabled" not in data and "mode" not in data
    assert TradingConfig.from_dict(data) == cfg


def test_from_dict_rejects_unknown_keys_including_live_flag():
    data = make().to_dict()
    data["live_enabled"] = True
    with pytest.raises(ConfigError, match="unknown config keys"):
        TradingConfig.from_dict(data)


def test_from_dict_rejects_bad_time_string():
    data = make().to_dict()
    data["trading_start"] = "nine-twenty"
    with pytest.raises(ConfigError):
        TradingConfig.from_dict(data)


# ---------------------------------------------------------------- RuntimeMode
def test_runtime_defaults_to_paper_with_live_disabled():
    rm = RuntimeMode()
    assert rm.mode is TradingMode.PAPER
    assert rm.live_enabled is False
    assert rm.is_live_allowed() is False


def test_live_needs_live_mode_and_explicit_confirmation():
    rm = RuntimeMode()
    with pytest.raises(ConfigError):
        rm.enable_live(confirmed=True)            # still PAPER
    rm.set_mode(TradingMode.LIVE)
    assert rm.is_live_allowed() is False          # selecting LIVE alone is not enough
    with pytest.raises(ConfigError):
        rm.enable_live(confirmed=False)
    with pytest.raises(ConfigError):
        rm.enable_live(confirmed="yes")           # truthy is not confirmation
    assert rm.is_live_allowed() is False
    rm.enable_live(confirmed=True)
    assert rm.is_live_allowed() is True


def test_leaving_live_switches_it_off_and_returning_needs_reconfirmation():
    rm = RuntimeMode()
    rm.set_mode(TradingMode.LIVE)
    rm.enable_live(confirmed=True)
    rm.set_mode(TradingMode.PAPER)
    assert rm.is_live_allowed() is False and rm.live_enabled is False
    rm.set_mode(TradingMode.LIVE)
    assert rm.is_live_allowed() is False


def test_mode_must_be_enum_and_paper_is_never_live():
    rm = RuntimeMode()
    with pytest.raises(ConfigError):
        rm.set_mode("LIVE")                       # a string is not a mode
    assert TradingMode.PAPER != TradingMode.LIVE
    assert TradingMode.PAPER != "PAPER"           # not a str subclass: no silent string comparisons
    with pytest.raises(ValueError):
        TradingMode("live")                       # unknown value never defaults to anything


# ---------------------------------------------------------------- credentials
def test_credentials_loaded_and_never_shown():
    env = {"KITE_API_KEY": "key_abc123", "KITE_API_SECRET": "secret_xyz789", "KITE_ACCESS_TOKEN": "tok_qwerty456"}
    creds = load_credentials(env)
    assert creds.is_complete
    for text in (repr(creds), str(creds), f"{creds}"):
        for secret in env.values():
            assert secret not in text
    assert creds.status() == {"api_key": "set", "api_secret": "set", "access_token": "set"}


def test_missing_credentials_reported():
    creds = load_credentials({"KITE_API_KEY": "only_key_here"})
    assert not creds.is_complete
    assert creds.status()["access_token"] == "missing"
    assert not BrokerCredentials().is_complete


def test_loaded_credentials_are_registered_for_log_redaction():
    from utils.logger import redact
    load_credentials({"KITE_API_KEY": "key_abc123", "KITE_API_SECRET": "secret_xyz789", "KITE_ACCESS_TOKEN": "tok_qwerty456"})
    assert redact("connecting with tok_qwerty456 now") == "connecting with *** now"


# ---------------------------------------------------------------- square-off time (Phase 3)
def test_square_off_must_be_after_trading_end_and_no_later_than_close():
    assert make(trading_end=time(15, 0), square_off_time=time(15, 15)).square_off_time == time(15, 15)
    assert make(trading_end=time(15, 0), square_off_time=time(15, 30)).square_off_time == time(15, 30)
    for bad in (time(15, 0), time(14, 59), time(15, 31)):
        with pytest.raises(ConfigError):
            make(trading_end=time(15, 0), square_off_time=bad)
    with pytest.raises(ConfigError):
        make(square_off_time="15:15")


def test_square_off_round_trips_through_dict():
    cfg = make(square_off_time=time(15, 20))
    assert cfg.to_dict()["square_off_time"] == "15:20"
    assert TradingConfig.from_dict(cfg.to_dict()) == cfg
