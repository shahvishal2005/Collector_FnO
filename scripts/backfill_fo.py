# What: command line for the F&O bhavcopy backfill (download, parse, store, manifest, report).
# In: optional --start/--end/--limit/--recheck-missing/--reprocess/--no-report. Out: data files.
"""Run the F&O archive backfill. Safe to stop and start again: it resumes."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from collector.common.logsetup import setup_logging
from collector.common.timeutil import today_ist
from collector.config import ConfigError, config_hash, load_config
from collector.jobs.backfill_fo import run_backfill
from collector.nse.client import NseClient
from collector.nse.tradingdays import build_calendar
from collector.quality.report import build_report
from collector.store.catalogue import Catalogue
from collector.store.layout import Layout
from collector.store.manifest import build_manifest

log = logging.getLogger("backfill_fo")


def _parse_args() -> argparse.Namespace:
    """Command-line options."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="path to config.yaml")
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--limit", type=int, default=None, help="process at most N new days")
    parser.add_argument(
        "--recheck-missing", action="store_true", help="retry days NSE said 'not found'"
    )
    parser.add_argument(
        "--reprocess", action="store_true", help="rebuild silver from bronze for all days"
    )
    parser.add_argument(
        "--no-report", action="store_true", help="skip manifest and report at the end"
    )
    return parser.parse_args()


def main() -> int:
    """Run the backfill; return a process exit code."""
    args = _parse_args()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    setup_logging(cfg.paths.logs_root, "backfill_fo")
    log.info("config hash %s", config_hash(cfg))
    start = args.start or cfg.backfill.start_date
    end = args.end or cfg.backfill.end_date or (today_ist() - timedelta(days=1))
    layout = Layout(cfg.paths.data_root)
    catalogue = Catalogue(layout.catalogue_path)
    calendar = build_calendar(cfg.backfill.start_date, end, cfg.paths.nifty_candles_root)
    summary = run_backfill(
        cfg, layout, catalogue, NseClient(cfg.nse), calendar,
        start=start, end=end, limit=args.limit,
        recheck_missing=args.recheck_missing, reprocess=args.reprocess,
    )  # fmt: skip
    log.info("summary: %s", summary)
    if not args.no_report:
        manifest = build_manifest(layout)
        log.info("manifest rows: %d", len(manifest))
        result = build_report(cfg, layout, catalogue, calendar)
        log.info("report: %s", result)
    return 1 if (summary.aborted or summary.parse_errors) else 0


if __name__ == "__main__":
    sys.exit(main())
