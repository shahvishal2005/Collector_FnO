# What: Indian Standard Time helpers. All collector timestamps are timezone-aware IST.
# In: dates or datetimes. Out: aware datetimes, date ranges.
"""Time helpers. Naive datetimes are refused so a timezone slip cannot enter the data."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """The current time in IST (timezone-aware)."""
    return datetime.now(IST)


def today_ist() -> date:
    """Today's date in India."""
    return now_ist().date()


def require_aware(value: datetime) -> datetime:
    """Return the value unchanged if it has a timezone, otherwise raise ValueError."""
    if value.tzinfo is None:
        raise ValueError("naive datetime refused: timestamps must be timezone-aware")
    return value


def daterange(start: date, end: date) -> Iterator[date]:
    """Every calendar day from start to end, both included."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)
