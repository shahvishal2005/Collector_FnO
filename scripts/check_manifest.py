# What: prove stored data still matches its manifest (nothing changed, nothing missing).
# In: optional --dataset (fo_eod by default, a dataset name, or all) and --config.
# Out: "OK" and exit code 0, or a list of problems and exit code 1.
"""Check a dataset against its manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from collector.config import ConfigError, load_config
from collector.datasets.registry import DATASETS
from collector.store.dataset_manifest import check_dataset_manifest
from collector.store.layout import Layout
from collector.store.manifest import check_manifest


def main() -> int:
    """Run the check(s)."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--dataset", default="fo_eod", help="fo_eod, all, or " + ", ".join(DATASETS)
    )
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    layout = Layout(cfg.paths.data_root)
    names = ["fo_eod", *DATASETS] if args.dataset == "all" else [args.dataset]
    exit_code = 0
    for name in names:
        if name == "fo_eod":
            problems = check_manifest(layout)
        elif name in DATASETS:
            problems = check_dataset_manifest(layout, name)
        else:
            print(f"unknown dataset {name!r}", file=sys.stderr)
            return 2
        if problems:
            exit_code = 1
            print(f"{name}: {len(problems)} problem(s):")
            for line in problems[:50]:
                print(" -", line)
        else:
            print(f"OK: {name}: all silver files match the manifest")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
