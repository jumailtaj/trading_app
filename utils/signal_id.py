"""Deterministic signal identifier generation."""
from __future__ import annotations

import hashlib
from datetime import datetime

from models import Signal, TradingMode
from utils.timeutil import to_iso, to_ist


def generate_signal_id(
    mode: TradingMode,
    symbol: str,
    timeframe: str,
    candle_time: datetime,
    signal: Signal,
) -> str:
    """Generate a deterministic 16-character hex signal_id.

    Formula: sha256(mode:symbol:timeframe:closed_candle_iso:signal)[:16]
    """
    candle_iso = to_iso(to_ist(candle_time))
    raw = f"{mode.value}:{symbol}:{timeframe}:{candle_iso}:{signal.value}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
