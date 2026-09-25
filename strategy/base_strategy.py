"""Strategy interface.

A strategy turns candles into a Signal and NOTHING else. It never sees a broker, a
database, an order, or the current position. Risk checks and order placement belong to
the trading engine (Phase 4+), so the same strategy runs unchanged in backtest, paper
and live.

Data contract (the caller guarantees this):
  * a pandas DataFrame with at least a `close` column, oldest candle first,
    unique increasing index (candle open time);
  * it contains ONLY CLOSED candles. The last row is the most recent closed candle.
    A still-forming candle must never be passed in.
Timing rule used everywhere: a signal produced from candle N's close is executed at
candle N+1's open.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from models import Signal


class StrategyDataError(ValueError):
    """The candle data handed to a strategy is unusable. Callers must treat this as 'do not trade'."""


class Strategy(ABC):
    warmup_candles: int = 1

    @property
    @abstractmethod
    def name(self) -> str:
        """Short label for the UI, e.g. 'EMA 9/21'."""

    @abstractmethod
    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """Return BUY, SELL or HOLD for the most recent closed candle in `data`."""

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Signal for EVERY candle, where signal[i] may use candles 0..i only.

        This default is slow (it re-runs generate_signal on each growing prefix) but is correct
        by construction. Strategies may override it with a faster vectorised version; the
        backtest engine spot-checks any override against generate_signal to catch look-ahead.
        Implement at least one of the two independently: this default calls generate_signal, so a
        generate_signal that itself calls generate_signals must not fall back to this default.
        """
        self.validate_candles(data)
        out = pd.Series(Signal.HOLD, index=data.index, dtype=object)
        for i in range(max(self.warmup_candles, 1) - 1, len(data)):
            out.iloc[i] = self.generate_signal(data.iloc[: i + 1])
        return out

    @staticmethod
    def validate_candles(data: pd.DataFrame) -> None:
        if not isinstance(data, pd.DataFrame):
            raise StrategyDataError(f"candles must be a DataFrame, got {type(data).__name__}")
        if "close" not in data.columns:
            raise StrategyDataError("candles must have a 'close' column")
        if not (data.index.is_unique and data.index.is_monotonic_increasing):
            raise StrategyDataError("candle index must be unique and sorted oldest to newest")
        close = pd.to_numeric(data["close"], errors="coerce")
        if len(close) and not close.map(pd.notna).all():
            raise StrategyDataError("close prices contain missing or non-numeric values")
        if len(close) and not ((close > 0) & (close < float("inf"))).all():
            raise StrategyDataError("close prices must be positive and finite")
