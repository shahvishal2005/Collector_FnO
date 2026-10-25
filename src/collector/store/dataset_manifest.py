# What: per-day fingerprints for any daily dataset, and a check that the files still match them.
# In: the layout and a dataset name. Out: a manifest CSV; a list of differences.
"""Generic manifest (rows, a checksum of all numeric values, and the file's SHA-256 per day)."""

from __future__ import annotations

from datetime import date

import pandas as pd

from collector.common.hashing import sha256_file
from collector.store.layout import Layout
from collector.store.parquet import read_table

MANIFEST_COLUMNS = ["trade_date", "rows", "numeric_checksum", "file_sha256"]


def dataset_days(layout: Layout, name: str) -> list[date]:
    """Trade dates that have a silver partition for the dataset, ascending."""
    days = []
    for folder in layout.dataset_silver_root(name).glob("trade_date=*"):
        if (folder / "part-0.parquet").is_file():
            days.append(date.fromisoformat(folder.name.split("=", 1)[1]))
    return sorted(days)


def numeric_checksum(frame: pd.DataFrame) -> float:
    """Sum of every numeric value in the table (a cheap fingerprint of the content)."""
    numbers = frame.select_dtypes(include="number").drop(
        columns=["schema_version"], errors="ignore"
    )
    return round(float(numbers.fillna(0).astype("float64").to_numpy().sum()), 4)


def build_dataset_manifest(layout: Layout, name: str) -> pd.DataFrame:
    """Recompute the manifest from every silver file and write it."""
    rows = []
    for day in dataset_days(layout, name):
        path = layout.dataset_silver_file(name, day)
        frame = read_table(path)
        rows.append(
            {
                "trade_date": day.isoformat(),
                "rows": len(frame),
                "numeric_checksum": numeric_checksum(frame),
                "file_sha256": sha256_file(path),
            }
        )
    manifest = pd.DataFrame(rows, columns=MANIFEST_COLUMNS)
    layout.manifests_root.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(layout.dataset_manifest_path(name), index=False)
    return manifest


def check_dataset_manifest(layout: Layout, name: str) -> list[str]:
    """Compare the manifest with the silver files; return problems (empty = OK)."""
    path = layout.dataset_manifest_path(name)
    if not path.is_file():
        return [f"manifest not found: {path}"]
    stored = pd.read_csv(path, dtype={"file_sha256": str})
    stored_days = {date.fromisoformat(d) for d in stored["trade_date"]}
    actual_days = set(dataset_days(layout, name))
    problems = [
        f"{d}: in manifest but silver file missing" for d in sorted(stored_days - actual_days)
    ]
    problems += [
        f"{d}: silver file present but not in manifest" for d in sorted(actual_days - stored_days)
    ]
    for record in stored.to_dict("records"):
        day = date.fromisoformat(str(record["trade_date"]))
        if (
            day in actual_days
            and sha256_file(layout.dataset_silver_file(name, day)) != record["file_sha256"]
        ):
            problems.append(f"{day}: file checksum differs from the manifest")
    return problems
