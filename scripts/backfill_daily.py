# What: command line for the daily-file datasets (participant OI/volume, ban list, index close).
# In: --dataset NAME|all, optional --start/--end/--limit/--recheck-missing/--reprocess/--no-report.
# Out: bronze and silver files, manifests and reports. Safe to stop and start again: it resumes.
"""Backfill the M3 datasets from the NSE archive."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

from collector.common.logsetup import setup_logging
from collector.common.timeutil import today_ist
from collector.config import ConfigError, config_hash, load_config
from collector.datasets.registry import DATASETS
from collector.jobs.backfill_daily import run_dataset_backfill
from collector.nse.client import NseClient
from collector.nse.tradingdays import build_calendar
from collector.quality.daily_report import build_dataset_report
from collector.store.catalogue import Catalogue
from collector.store.dataset_manifest import build_dataset_manifest
from collector.store.layout import Layout

log = logging.getLogger("backfill_daily")


def main() -> int:
    """Run the chosen dataset(s); return a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="all", help="one of: all, " + ", ".join(DATASETS))
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--start", type=date.fromisoformat, default=None)
    parser.add_argument("--end", type=date.fromisoformat, default=None)
    parser.add_argument("--limit", type=int, default=None, help="process at most N new days each")
    parser.add_argument("--recheck-missing", action="store_true")
    parser.add_argument("--reprocess", action="store_true", help="rebuild silver from bronze")
    parser.add_argument("--no-report", action="store_true")
    args = parser.parse_args()
    if args.dataset != "all" and args.dataset not in DATASETS:
        print(
            f"unknown dataset {args.dataset!r}; choose from: all, {', '.join(DATASETS)}",
            file=sys.stderr,
        )
        return 2
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    setup_logging(cfg.paths.logs_root, "backfill_daily")
    log.info("config hash %s", config_hash(cfg))
    start = args.start or cfg.backfill.start_date
    end = args.end or cfg.backfill.end_date or (today_ist() - timedelta(days=1))
    layout = Layout(cfg.paths.data_root)
    catalogue = Catalogue(layout.catalogue_path)
    calendar = build_calendar(cfg.backfill.start_date, end, cfg.paths.nifty_candles_root)
    client = NseClient(cfg.nse)
    names = list(DATASETS) if args.dataset == "all" else [args.dataset]
    failed = False
    for name in names:
        dataset = DATASETS[name]
        summary = run_dataset_backfill(
            cfg, layout, catalogue, client, calendar, dataset, start=start, end=end,
            limit=args.limit, recheck_missing=args.recheck_missing, reprocess=args.reprocess,
        )  # fmt: skip
        log.info("%s summary: %s", name, summary)
        failed = failed or summary.aborted or bool(summary.parse_errors)
        if not args.no_report:
            manifest = build_dataset_manifest(layout, name)
            report = build_dataset_report(cfg, layout, catalogue, calendar, dataset)
            log.info("%s manifest rows %d; report %s", name, len(manifest), report)
        if summary.aborted:
            break  # the source is unhappy: do not move on to the next dataset
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
