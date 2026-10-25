# What: read NSE's daily "all indices close" file (open/high/low/close, volume, P/E, P/B, yield).
# In: the CSV bytes, the date it was requested for, its source name. Out: a DataFrame in INDEX_CLOSE_SCHEMA.
"""Index end-of-day table (about 75 indices in 2017, 168 in 2026).

Blank or '-' values become nulls. Index volume is empty for many indices and early years.
"""

from __future__ import annotations

import io
from datetime import date, datetime

import pandas as pd
import pyarrow as pa

from collector.normalise.fo_eod import ParseError

SCHEMA_VERSION = 1
INDEX_CLOSE_SCHEMA = pa.schema(
    [
        ("trade_date", pa.date32()),
        ("index_name", pa.string()),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("points_change", pa.float64()),
        ("change_pct", pa.float64()),
        ("volume", pa.int64()),
        ("turnover_cr", pa.float64()),
        ("pe", pa.float64()),
        ("pb", pa.float64()),
        ("div_yield", pa.float64()),
        ("source_file", pa.string()),
        ("ingested_at", pa.timestamp("us", tz="Asia/Kolkata")),
        ("schema_version", pa.int32()),
    ]
)
INDEX_CLOSE_COLUMNS = [f.name for f in INDEX_CLOSE_SCHEMA]
_FILE_COLUMNS = {
    "Index Name": "index_name",
    "Open Index Value": "open",
    "High Index Value": "high",
    "Low Index Value": "low",
    "Closing Index Value": "close",
    "Points Change": "points_change",
    "Change(%)": "change_pct",
    "Volume": "volume",
    "Turnover (Rs. Cr.)": "turnover_cr",
    "P/E": "pe",
    "P/B": "pb",
    "Div Yield": "div_yield",
}


def _number(series: pd.Series) -> pd.Series:
    """Text to float; blank and '-' become NaN; other text raises."""
    cleaned = series.astype(str).str.strip().replace({"": float("nan"), "-": float("nan")})
    try:
        return pd.to_numeric(cleaned, errors="raise").astype("float64")
    except (ValueError, TypeError):
        raise ParseError(f"non-numeric value in column {series.name!r}") from None


def parse_index_close(
    content: bytes, expected: date, source_file: str, ingested_at: datetime
) -> pd.DataFrame:
    """One day's index table; ParseError if columns are missing or the date differs."""
    text = content.decode("utf-8-sig", errors="replace")
    raw = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False)
    raw.columns = [str(c).strip() for c in raw.columns]
    missing = sorted((set(_FILE_COLUMNS) | {"Index Date"}) - set(raw.columns))
    if missing:
        raise ParseError(f"missing columns {missing}")
    if raw.empty:
        raise ParseError("index file has no rows")
    dates = set(pd.to_datetime(raw["Index Date"].str.strip(), format="%d-%m-%Y").dt.date)
    if dates != {expected}:
        raise ParseError(f"file dates {sorted(dates)}, expected {expected}")
    frame = pd.DataFrame({"trade_date": [expected] * len(raw)})
    frame["index_name"] = raw["Index Name"].str.strip()
    for file_name, column in _FILE_COLUMNS.items():
        if column == "index_name":
            continue
        frame[column] = _number(raw[file_name])
    frame["volume"] = frame["volume"].round().astype("Int64")
    frame["source_file"] = source_file
    frame["ingested_at"] = pd.Timestamp(ingested_at)
    frame["schema_version"] = SCHEMA_VERSION
    return frame[INDEX_CLOSE_COLUMNS]
