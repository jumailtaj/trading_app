"""Unit tests for market data feeds (ReplayFeed, FakeFeed) and CandleBuilder."""
from datetime import datetime, timedelta
import pytest
import pandas as pd

from market.live_data import CandleBuilder, FakeFeed, ReplayFeed, StaleFeedError
from utils.timeutil import IST


def test_replay_feed_yields_closed_candles_in_order():
    df = FakeFeed.generate(symbol="INFY", candles=10)
    feed = ReplayFeed(df)
    candles = []
    while feed.has_next:
        c = feed.next_candle()
        if c is not None:
            candles.append(c)

    assert len(candles) == 10
    # Check monotonic timestamps
    timestamps = [c.name for c in candles]
    assert sorted(timestamps) == timestamps


def test_replay_feed_stale_raises_stale_feed_error():
    df = FakeFeed.generate(symbol="INFY", candles=5)
    feed = ReplayFeed(df, stale_threshold_seconds=10.0)

    t0 = datetime(2026, 9, 23, 9, 15, tzinfo=IST)
    c1 = feed.next_candle(current_time=t0)
    assert c1 is not None

    # Jump 30 seconds later -> exceeds stale threshold of 10s
    t1 = t0 + timedelta(seconds=30)
    with pytest.raises(StaleFeedError, match="Feed became stale"):
        feed.next_candle(current_time=t1)


def test_fake_feed_produces_valid_ohlcv():
    df = FakeFeed.generate(symbol="TCS", candles=20)
    assert len(df) == 20
    assert set(df.columns) >= {"open", "high", "low", "close", "volume"}
    assert (df["high"] >= df["low"]).all()
    assert (df["high"] >= df["open"]).all()
    assert (df["high"] >= df["close"]).all()
    assert (df["low"] <= df["open"]).all()
    assert (df["low"] <= df["close"]).all()


def test_candle_builder_emits_only_closed_candles():
    builder = CandleBuilder(timeframe_minutes=5)
    t0 = datetime(2026, 9, 23, 9, 15, 10, tzinfo=IST)
    t1 = datetime(2026, 9, 23, 9, 17, 30, tzinfo=IST)
    t2 = datetime(2026, 9, 23, 9, 19, 50, tzinfo=IST)
    t_next = datetime(2026, 9, 23, 9, 20, 5, tzinfo=IST)

    # First ticks in 9:15-9:20 bucket
    assert builder.add_tick(t0, 100.0, 10) is None
    assert builder.add_tick(t1, 105.0, 20) is None
    assert builder.add_tick(t2, 98.0, 15) is None

    # Tick crossing the 9:20 boundary emits closed 9:15 candle
    closed = builder.add_tick(t_next, 102.0, 5)
    assert closed is not None
    assert closed["open"] == 100.0
    assert closed["high"] == 105.0
    assert closed["low"] == 98.0
    assert closed["close"] == 98.0
    assert closed["volume"] == 45
    assert closed["timestamp"] == datetime(2026, 9, 23, 9, 15, tzinfo=IST)
