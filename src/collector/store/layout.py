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

    # ---- live capture (Fyers) ----
    def chain_raw_file(self, day: date, cycle_label: str) -> Path:
        """Raw option-chain answers of one cycle (compressed JSON lines)."""
        return (
            self.root / "bronze" / "fyers_chain" / f"trade_date={day.isoformat()}"
            / f"cycle_{cycle_label}.jsonl.gz"
        )  # fmt: skip

    def chain_silver_file(self, day: date, cycle_label: str) -> Path:
        """Normalised option-chain rows of one cycle."""
        return (
            self.root / "silver" / "option_chain" / f"trade_date={day.isoformat()}"
            / f"cycle_{cycle_label}.parquet"
        )  # fmt: skip

    def chain_silver_dir(self, day: date) -> Path:
        """Folder with all cycles of one day."""
        return self.root / "silver" / "option_chain" / f"trade_date={day.isoformat()}"

    def live_health_dir(self, day: date) -> Path:
        """Folder with the cycle and call health logs of one day."""
        return self.root / "silver" / "live_health" / f"trade_date={day.isoformat()}"

    def contract_master_file(self, day: date) -> Path:
        """The day's contract list (symbols, lot sizes, expiries) as Parquet."""
        return (
            self.root / "silver" / "contract_master" / f"trade_date={day.isoformat()}"
            / "contracts.parquet"
        )  # fmt: skip

    def contract_master_raw(self, day: date, label: str) -> Path:
        """The raw symbol-master file as downloaded (compressed)."""
        return (
            self.root / "bronze" / "fyers_symbol_master" / f"trade_date={day.isoformat()}"
            / f"{label}.csv.gz"
        )  # fmt: skip
