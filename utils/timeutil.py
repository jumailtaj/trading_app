"""Time helpers. Everything the app stores or compares is timezone-aware IST."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    return datetime.now(IST)


def to_ist(dt: datetime) -> datetime:
    """Convert an aware datetime to IST. Naive datetimes are rejected, never guessed."""
    if not isinstance(dt, datetime):
        raise TypeError(f"expected datetime, got {type(dt).__name__}")
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive datetime not allowed; attach a timezone (use utils.timeutil.IST)")
    return dt.astimezone(IST)


def to_iso(dt: datetime) -> str:
    """IST ISO-8601 string. Because it is always IST, the first 10 chars are the IST date."""
    return to_ist(dt).isoformat(timespec="seconds")


def from_iso(text: str) -> datetime:
    return to_ist(datetime.fromisoformat(text))
