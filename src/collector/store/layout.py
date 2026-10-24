# What: the folder layout under data_root, in one place so no other module builds paths by hand.
# In: the data root and a dataset/date. Out: file and folder paths.
"""Storage layout.

data/
  bronze/nse_fo/<YYYY>/<original file name>      raw downloads, never modified
  bronze/catalogue.sqlite                         what was fetched, when, checksum, status
  silver/fo_eod/trade_date=YYYY-MM-DD/part-0.parquet   normalised daily tables
  manifests/fo_eod_manifest.csv                   per-day fingerprints
  reports/                                        coverage and quality reports
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

FO_DATASET = "nse_fo"
FO_EOD_TABLE = "fo_eod"


@dataclass(frozen=True)
class Layout:
    """Resolved paths for one data root."""

    root: Path

    @property
    def catalogue_path(self) -> Path:
        """SQLite file listing every raw download."""
        return self.root / "bronze" / "catalogue.sqlite"

    def bronze_file(self, dataset: str, day: date, file_name: str) -> Path:
        """Where the raw file for a dataset, day and file name is stored."""
        return self.root / "bronze" / dataset / f"{day.year}" / file_name

    @property
    def fo_silver_root(self) -> Path:
        """Folder holding the daily fo_eod partitions."""
        return self.root / "silver" / FO_EOD_TABLE

    def fo_silver_file(self, day: date) -> Path:
        """The parquet file of one trade day."""
        return self.fo_silver_root / f"trade_date={day.isoformat()}" / "part-0.parquet"

    @property
    def manifests_root(self) -> Path:
        """Folder with manifest CSV files."""
        return self.root / "manifests"

    @property
    def fo_manifest_path(self) -> Path:
        """The fo_eod manifest."""
        return self.manifests_root / "fo_eod_manifest.csv"

    @property
    def reports_root(self) -> Path:
        """Folder with generated reports."""
        return self.root / "reports"
