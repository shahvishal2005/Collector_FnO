# What: compare a local config.yaml with config.example.yaml to spot drift after an update.
# In: the two YAML files. Out: keys the example has that yours lacks, and keys yours has that are unknown.
"""Config drift check.

config.yaml is local (git-ignored) and the schema rejects unknown keys, so a setting that was
renamed or removed in an update makes the old config invalid. This lists the differences so they
can be fixed by hand without overwriting the local values (host name, paths, holidays).
Lists (for example the Tier 1 indices) are treated as single values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def flatten_keys(data: Any, prefix: str = "") -> set[str]:
    """Dotted names of every setting in a nested mapping (a list counts as one setting)."""
    keys: set[str] = set()
    if isinstance(data, dict):
        for name, value in data.items():
            path = f"{prefix}.{name}" if prefix else str(name)
            if isinstance(value, dict) and value:
                keys |= flatten_keys(value, path)
            else:
                keys.add(path)
    return keys


def compare_config(example_path: Path, actual_path: Path) -> tuple[list[str], list[str]]:
    """Return (settings missing from yours, settings in yours that the example does not know)."""
    example = yaml.safe_load(example_path.read_text(encoding="utf-8")) or {}
    actual = yaml.safe_load(actual_path.read_text(encoding="utf-8")) or {}
    example_keys, actual_keys = flatten_keys(example), flatten_keys(actual)
    return sorted(example_keys - actual_keys), sorted(actual_keys - example_keys)
