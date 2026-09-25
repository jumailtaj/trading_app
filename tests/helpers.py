"""Shared builders for backtest tests. Prices are chosen so expected P&L can be worked out by hand.

With capital 100,000, risk 0.5% and stop 1%, a share priced 100 sizes to exactly 500 shares:
    risk amount 500 / (100 * 1%) = 500   -> every Rs 1 move is Rs 500.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest.engine import Backtester
from config import TradingConfig
from models import Signal
from strategy.base_strategy import Strategy
from utils.charges import ChargesConfig
from utils.timeutil import IST

BUY, SELL, HOLD = Signal.BUY, Signal.SELL, Signal.HOLD
NO_FEES = ChargesConfig.none()
SESSION = 75            # 5-minute candles from 09:15 to 15:25


def cfg(**kw) -> TradingConfig:
    base = dict(symbol="TEST", capital=100_000.0, risk_per_trade_pct=0.5, stop_loss_pct=1.0,
                max_quantity=1000, max_daily_loss=5_000.0, max_trades_per_day=10, slippage_pct=0.0)
    base.update(kw)
    return TradingConfig(**base)


def flat(p: float) -> tuple:
    return (p, p, p, p)


def candles(rows, day="2026-09-23", start="09:15") -> pd.DataFrame:
    idx = pd.date_range(f"{day} {start}", periods=len(rows), freq="5min", tz=IST)
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx, dtype=float)
    df["volume"] = 1000
    return df


def session(day="2026-09-23", price=100.0, overrides=None) -> pd.DataFrame:
    """A full trading day of flat candles, with optional {candle_index: (o, h, l, c)} overrides."""
    rows = [flat(price)] * SESSION
    for i, r in (overrides or {}).items():
        rows[i] = r
    return candles(rows, day)


class ScriptedStrategy(Strategy):
    """Emits exactly the signals in `script` ({candle_index: Signal}); causal by construction."""

    def __init__(self, script):
        self.script = script
        self.warmup_candles = 1

    @property
    def name(self) -> str:
        return "scripted"

    def generate_signal(self, data):
        return self.script.get(len(data) - 1, HOLD)

    def generate_signals(self, data):
        return pd.Series([self.script.get(i, HOLD) for i in range(len(data))], index=data.index, dtype=object)


def run(data, script, charges=NO_FEES, **cfg_kw):
    return Backtester(cfg(**cfg_kw), ScriptedStrategy(script), charges).run(data)


def random_walk(n_days=4, seed=0, start_price=1500.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = []
    for d in pd.bdate_range("2026-03-02", periods=n_days):
        idx += list(pd.date_range(f"{d.date()} 09:15", periods=SESSION, freq="5min", tz=IST))
    n = len(idx)
    close = start_price * np.exp(np.cumsum(rng.normal(0, 0.0007, n)))
    op = np.r_[close[0], close[:-1]]
    hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, 0.0003, n)))
    lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, 0.0003, n)))
    return pd.DataFrame({"open": op, "high": hi, "low": lo, "close": close, "volume": 1000},
                        index=pd.DatetimeIndex(idx))
