# What: sanity checks for the participant, ban-list and index-close tables (one day at a time).
# In: a day's table and its date. Out: a list of Issue records (empty means clean).
"""Quality checks for the M3 datasets. They report; they never change data."""

from __future__ import annotations

from datetime import date

import pandas as pd

from collector.quality.fo_checks import ERROR, INFO, WARN, Issue

_PARTICIPANTS = ["Client", "DII", "FII", "Pro"]
_RANGE_TOLERANCE = 1e-9
# NSE rounds each participant row separately: on 2026-10-23 the four rows add up to the TOTAL row
# within one contract. Anything larger is a real inconsistency.
_SUM_TOLERANCE = 2


def check_participant(frame: pd.DataFrame, day: date) -> list[Issue]:
    """Five client types x seven categories; participants must add up to TOTAL; TOTAL long = short."""
    issues: list[Issue] = []
    if frame.empty:
        return [Issue(day, "EMPTY_DAY", ERROR, 0, "the file has no rows")]
    if set(frame["trade_date"]) != {day}:
        issues.append(Issue(day, "DATE_MISMATCH", ERROR, len(frame), "wrong trade date"))
    if len(frame) != 35:
        issues.append(Issue(day, "UNEXPECTED_ROW_COUNT", ERROR, len(frame), "expected 35 rows"))
    for column in ("long_contracts", "short_contracts"):
        negative = int((frame[column] < 0).sum())
        if negative:
            issues.append(Issue(day, f"NEGATIVE_{column.upper()}", ERROR, negative, "below zero"))
    fractional = int(
        sum(((frame[c] % 1) != 0).sum() for c in ("long_contracts", "short_contracts"))
    )
    if fractional:
        issues.append(
            Issue(
                day,
                "FRACTIONAL_CONTRACTS",
                INFO,
                fractional,
                "non-whole counts in the source (kept exactly)",
            )
        )
    total = frame[frame["client_type"] == "TOTAL"].set_index("category")
    parts = (
        frame[frame["client_type"].isin(_PARTICIPANTS)]
        .groupby("category")[["long_contracts", "short_contracts"]]
        .sum()
    )
    for side in ("long_contracts", "short_contracts"):
        joined = parts[side].to_frame("parts").join(total[side].rename("total"), how="outer")
        bad = joined[(joined["parts"] - joined["total"]).abs() > _SUM_TOLERANCE]
        if len(bad):
            issues.append(
                Issue(
                    day, "PARTICIPANTS_DO_NOT_ADD_UP", ERROR, len(bad), f"{side}: {list(bad.index)}"
                )
            )
    unbalanced = total[(total["long_contracts"] - total["short_contracts"]).abs() > _SUM_TOLERANCE]
    if len(unbalanced):
        issues.append(
            Issue(
                day,
                "TOTAL_LONG_NOT_EQUAL_SHORT",
                WARN,
                len(unbalanced),
                str(list(unbalanced.index)),
            )
        )
    return issues


def check_ban(frame: pd.DataFrame, day: date) -> list[Issue]:
    """A ban list may be empty; symbols must be unique and numbered 1..n."""
    issues: list[Issue] = []
    if frame.empty:
        return issues
    if frame["symbol"].duplicated().any():
        issues.append(
            Issue(day, "DUPLICATE_SYMBOL", ERROR, int(frame["symbol"].duplicated().sum()), "")
        )
    if sorted(frame["position"]) != list(range(1, len(frame) + 1)):
        issues.append(
            Issue(day, "POSITIONS_NOT_SEQUENTIAL", WARN, len(frame), "numbering is not 1..n")
        )
    return issues


def check_index_close(frame: pd.DataFrame, day: date) -> list[Issue]:
    """Unique index names; high not below low; close inside the range; no negative volume."""
    issues: list[Issue] = []
    if frame.empty:
        return [Issue(day, "EMPTY_DAY", ERROR, 0, "the file has no rows")]
    duplicated = int(frame["index_name"].duplicated().sum())
    if duplicated:
        issues.append(Issue(day, "DUPLICATE_INDEX", ERROR, duplicated, "same index twice"))
    both = frame["high"].notna() & frame["low"].notna()
    bad_range = int((both & (frame["high"] < frame["low"])).sum())
    if bad_range:
        issues.append(Issue(day, "HIGH_BELOW_LOW", ERROR, bad_range, "high < low"))
    missing_close = int(frame["close"].isna().sum())
    if missing_close:
        issues.append(Issue(day, "MISSING_CLOSE", ERROR, missing_close, "no closing value"))
    outside = (
        both
        & frame["close"].notna()
        & (
            (frame["close"] > frame["high"] + _RANGE_TOLERANCE)
            | (frame["close"] < frame["low"] - _RANGE_TOLERANCE)
        )
    )
    if int(outside.sum()):
        issues.append(
            Issue(day, "CLOSE_OUTSIDE_RANGE", WARN, int(outside.sum()), "close outside [low, high]")
        )
    negative = int((frame["volume"].fillna(0) < 0).sum())
    if negative:
        issues.append(Issue(day, "NEGATIVE_VOLUME", ERROR, negative, "below zero"))
    return issues
