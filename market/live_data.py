"""Market data feeds (ReplayFeed, FakeFeed) and tick-to-candle aggregation."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterator, Optional
import numpy as np
import pandas as pd

from utils.timeutil import IST, now_ist, to_ist


class StaleFeedError(RuntimeError):
    """Raised when data feed stops producing ticks/candles past the stale threshold."""


class ReplayFeed:
    """Historical candle replay feed simulating live closed candle delivery."""

    def __init__(self, data: pd.DataFrame, stale_threshold_seconds: float = 30.0) -> None:
        if data.empty:
            raise ValueError("ReplayFeed requires a non-empty DataFrame")
        self.data = data.copy()
        if self.data.index.tz is None:
            self.data.index = self.data.index.tz_localize(IST)
        else:
            self.data.index = self.data.index.tz_convert(IST)

        self.stale_threshold_seconds = stale_threshold_seconds
        self._index = 0
        self._total = len(self.data)
        self.last_tick_time: Optional[datetime] = None

    def __iter__(self) -> Iterator[pd.Series]:
        return self

    def __next__(self) -> pd.Series:
        candle = self.next_candle()
        if candle is None:
            raise StopIteration
        return candle

    def next_candle(self, current_time: Optional[datetime] = None) -> Optional[pd.Series]:
        """Fetch the next closed candle from the replay buffer, checking freshness."""
        now = to_ist(current_time or now_ist())
        if self.last_tick_time is not None:
            elapsed = (now - self.last_tick_time).total_seconds()
            if elapsed > self.stale_threshold_seconds:
                raise StaleFeedError(
                    f"Feed became stale: {elapsed:.1f}s since last tick (limit {self.stale_threshold_seconds}s)"
                )

        if self._index >= self._total:
            return None

        candle = self.data.iloc[self._index]
        self._index += 1
        self.last_tick_time = now
        return candle

    @property
    def has_next(self) -> bool:
        return self._index < self._total


class FakeFeed:
    """Synthetic OHLCV candle generator for unit tests."""

    @staticmethod
    def generate(
        symbol: str = "TEST",
        candles: int = 50,
        start_price: float = 100.0,
        start_time: Optional[datetime] = None,
        freq_minutes: int = 5,
    ) -> pd.DataFrame:
        start = to_ist(start_time or datetime(2026, 9, 23, 9, 15, tzinfo=IST))
        idx = pd.date_range(start=start, periods=candles, freq=f"{freq_minutes}min", tz=IST)
        np.random.seed(42)
        returns = np.random.normal(0, 0.005, size=candles)
        prices = start_price * np.cumprod(1 + returns)

        opens = prices
        highs = opens * (1 + np.abs(np.random.normal(0, 0.003, size=candles)))
        lows = opens * (1 - np.abs(np.random.normal(0, 0.003, size=candles)))
        closes = (highs + lows) / 2
        volume = np.random.randint(100, 10000, size=candles)

        df = pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volume},
            index=idx,
        )
        return df


class CandleBuilder:
    """Accumulates ticks and emits closed candles on timeframe boundaries."""

    def __init__(self, timeframe_minutes: int = 5) -> None:
        self.timeframe_minutes = timeframe_minutes
        self._current_boundary: Optional[datetime] = None
        self._open: Optional[float] = None
        self._high: Optional[float] = None
        self._low: Optional[float] = None
        self._close: Optional[float] = None
        self._volume: int = 0

    def _get_boundary(self, dt: datetime) -> datetime:
        """Floor dt to the start of its timeframe interval."""
        dt_ist = to_ist(dt)
        discard_mins = dt_ist.minute % self.timeframe_minutes
        boundary = dt_ist.replace(minute=dt_ist.minute - discard_mins, second=0, microsecond=0)
        return boundary

    def add_tick(self, timestamp: datetime, price: float, volume: int = 1) -> Optional[dict]:
        """Process a tick. Returns a closed candle dictionary if this tick crossed a boundary."""
        ts = to_ist(timestamp)
        tick_boundary = self._get_boundary(ts)
        closed_candle = None

        if self._current_boundary is not None and tick_boundary > self._current_boundary:
            closed_candle = {
                "timestamp": self._current_boundary,
                "open": self._open,
                "high": self._high,
                "low": self._low,
                "close": self._close,
                "volume": self._volume,
            }
            # Start new candle
            self._current_boundary = tick_boundary
            self._open = price
            self._high = price
            self._low = price
            self._close = price
            self._volume = volume
        elif self._current_boundary is None:
            self._current_boundary = tick_boundary
            self._open = price
            self._high = price
            self._low = price
            self._close = price
            self._volume = volume
        else:
            # Same candle
            self._high = max(self._high, price)  # type: ignore[type-var]
            self._low = min(self._low, price)    # type: ignore[type-var]
            self._close = price
            self._volume += volume

        return closed_candle
