# What: per-day fingerprints of the fo_eod data, and a check that the files still match them.
# In: the silver folder (and the manifest CSV). Out: a manifest CSV; a list of differences.
"""Manifest of the fo_eod table (the same idea as the research platform's data manifest)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from collector.common.hashing import sha256_file
from collector.store.layout import Layout
from collector.store.parquet import read_table

MANIFEST_COLUMNS = [
    "trade_date", "rows", "underlyings", "future_rows", "option_rows",
    "sum_open_interest", "sum_turnover_inr", "sum_close", "source_format", "file_sha256",
]  # fmt: skip


def fingerprint_day(frame: pd.DataFrame, file_sha: str) -> dict[str, object]:
    """Summary numbers of one day's table, used to detect any later change."""
    is_option = frame["instrument_type"].isin(["OPTIDX", "OPTSTK"])
    return {
        "trade_date": frame["trade_date"].iloc[0].isoformat(),
        "rows": len(frame),
        "underlyings": int(frame["underlying"].nunique()),
        "future_rows": int((~is_option).sum()),
        "option_rows": int(is_option.sum()),
        "sum_open_interest": int(frame["open_interest_qty"].fillna(0).sum()),
        "sum_turnover_inr": round(float(frame["turnover_inr"].fillna(0).sum()), 2),
        "sum_close": round(float(frame["close"].fillna(0).sum()), 4),
        "source_format": str(frame["source_format"].iloc[0]),
        "file_sha256": file_sha,
    }


def silver_days(layout: Layout) -> list[date]:
    """All trade dates that have a silver partition, ascending."""
    days: list[date] = []
    for folder in layout.fo_silver_root.glob("trade_date=*"):
        if (folder / "part-0.parquet").is_file():
            days.append(date.fromisoformat(folder.name.split("=", 1)[1]))
    return sorted(days)


def build_manifest(layout: Layout) -> pd.DataFrame:
    """Recompute the manifest from every silver file and write it to the manifest path."""
    rows = []
    for day in silver_days(layout):
        path = layout.fo_silver_file(day)
        rows.append(fingerprint_day(read_table(path), sha256_file(path)))
    manifest = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
    layout.manifests_root.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(layout.fo_manifest_path, index=False)
    return manifest


def check_manifest(layout: Layout) -> list[str]:
    """Compare the manifest file with the silver files; return a list of problems (empty = OK)."""
    if not layout.fo_manifest_path.is_file():
        return [f"manifest not found: {layout.fo_manifest_path}"]
    stored = pd.read_csv(layout.fo_manifest_path, dtype={"file_sha256": str})
    problems: list[str] = []
    stored_days = {date.fromisoformat(d) for d in stored["trade_date"]}
    actual_days = set(silver_days(layout))
    for day in sorted(stored_days - actual_days):
        problems.append(f"{day}: in manifest but silver file missing")
    for day in sorted(actual_days - stored_days):
        problems.append(f"{day}: silver file present but not in manifest")
    for record in stored.to_dict("records"):
        day = date.fromisoformat(str(record["trade_date"]))
        if day not in actual_days:
            continue
        path = layout.fo_silver_file(day)
        if sha256_file(path) != record["file_sha256"]:
            problems.append(f"{day}: file checksum differs from the manifest")
    return problems
