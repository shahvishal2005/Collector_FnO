# What: tests for the Tier 2 stock ranking.
# In: small synthetic daily tables. Out: pass/fail.
"""Tier 2 selection."""

from __future__ import annotations

from datetime import date

import pandas as pd

from collector.universe.tier2 import COLUMNS, rank_option_activity


def _day(day: date, rows: list[tuple[str, int, float, int | None, int]]) -> pd.DataFrame:
    """rows: (underlying, contracts, close, lot_size, open_interest)."""
    return pd.DataFrame(
        {
            "trade_date": day,
            "instrument_type": "OPTSTK",
            "underlying": [r[0] for r in rows],
            "volume_contracts": [r[1] for r in rows],
            "close": [r[2] for r in rows],
            "lot_size": pd.array([r[3] for r in rows], dtype="Int64"),
            "turnover_inr": [r[1] * 1000.0 for r in rows],
            "open_interest_qty": [r[4] for r in rows],
        }
    )


def test_ranks_by_premium_turnover() -> None:
    days = [date(2026, 10, d) for d in (19, 20, 21)]
    rows = [("AAA", 100, 10.0, 500, 1000), ("BBB", 10, 100.0, 600, 5000), ("ZERO", 0, 0.0, 500, 0)]
    ranked = rank_option_activity([_day(d, rows) for d in days], top_n=5, min_day_share=0.8)
    assert list(ranked.columns) == COLUMNS
    # AAA: 100 * 500 * 10 = 500,000; BBB: 10 * 600 * 100 = 600,000; ZERO traded nothing
    assert list(ranked["underlying"]) == ["BBB", "AAA", "ZERO"]
    assert ranked["basis"].iloc[0] == "premium"
    assert ranked["rank"].tolist() == [1, 2, 3]
    assert ranked.loc[0, "median_premium_turnover_inr"] == 600_000


def test_top_n_and_presence_filter() -> None:
    days = [date(2026, 10, d) for d in range(19, 29)]
    frames = [_day(d, [("OLD", 50, 5.0, 100, 10)]) for d in days]
    frames[0] = pd.concat([frames[0], _day(days[0], [("NEWLIST", 999, 99.0, 100, 10)])])
    ranked = rank_option_activity(frames, top_n=1, min_day_share=0.8)
    assert list(ranked["underlying"]) == ["OLD"]  # NEWLIST appears on only 1 of 10 days


def test_falls_back_to_notional_without_lot_sizes() -> None:
    frame = _day(date(2026, 10, 19), [("AAA", 10, 5.0, None, 1)])
    ranked = rank_option_activity([frame], top_n=3, min_day_share=0.5)
    assert ranked["basis"].iloc[0] == "notional"


def test_mixed_old_and_new_days_use_only_days_with_lot_sizes() -> None:
    old_day = _day(date(2018, 1, 8), [("AAA", 100, 10.0, None, 1000)])
    new_days = [_day(date(2026, 10, d), [("AAA", 10, 10.0, 100, 1000)]) for d in (19, 20)]
    ranked = rank_option_activity([old_day, *new_days], top_n=3, min_day_share=0.8)
    assert ranked["basis"].iloc[0] == "premium"
    assert ranked.loc[0, "days_present"] == 2
    assert ranked.loc[0, "median_premium_turnover_inr"] == 10_000  # 10 * 100 * 10


def test_empty_input() -> None:
    assert rank_option_activity([], 5, 0.8).empty
    futures_only = _day(date(2026, 10, 19), [("AAA", 1, 1.0, 1, 1)])
    futures_only["instrument_type"] = "FUTSTK"
    assert rank_option_activity([futures_only], 5, 0.8).empty
