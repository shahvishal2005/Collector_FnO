# What: decide which days to ask NSE for, and which days the market was really open.
# In: a date range and (optionally) the research platform's Nifty 1-minute candle folder.
# Out: the list of candidate days and, when candles are available, the known trading days.
"""Trading-day knowledge.

NSE returns 404 for holidays, so we try every weekday, plus any weekend day on which the Nifty
candles show a trading session (for example Muhurat trading). The candle folder is read-only and
optional; without it only weekdays are tried and the report cannot judge missing days.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq

from collector.common.timeutil import daterange

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TradingCalendar:
    """Candidate days to request, plus what we know about real trading days."""

    candidates: list[date]
    known_trading_days: frozenset[date] | None
    known_until: date | None


def trading_days_from_candles(root: Path) -> frozenset[date]:
    """Every date that has at least one candle in the Nifty candle folder (read-only)."""
    days: set[date] = set()
    for file in sorted(root.glob("year=*/candles.parquet")):
        column = pq.read_table(file, columns=["ts"]).column("ts").to_pandas()
        days.update(column.dt.date.unique())
    return frozenset(days)


def calendar_with_fallback(
    start: date, end: date, candles_root: Path | None, fallback_days: frozenset[date]
) -> TradingCalendar:
    """Like build_calendar, but when no candle folder is available (for example on the VPS) the
    given days (the dates that have F&O files) are used as the known trading days."""
    calendar = build_calendar(start, end, candles_root)
    if calendar.known_trading_days is not None or not fallback_days:
        return calendar
    known = frozenset(d for d in fallback_days if d <= end)
    extra = [d for d in known if start <= d <= end and d.weekday() >= 5]
    return TradingCalendar(
        sorted(set(calendar.candidates) | set(extra)), known, max(known) if known else None
    )


def build_calendar(start: date, end: date, candles_root: Path | None) -> TradingCalendar:
    """Candidate days between start and end (inclusive), enriched with candle knowledge."""
    known: frozenset[date] | None = None
    known_until: date | None = None
    if candles_root is not None and candles_root.is_dir():
        known = trading_days_from_candles(candles_root)
        known_until = max(known) if known else None
        log.info("loaded %d trading days from candles (until %s)", len(known), known_until)
    elif candles_root is not None:
        log.warning("candle folder %s not found; using weekdays only", candles_root)
    weekdays = [d for d in daterange(start, end) if d.weekday() < 5]
    extra = [d for d in (known or frozenset()) if start <= d <= end and d.weekday() >= 5]
    return TradingCalendar(sorted(set(weekdays) | set(extra)), known, known_until)
