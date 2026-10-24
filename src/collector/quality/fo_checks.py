# What: sanity checks on one day of fo_eod data, and a comparison of the old and new formats.
# In: a day's table (and thresholds), or the same day parsed from both formats.
# Out: a list of Issue records; an OverlapResult summarising agreement between formats.
"""Quality checks. They report problems; they never change data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from collector.normalise.fo_eod import FUTURE_TYPES, NATURAL_KEY, OPTION_TYPES

ERROR = "error"
WARN = "warn"
INFO = "info"
PRICE_COLUMNS = ["open", "high", "low", "close", "settle_price"]
# The old file reports turnover in lakh rupees with two decimals, so it is only exact to Rs 1,000.
TURNOVER_TOLERANCE_INR = 1000.0


@dataclass(frozen=True)
class Issue:
    """One finding: which day, which check, how bad, how many rows, and a short explanation."""

    trade_date: date
    check: str
    severity: str
    count: int
    detail: str


def check_day(frame: pd.DataFrame, expected: date, min_underlyings: int) -> list[Issue]:
    """Run every single-day check and return the findings (empty list means clean)."""
    issues: list[Issue] = []

    def add(check: str, severity: str, mask: pd.Series, detail: str) -> None:
        count = int(mask.sum())
        if count:
            issues.append(Issue(expected, check, severity, count, detail))

    if frame.empty:
        return [Issue(expected, "EMPTY_DAY", ERROR, 0, "the file has no rows")]

    dates = set(frame["trade_date"])
    if dates != {expected}:
        issues.append(Issue(expected, "DATE_MISMATCH", ERROR, len(frame), f"dates {sorted(dates)}"))
    add("DUPLICATE_KEY", ERROR, frame.duplicated(NATURAL_KEY, keep=False), "same contract twice")

    for column in ["volume_contracts", "open_interest_qty", "turnover_inr"]:
        add(f"NEGATIVE_{column.upper()}", ERROR, frame[column] < 0, f"{column} below zero")
    for column in PRICE_COLUMNS:
        add(f"NEGATIVE_{column.upper()}", ERROR, frame[column] < 0, f"{column} below zero")

    traded = frame["volume_contracts"].fillna(0) > 0
    add(
        "HIGH_BELOW_LOW",
        ERROR,
        traded & (frame["high"] < frame["low"]),
        "high < low on a traded contract",
    )
    outside = (frame["close"] > frame["high"] + 1e-9) | (frame["close"] < frame["low"] - 1e-9)
    zero_ohlc = (frame["open"] == 0) & (frame["high"] == 0) & (frame["low"] == 0)
    add(
        "ZERO_OHLC_WITH_VOLUME",
        INFO,
        traded & zero_ohlc,
        "traded but open/high/low are 0 (NSE quirk, e.g. spread trades): use close/settle",
    )
    is_settlement = frame["close"] == frame["settle_price"]
    add(
        "SETTLEMENT_CLOSE_OUTSIDE_RANGE",
        INFO,
        traded & outside & ~zero_ohlc & is_settlement,
        "close equals the settlement price and lies outside [low, high] (NSE quirk, thin futures)",
    )
    add(
        "CLOSE_OUTSIDE_RANGE",
        WARN,
        traded & outside & ~zero_ohlc & ~is_settlement,
        "close outside [low, high] on a traded contract",
    )

    is_option = frame["instrument_type"].isin(OPTION_TYPES)
    is_future = frame["instrument_type"].isin(FUTURE_TYPES)
    add(
        "OPTION_WITHOUT_TYPE",
        ERROR,
        is_option & ~frame["option_type"].isin(["CE", "PE"]),
        "option row without CE/PE",
    )
    add(
        "FUTURE_WITH_TYPE",
        ERROR,
        is_future & frame["option_type"].notna(),
        "future row has an option type",
    )
    add(
        "OPTION_BAD_STRIKE",
        ERROR,
        is_option & ~(frame["strike"] > 0),
        "option row without a positive strike",
    )
    add("FUTURE_WITH_STRIKE", ERROR, is_future & frame["strike"].notna(), "future row has a strike")
    add(
        "EXPIRY_BEFORE_TRADE",
        ERROR,
        frame["expiry_date"] < expected,
        "expiry earlier than the trade date",
    )

    underlyings = int(frame["underlying"].nunique())
    if underlyings < min_underlyings:
        issues.append(
            Issue(
                expected,
                "FEW_UNDERLYINGS",
                WARN,
                underlyings,
                f"fewer than {min_underlyings} underlyings",
            )
        )
    return issues


def check_row_count_jumps(
    rows_by_day: dict[date, int], ratio: float, window: int = 20
) -> list[Issue]:
    """Flag days whose row count departs from the previous days' median by more than `ratio`."""
    issues: list[Issue] = []
    days = sorted(rows_by_day)
    for index, day in enumerate(days):
        history = [rows_by_day[d] for d in days[max(0, index - window) : index]]
        if len(history) < 5:
            continue
        median = float(pd.Series(history).median())
        if median > 0 and abs(rows_by_day[day] / median - 1.0) > ratio:
            issues.append(
                Issue(
                    day,
                    "ROW_COUNT_JUMP",
                    WARN,
                    rows_by_day[day],
                    f"median of previous days is {median:.0f}",
                )
            )
    return issues


@dataclass(frozen=True)
class OverlapResult:
    """Agreement between the old and the new format on a day that has both."""

    trade_date: date
    rows_old: int
    rows_new: int
    matched_rows: int
    only_old: int
    only_new: int
    mismatches: dict[str, int]

    @property
    def identical(self) -> bool:
        """True when every contract is in both files and no compared field differs."""
        return self.only_old == 0 and self.only_new == 0 and not any(self.mismatches.values())


def compare_formats(old: pd.DataFrame, new: pd.DataFrame, day: date) -> OverlapResult:
    """Join the two formats on the contract key and count differing fields."""
    key = [c for c in NATURAL_KEY if c != "trade_date"]
    merged = old.merge(new, on=key, how="outer", suffixes=("_old", "_new"), indicator=True)
    both = merged[merged["_merge"] == "both"]
    mismatches: dict[str, int] = {}
    for column in PRICE_COLUMNS:
        diff = (both[f"{column}_old"] - both[f"{column}_new"]).abs()
        mismatches[column] = int((diff > 1e-6).sum())
    for column in ["volume_contracts", "open_interest_qty", "chg_in_oi_qty"]:
        left = both[f"{column}_old"].astype("float64")
        right = both[f"{column}_new"].astype("float64")
        mismatches[column] = int((left != right).sum())
    turnover = (both["turnover_inr_old"] - both["turnover_inr_new"]).abs()
    mismatches["turnover_inr"] = int((turnover > TURNOVER_TOLERANCE_INR).sum())
    return OverlapResult(
        day,
        len(old),
        len(new),
        len(both),
        int((merged["_merge"] == "left_only").sum()),
        int((merged["_merge"] == "right_only").sum()),
        mismatches,
    )
