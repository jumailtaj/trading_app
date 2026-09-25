"""EMA crossover strategy (default 9/21).

BUY  when the fast EMA crosses above the slow EMA.
SELL when the fast EMA crosses below the slow EMA.
Anything else is HOLD, so a crossover produces exactly ONE signal, on the candle where it happens.

Definition of "cross": the sign of (fast - slow) flips. If the two EMAs are exactly equal on
some candle, the previous sign is carried forward, so "above -> touch -> above" is not a cross,
while "below -> touch -> above" is (the BUY appears on the first candle that is strictly above).
This matches the spec's "prev <= and now >" / "prev >= and now <" rule for every real crossover.

No look-ahead: EMAs are computed with an adjust=False recursive filter, which only looks
backwards. Signals are suppressed until `warmup_candles` candles exist, because an EMA seeded
on the first close is not trustworthy for roughly 3x its span.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from models import Signal
from strategy.base_strategy import Strategy


class EMACrossoverStrategy(Strategy):
    def __init__(self, fast_period: int = 9, slow_period: int = 21, warmup_candles: Optional[int] = None):
        for label, value in (("fast_period", fast_period), ("slow_period", slow_period)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{label} must be a positive whole number, got {value!r}")
        if fast_period >= slow_period:
            raise ValueError(f"fast_period ({fast_period}) must be smaller than slow_period ({slow_period})")
        warmup = 3 * slow_period if warmup_candles is None else warmup_candles
        if isinstance(warmup, bool) or not isinstance(warmup, int) or warmup < slow_period + 1:
            raise ValueError(f"warmup_candles must be a whole number >= slow_period + 1, got {warmup!r}")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.warmup_candles = warmup

    @property
    def name(self) -> str:
        return f"EMA {self.fast_period}/{self.slow_period}"

    def _ema_lines(self, close: pd.Series) -> tuple[pd.Series, pd.Series]:
        return (
            close.ewm(span=self.fast_period, adjust=False).mean(),
            close.ewm(span=self.slow_period, adjust=False).mean(),
        )

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """Signal for EVERY candle in `data`, each using only that candle and earlier ones.

        Vectorised override used by backtests; generate_signal() returns the last element of this
        series, so both paths share one implementation.
        """
        self.validate_candles(data)
        signals = pd.Series(Signal.HOLD, index=data.index, dtype=object)
        if len(data) == 0:
            return signals
        close = pd.to_numeric(data["close"]).astype(float)
        fast, slow = self._ema_lines(close)
        state = pd.Series(np.sign((fast - slow).to_numpy()), index=data.index).replace(0.0, np.nan).ffill()
        prev = state.shift(1)
        signals[((prev < 0) & (state > 0)).to_numpy()] = Signal.BUY
        signals[((prev > 0) & (state < 0)).to_numpy()] = Signal.SELL
        signals.iloc[: self.warmup_candles - 1] = Signal.HOLD   # not enough history yet
        return signals

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        self.validate_candles(data)
        if len(data) < self.warmup_candles:
            return Signal.HOLD
        return self.generate_signals(data).iloc[-1]
