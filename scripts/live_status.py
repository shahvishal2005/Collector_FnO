# What: show how the live capture is doing today (cycles, failures, gaps).
# In: optional --date / --test / --config. Out: a text summary; exit code 1 if unhealthy.
"""Live capture status for the operator."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from collector.common.timeutil import IST, now_ist, today_ist
from collector.config import ConfigError, load_config
from collector.live.status import read_status
from collector.store.layout import Layout


def main() -> int:
    """Print the summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--date", type=date.fromisoformat, default=None)
    parser.add_argument("--test", action="store_true", help="look at data/_test instead")
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    root = cfg.paths.data_root / "_test" if args.test else cfg.paths.data_root
    layout = Layout(root)
    day = args.date or today_ist()
    status = read_status(root / "live_status.json")
    print(f"== live status for {day}")
    if status:
        print(
            f"state={status['state']} cycles={status['cycles']} ok_calls={status['ok_calls']} "
            f"failed_calls={status['failed_calls']} rows={status['rows']} "
            f"skipped_slots={status['skipped_slots']} last_cycle={status['last_cycle_ts']} "
            f"updated={status['updated_at']} reason={status['reason']!r}"
        )
    else:
        print("no status file yet")
    folder = layout.live_health_dir(day)
    cycles_file, calls_file = folder / "cycles.csv", folder / "calls.csv"
    if not cycles_file.is_file():
        print("no health records for this day")
        return 1
    cycles = pd.read_csv(cycles_file)
    calls = pd.read_csv(calls_file)
    cap = cfg.live.capture
    first = datetime.combine(day, cap.capture_start, tzinfo=IST)
    last = datetime.combine(day, cap.capture_end, tzinfo=IST)
    horizon = min(now_ist(), last) if day == today_ist() else last
    expected = max(0, int((horizon - first) // timedelta(seconds=cap.tier1_interval_seconds)) + 1)
    print(f"cycles recorded: {len(cycles)} (about {expected} expected by now)")
    n_failed = int((~calls["ok"]).sum())
    print(f"calls: {len(calls)}, failed: {n_failed}, rows stored: {int(cycles['rows'].sum())}")
    failed = calls[~calls["ok"]]
    if len(failed):
        print("failures by kind:", failed["error_kind"].value_counts().to_dict())
        print("failures by underlying:", failed["underlying"].value_counts().head(8).to_dict())
    median, slowest = calls["seconds"].median(), calls["seconds"].max()
    print(f"median call time: {median:.2f}s, slowest: {slowest:.2f}s")
    limits, skipped = int(cycles["rate_limit_hits"].sum()), int(cycles["skipped_slots"].sum())
    print(f"rate-limit answers: {limits}, skipped slots: {skipped}")
    files = len(list(layout.chain_silver_dir(day).glob("cycle_*.parquet")))
    print(f"chain files stored: {files}")
    healthy = len(cycles) >= 0.9 * expected and not (len(failed) > 0.05 * max(1, len(calls)))
    print("verdict:", "OK" if healthy else "CHECK (missing cycles or many failures)")
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
