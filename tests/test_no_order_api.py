# What: guard test: the collector must never contain broker order-placing code.
# In: the source files. Out: pass/fail.
"""The collector reads data only. This test fails if order-related calls ever appear."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
FORBIDDEN = re.compile(
    r"place_order|modify_order|cancel_order|exit_positions|convert_position|"
    r"place_basket|place_multileg|\.orders\(|/orders\b",
    re.IGNORECASE,
)


def test_no_order_functions_in_source() -> None:
    offenders = []
    for folder in ("src", "scripts"):
        for path in (ROOT / folder).rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if FORBIDDEN.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offenders, "order-related code found:\n" + "\n".join(offenders)
