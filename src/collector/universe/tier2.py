# What: rank stocks by how actively their options trade, to propose the Tier 2 live-capture list.
# In: a list of daily fo_eod tables (the most recent trading days) and the selection settings.
# Out: a ranked table with liquidity measures per stock; the top rows are the proposal.
"""Tier 2 stock selection from stored end-of-day option data.

Liquidity is measured by premium turnover (contracts x lot size x close), which reflects money
actually paid for options, unlike NSE's notional turnover that grows with the strike price.
Lot sizes exist only in the new file format, so this is meant for recent days; if no lot size is
available the ranking falls back to notional turnover and says so in the `basis` column.
"""

from __future__ import annotations

import pandas as pd

COLUMNS = [
    "rank", "underlying", "days_present", "median_premium_turnover_inr",
    "median_contracts", "median_active_contracts", "median_open_interest_qty", "basis",
]  # fmt: skip


def rank_option_activity(
    frames: list[pd.DataFrame], top_n: int, min_day_share: float
) -> pd.DataFrame:
    """Rank stock-option underlyings by median daily premium turnover over the given days."""
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    with_lot = [f for f in frames if f["lot_size"].notna().any()]
    if with_lot:  # rank only on days that carry lot sizes (new format) so old days cannot add zeros
        frames = with_lot
    options = pd.concat(frames, ignore_index=True)
    options = options[options["instrument_type"] == "OPTSTK"].copy()
    n_days = len(frames)
    if options.empty:
        return pd.DataFrame(columns=COLUMNS)
    traded = options["volume_contracts"].fillna(0) > 0
    have_lot = bool(with_lot)
    if have_lot:
        value = options["volume_contracts"] * options["lot_size"] * options["close"]
        basis = "premium"
    else:
        value = options["turnover_inr"]
        basis = "notional"
    options["value"] = value.astype("float64").where(traded, 0.0).fillna(0.0)
    options["contracts"] = options["volume_contracts"].fillna(0)
    options["active"] = traded.astype(int)
    options["oi"] = options["open_interest_qty"].fillna(0)
    daily = (
        options.groupby(["trade_date", "underlying"])
        .agg(value=("value", "sum"), contracts=("contracts", "sum"),
             active=("active", "sum"), oi=("oi", "sum"))
        .reset_index()
    )  # fmt: skip
    summary = (
        daily.groupby("underlying")
        .agg(
            days_present=("trade_date", "nunique"),
            median_premium_turnover_inr=("value", "median"),
            median_contracts=("contracts", "median"),
            median_active_contracts=("active", "median"),
            median_open_interest_qty=("oi", "median"),
        )
        .reset_index()
    )
    summary = summary[summary["days_present"] >= min_day_share * n_days]
    summary = summary.sort_values("median_premium_turnover_inr", ascending=False)
    summary = summary.head(top_n).reset_index(drop=True)
    summary.insert(0, "rank", range(1, len(summary) + 1))
    summary["basis"] = basis
    return summary[COLUMNS]
