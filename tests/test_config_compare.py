# What: tests for the config drift check used when updating the VPS.
# In: small YAML files. Out: pass/fail.
"""Config comparison."""

from __future__ import annotations

from pathlib import Path

from collector.config.compare import compare_config, flatten_keys

EXAMPLE = Path(__file__).parents[1] / "config" / "config.example.yaml"


def test_flatten_keys_treats_lists_as_values() -> None:
    data = {"a": {"b": 1, "c": {"d": 2}}, "e": [1, 2], "f": {}}
    assert flatten_keys(data) == {"a.b", "a.c.d", "e", "f"}


def test_missing_and_unknown_keys(tmp_path: Path) -> None:
    example = tmp_path / "example.yaml"
    example.write_text(
        "live:\n  capture:\n    market_check_slots: 10\n    save_raw: true\nnse:\n  x: 1\n",
        encoding="utf-8",
    )
    mine = tmp_path / "mine.yaml"
    mine.write_text(
        "live:\n  capture:\n    stale_after_seconds: 900\n    save_raw: true\nnse:\n  x: 5\n",
        encoding="utf-8",
    )
    missing, unknown = compare_config(example, mine)
    assert missing == ["live.capture.market_check_slots"]
    assert unknown == [
        "live.capture.stale_after_seconds"
    ]  # a renamed setting shows up on both sides


def test_the_example_matches_itself() -> None:
    assert compare_config(EXAMPLE, EXAMPLE) == ([], [])
