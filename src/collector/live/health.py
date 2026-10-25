# What: health records of the live capture: one row per API call and one per cycle (CSV, appended).
# In: records produced by the collector. Out: CSV files under data/silver/live_health/<date>/.
"""Health logging.

These files answer 'what did we miss and why?' after the fact. A failed call is a row, not a
silent hole: gaps are visible, never filled.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime
from pathlib import Path


@dataclass(frozen=True)
class CallHealth:
    """The outcome of one API call."""

    trade_date: date
    cycle_ts: datetime
    underlying: str
    expiry_epoch: str
    tier: int
    ok: bool
    error_kind: str  # '', 'rate_limit', 'auth', 'api', 'shape', 'exception'
    error_code: int | None
    seconds: float
    rows: int


@dataclass(frozen=True)
class CycleHealth:
    """The outcome of one capture cycle."""

    trade_date: date
    cycle_ts: datetime
    started: datetime
    finished: datetime
    planned_calls: int
    ok_calls: int
    failed_calls: int
    rows: int
    rate_limit_hits: int
    skipped_slots: int  # slots missed because the previous cycle ran long


def _append(path: Path, record: object, record_type: type) -> None:
    """Append one dataclass row to a CSV file, writing the header if the file is new."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    names = [f.name for f in fields(record_type)]
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        if new_file:
            writer.writeheader()
        writer.writerow(asdict(record))  # type: ignore[call-overload]


class HealthLog:
    """Appends call and cycle records for one trading day."""

    def __init__(self, folder: Path) -> None:
        """Remember the day's folder."""
        self._folder = folder

    def call(self, record: CallHealth) -> None:
        """Record one API call."""
        _append(self._folder / "calls.csv", record, CallHealth)

    def cycle(self, record: CycleHealth) -> None:
        """Record one cycle."""
        _append(self._folder / "cycles.csv", record, CycleHealth)
