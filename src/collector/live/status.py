# What: a small status file the operator (or a monitor) can read to see how the day is going.
# In: running totals from the scheduler. Out: data/live_status.json, rewritten atomically.
"""Status file for the live collector."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
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
