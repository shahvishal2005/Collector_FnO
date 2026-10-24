# What: a small SQLite log of every raw file we tried to download (the "bronze catalogue").
# In: dataset, trade date, format and the outcome of a download. Out: lookups so runs can resume.
"""Download catalogue. One row per (dataset, trade date, format)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_files (
    dataset     TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    format      TEXT NOT NULL,
    status      TEXT NOT NULL,          -- 'ok' or 'not_found'
    url         TEXT NOT NULL,
    http_status INTEGER NOT NULL,
    fetched_at  TEXT NOT NULL,
    bytes       INTEGER,
    sha256      TEXT,
    path        TEXT,
    PRIMARY KEY (dataset, trade_date, format)
)
"""


@dataclass(frozen=True)
class CatalogueRow:
    """One recorded download outcome."""

    dataset: str
    trade_date: date
    format: str
    status: str
    url: str
    http_status: int
    fetched_at: str
    size: int | None
    sha256: str | None
    path: str | None


class Catalogue:
    """Read and write the catalogue file."""

    def __init__(self, path: Path) -> None:
        """Open (and create if needed) the SQLite file."""
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path)) as conn:
            conn.execute(_SCHEMA)
            conn.commit()

    def get(self, dataset: str, day: date, fmt: str) -> CatalogueRow | None:
        """The recorded outcome for a file, or None if it was never attempted."""
        with closing(sqlite3.connect(self._path)) as conn:
            cur = conn.execute(
                "SELECT dataset, trade_date, format, status, url, http_status, fetched_at, bytes,"
                " sha256, path FROM raw_files WHERE dataset=? AND trade_date=? AND format=?",
                (dataset, day.isoformat(), fmt),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return CatalogueRow(
            row[0], date.fromisoformat(row[1]), row[2], row[3], row[4], row[5], row[6],
            row[7], row[8], row[9],
        )  # fmt: skip

    def record(self, row: CatalogueRow) -> None:
        """Insert or replace the outcome of a download."""
        with closing(sqlite3.connect(self._path)) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO raw_files VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    row.dataset, row.trade_date.isoformat(), row.format, row.status, row.url,
                    row.http_status, row.fetched_at, row.size, row.sha256, row.path,
                ),
            )  # fmt: skip
            conn.commit()

    def rows(self, dataset: str) -> list[CatalogueRow]:
        """Every recorded outcome of a dataset, oldest first."""
        with closing(sqlite3.connect(self._path)) as conn:
            cur = conn.execute(
                "SELECT dataset, trade_date, format, status, url, http_status, fetched_at, bytes,"
                " sha256, path FROM raw_files WHERE dataset=? ORDER BY trade_date, format",
                (dataset,),
            )
            data = cur.fetchall()
        return [
            CatalogueRow(
                r[0], date.fromisoformat(r[1]), r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9]
            )
            for r in data
        ]
