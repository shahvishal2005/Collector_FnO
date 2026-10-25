# What: decide which underlyings the live capture watches (Tier 1 indices, Tier 2 stocks).
# In: the live config and the Tier 2 ranking file written by scripts/derive_tier2.py.
# Out: a list of Target objects (name, Fyers spot symbol, tier, strikes and expiries to capture).
"""Capture targets."""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

from collector.config.schema import LiveConfig

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Target:
    """One underlying to capture."""

    name: str
    spot_symbol: str
    tier: int
    strikecount: int
    expiry_count: int


def equity_symbol(underlying: str) -> str:
    """Fyers' symbol for a stock's cash market, e.g. RELIANCE -> NSE:RELIANCE-EQ."""
    return f"NSE:{underlying}-EQ"


def load_tier2_names(path: Path, limit: int) -> list[str]:
    """The first `limit` underlyings of the Tier 2 ranking file (column `underlying`)."""
    if limit <= 0:
        return []
    if not path.is_file():
        log.warning("Tier 2 file %s not found; capturing Tier 1 only", path)
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        names = [
            row["underlying"].strip() for row in csv.DictReader(handle) if row.get("underlying")
        ]
    return names[:limit]


def build_targets(live: LiveConfig, tier2_names: list[str]) -> list[Target]:
    """Tier 1 indices first, then Tier 2 stocks, using the capture settings."""
    cap = live.capture
    targets = [
        Target(u.name, u.spot_symbol, 1, cap.tier1_strikecount, cap.tier1_expiry_count)
        for u in live.tier1
    ]
    targets += [
        Target(name, equity_symbol(name), 2, cap.tier2_strikecount, cap.tier2_expiry_count)
        for name in tier2_names
    ]
    return targets
