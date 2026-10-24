# What: compare the days we hold with the days the market was open, year by year.
# In: the days with data and the known trading days (from the platform's Nifty candles).
# Out: a per-year coverage table and the lists of missing / extra days.
"""Coverage analysis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


@dataclass(frozen=True)
class Coverage:
    """Result of comparing held days with known trading days."""

    missing: list[date]  # market was open (per candles) but no file
    extra: list[date]  # file exists but candles show no session
    judged_until: date | None  # last day the candles can judge
    table: pd.DataFrame  # per-year counts


def analyse_coverage(
    held: set[date], known_trading: frozenset[date] | None, known_until: date | None, start: date
) -> Coverage:
    """Missing days, extra days and a per-year table (only judged where candle knowledge exists)."""
    if known_trading is None or known_until is None:
        table = _year_table(held, set(), set(), set(held))
        return Coverage([], [], None, table)
    window = {d for d in known_trading if start <= d <= known_until}
    held_window = {d for d in held if start <= d <= known_until}
    missing = sorted(window - held_window)
    extra = sorted(held_window - window)
    table = _year_table(held_window, window, set(missing), set(extra))
    return Coverage(missing, extra, known_until, table)


def _year_table(
    held: set[date], expected: set[date], missing: set[date], extra: set[date]
) -> pd.DataFrame:
    """Counts per calendar year."""
    years = sorted({d.year for d in held | expected})
    rows = [
        {
            "year": year,
            "expected_trading_days": sum(1 for d in expected if d.year == year),
            "days_with_data": sum(1 for d in held if d.year == year),
            "missing_days": sum(1 for d in missing if d.year == year),
            "extra_days": sum(1 for d in extra if d.year == year),
        }
        for year in years
    ]
    return pd.DataFrame(
        rows,
        columns=["year", "expected_trading_days", "days_with_data", "missing_days", "extra_days"],
    )
