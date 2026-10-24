# What: write and read the daily Parquet tables safely.
# In: a DataFrame, a schema and a path. Out: a file written atomically (temp file, then rename).
"""Parquet storage with atomic writes."""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


def write_atomic_bytes(path: Path, data: bytes) -> None:
    """Write bytes to path via a temp file in the same folder, then rename over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def write_table(frame: pd.DataFrame, schema: pa.Schema, path: Path) -> None:
    """Write the frame as zstd Parquet with the given schema; replaces any old file atomically."""
    table = pa.Table.from_pandas(frame, schema=schema, preserve_index=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    pq.write_table(table, temp, compression="zstd")
    os.replace(temp, path)


def read_table(path: Path) -> pd.DataFrame:
    """Read one Parquet file back into a DataFrame.

    ParquetFile is used on purpose: read_table() would treat the `trade_date=...` folder name as a
    partition column and clash with the real column of the same name.
    """
    frame: pd.DataFrame = pq.ParquetFile(path).read().to_pandas()
    return frame
