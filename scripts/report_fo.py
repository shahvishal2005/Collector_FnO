# What: rebuild the manifest and the quality report from the stored data (no downloads).
# In: optional --config. Out: data/manifests/fo_eod_manifest.csv and data/reports/*.
"""Regenerate the manifest and the F&O quality report."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta
from pathlib import Path

from collector.common.logsetup import setup_logging
from collector.common.timeutil import today_ist
from collector.config import ConfigError, load_config
from collector.nse.tradingdays import build_calendar
from collector.quality.report import build_report
from collector.store.catalogue import Catalogue
from collector.store.layout import Layout
from collector.store.manifest import build_manifest

log = logging.getLogger("report_fo")


def main() -> int:
    """Write the manifest and the report; print the headline numbers."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    setup_logging(cfg.paths.logs_root, "report_fo")
    layout = Layout(cfg.paths.data_root)
    end = cfg.backfill.end_date or (today_ist() - timedelta(days=1))
    calendar = build_calendar(cfg.backfill.start_date, end, cfg.paths.nifty_candles_root)
    manifest = build_manifest(layout)
    result = build_report(cfg, layout, Catalogue(layout.catalogue_path), calendar)
    log.info("manifest rows: %d; report: %s", len(manifest), result)
    print(f"report written to {layout.reports_root / 'fo_eod_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
