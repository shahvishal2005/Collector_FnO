# What: check config\config.yaml against config\config.example.yaml (drift after an update) and load it.
# In: optional --config / --example. Out: a short report; exit code 1 if the config is unusable.
"""Report config drift. It never edits any file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from collector.config import ConfigError, load_config
from collector.config.compare import compare_config


def main() -> int:
    """Compare, then try to load; print what to fix."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config/config.yaml"))
    parser.add_argument("--example", type=Path, default=Path("config/config.example.yaml"))
    args = parser.parse_args()
    if not args.config.is_file():
        print(f"{args.config} not found: copy {args.example} to it first")
        return 1
    missing, unknown = compare_config(args.example, args.config)
    if missing:
        print("in the example but not in your config (defaults apply unless noted):")
        for key in missing:
            print("  +", key)
    if unknown:
        print(
            "in your config but unknown to the example (renamed or removed? the loader rejects these):"
        )
        for key in unknown:
            print("  -", key)
    try:
        load_config(args.config)
    except ConfigError as exc:
        print("CONFIG INVALID:", str(exc).splitlines()[0])
        return 1
    print("config loads OK" + ("" if not (missing or unknown) else " (see the differences above)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
