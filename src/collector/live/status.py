# What: a small status file the operator (or a monitor) can read to see how the day is going.
# In: running totals from the scheduler. Out: data/live_status.json, rewritten atomically.
"""Status file for the live collector."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path

from collector.store.parquet import write_atomic_bytes


@dataclass
class Status:
    """Totals so far today."""

    day: str
    state: str  # 'waiting', 'running', 'finished', 'stopped'
    cycles: int = 0
    ok_calls: int = 0
    failed_calls: int = 0
    rows: int = 0
    skipped_slots: int = 0
    last_cycle_ts: str | None = None
    reason: str = ""
    updated_at: str = ""


def write_status(path: Path, status: Status, now: datetime) -> None:
    """Write the status as JSON (atomically, so a reader never sees half a file)."""
    status.updated_at = now.isoformat()
    write_atomic_bytes(path, json.dumps(asdict(status), indent=1).encode("utf-8"))


def read_status(path: Path) -> dict[str, object] | None:
    """Read the status file back, or None if it does not exist or is unreadable."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def done_marker_path(root: Path, day: date) -> Path:
    """The file that says 'today's capture is complete' (so relaunches exit at once)."""
    return root / "live_done" / f"{day.isoformat()}.json"


def is_done(root: Path, day: date) -> bool:
    """True if today's capture already finished normally (or the market was closed)."""
    return done_marker_path(root, day).is_file()


def write_done(root: Path, day: date, summary: dict[str, object], now: datetime) -> None:
    """Record that the day is complete, with the run's summary."""
    payload = {"day": day.isoformat(), "finished_at": now.isoformat(), **summary}
    write_atomic_bytes(done_marker_path(root, day), json.dumps(payload, indent=1).encode("utf-8"))
