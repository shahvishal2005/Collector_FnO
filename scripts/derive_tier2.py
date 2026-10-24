# What: propose the Tier 2 stock list from the most recent stored days of option data.
# In: optional --config / --top. Out: data/reports/tier2_candidates.csv and a printed table.
"""Rank F&O stocks by option activity and write the proposal (for the owner to review)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from collector.config import ConfigError, load_config
from collector.store.layout import Layout
from collector.store.manifest import silver_days
from collector.store.parquet import read_table
from collector.universe.tier2 import rank_option_activity


def main() -> int:
    """Rank and save."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--top", type=int, default=None, help="override universe.tier2_size")
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    layout = Layout(cfg.paths.data_root)
    days = silver_days(layout)[-cfg.universe.window_days :]
    if not days:
        print("no stored days found; run the backfill first", file=sys.stderr)
        return 1
    frames = [read_table(layout.fo_silver_file(day)) for day in days]
    top = args.top or cfg.universe.tier2_size
    ranked = rank_option_activity(frames, top, cfg.universe.min_day_share)
    layout.reports_root.mkdir(parents=True, exist_ok=True)
    out = layout.reports_root / "tier2_candidates.csv"
    ranked.to_csv(out, index=False)
    basis = ranked["basis"].iloc[0] if len(ranked) else "n/a"
    print(f"{len(days)} days ({days[0]} to {days[-1]}); basis: {basis}")
    print(ranked.to_string(index=False))
    print(f"written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
