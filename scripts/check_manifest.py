# What: prove the stored fo_eod files still match the manifest (nothing changed, nothing missing).
# In: optional --config. Out: "OK" and exit code 0, or a list of problems and exit code 1.
"""Check the fo_eod data against its manifest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from collector.config import ConfigError, load_config
from collector.store.layout import Layout
from collector.store.manifest import check_manifest


def main() -> int:
    """Run the check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    problems = check_manifest(Layout(cfg.paths.data_root))
    if problems:
        print(f"{len(problems)} problem(s):")
        for line in problems[:50]:
            print(" -", line)
        return 1
    print("OK: all silver files match the manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
