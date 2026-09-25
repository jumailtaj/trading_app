"""Market data loading utilities (CSV loader and Kite historical data fetcher)."""
from __future__ import annotations

import pathlib
from typing import Any, Union
import pandas as pd

from backtest.engine import BacktestDataError, Backtester
from utils.timeutil import IST


class DataLoadError(ValueError):
    """Raised when historical candle data cannot be loaded or parsed."""


COLUMN_ALIASES: dict[str, str] = {
    "date": "timestamp",
    "datetime": "timestamp",
    "time": "timestamp",
    "timestamp": "timestamp",
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "vol": "volume",
    "volume": "volume",
}


def load_csv(path: Union[str, pathlib.Path]) -> pd.DataFrame:
    """Load historical candles from CSV into the standard backtest engine schema.

    Requirements:
    - Must contain open, high, low, close columns (case-insensitive).
    - Timestamps will be normalized to timezone-aware Asia/Kolkata (IST).
    - Sorted chronologically, unique index.
    - Validated by Backtester._prepare().
    """
    p = pathlib.Path(path)
    if not p.exists():
        raise DataLoadError(f"CSV file does not exist: {p}")

    try:
        df = pd.read_csv(p)
    except Exception as exc:
        raise DataLoadError(f"Failed to read CSV at {p}: {exc}") from exc

    if df.empty:
        raise DataLoadError(f"CSV file is empty: {p}")

    # Map column names via aliases
    col_map: dict[str, str] = {}
    for col in df.columns:
        norm = str(col).strip().lower()
        if norm in COLUMN_ALIASES:
            col_map[col] = COLUMN_ALIASES[norm]
        else:
            col_map[col] = norm

    df = df.rename(columns=col_map)

    # Find timestamp column or check if index already has it
    if "timestamp" in df.columns:
        try:
            ts = pd.to_datetime(df["timestamp"])
        except Exception as exc:
            raise DataLoadError(f"Failed to parse 'timestamp' column in {p}: {exc}") from exc
        df = df.drop(columns=["timestamp"])
        df.index = ts
    elif not isinstance(df.index, pd.DatetimeIndex):
        first_col = df.columns[0]
        try:
            ts = pd.to_datetime(df[first_col])
            df = df.drop(columns=[first_col])
            df.index = ts
        except Exception as exc:
            raise DataLoadError(f"No timestamp column found and index is not DatetimeIndex in {p}") from exc

    # Ensure timezone is IST
    if df.index.tz is None:
        try:
            df.index = df.index.tz_localize(IST)
        except Exception as exc:
            raise DataLoadError(f"Ambiguous or invalid timestamps when localizing to IST in {p}: {exc}") from exc
    else:
        df.index = df.index.tz_convert(IST)

    # Check required columns
    required = {"open", "high", "low", "close"}
    missing = required - set(df.columns)
    if missing:
        raise DataLoadError(f"CSV at {p} missing required columns: {sorted(missing)}")

    # Keep only open, high, low, close, and volume (if present)
    keep_cols = ["open", "high", "low", "close"]
    if "volume" in df.columns:
        keep_cols.append("volume")
    df = df[keep_cols]

    # Validate using Backtester._prepare
    try:
        validated = Backtester._prepare(df)
    except BacktestDataError as exc:
        raise DataLoadError(f"Data in {p} failed validation: {exc}") from exc

    return validated


def load_kite(kite_client: Any, symbol: str, from_date: Any, to_date: Any, interval: str = "5minute") -> pd.DataFrame:
    """Placeholder for Kite Connect historical data fetching (deferred to Phase D/E)."""
    raise NotImplementedError("Kite fetch is not available until Phase D")
