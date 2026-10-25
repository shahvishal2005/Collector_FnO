# What: read NSE's participant-wise F&O files (open interest and trading volume) into one tidy table.
# In: the CSV bytes, the date it was requested for, its source name. Out: a DataFrame in PARTICIPANT_SCHEMA.
"""Participant-wise open interest / volume (FII, DII, Pro, Client).

File layout (identical across 2017-2026): a title line carrying the date, a header line, then one
row per participant type (Client, DII, FII, Pro) and a TOTAL row. Each row has long and short
contracts for index futures, stock futures, index calls/puts and stock calls/puts, plus totals.
The table is made 'tidy': one row per (client type, category).

Some days (seen on 2017-11-24 and 2017-12-06) carry FRACTIONAL contract counts such as 787007.6667
(thirds). They are in the source, so they are stored exactly (float64) and never rounded.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime

import pandas as pd
import pyarrow as pa

from collector.normalise.fo_eod import ParseError

SCHEMA_VERSION = 1
CLIENT_TYPES = {"Client", "DII", "FII", "Pro", "TOTAL"}
# (category, long column, short column) as they are named in the file
CATEGORIES = [
    ("FUTIDX", "Future Index Long", "Future Index Short"),
    ("FUTSTK", "Future Stock Long", "Future Stock Short"),
    ("OPTIDX_CE", "Option Index Call Long", "Option Index Call Short"),
    ("OPTIDX_PE", "Option Index Put Long", "Option Index Put Short"),
    ("OPTSTK_CE", "Option Stock Call Long", "Option Stock Call Short"),
    ("OPTSTK_PE", "Option Stock Put Long", "Option Stock Put Short"),
    ("TOTAL", "Total Long Contracts", "Total Short Contracts"),
]
PARTICIPANT_SCHEMA = pa.schema(
    [
        ("trade_date", pa.date32()),
        ("client_type", pa.string()),
        ("category", pa.string()),
        ("long_contracts", pa.float64()),
        ("short_contracts", pa.float64()),
        ("source_file", pa.string()),
        ("ingested_at", pa.timestamp("us", tz="Asia/Kolkata")),
        ("schema_version", pa.int32()),
    ]
)
PARTICIPANT_COLUMNS = [f.name for f in PARTICIPANT_SCHEMA]
_MONTHS = {
    m: i + 1
    for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])
}  # fmt: skip
_TITLE_DATE = re.compile(
    r"as on\s+([A-Za-z]{3})[a-z]*\s+(\d{1,2})\s*,?\s*\W*(\d{4})", re.IGNORECASE
)


def _title_date(line: str) -> date:
    """The date written in the title line, e.g. 'as on Oct 24, 2017'."""
    match = _TITLE_DATE.search(line)
    if not match or match[1].upper() not in _MONTHS:
        raise ParseError(f"no date found in the title line: {line[:80]!r}")
    return date(int(match[3]), _MONTHS[match[1].upper()], int(match[2]))


def _count(text: str) -> float:
    """A contract count (usually whole, sometimes fractional) with optional thousands separators."""
    try:
        return float(text.replace(",", "").strip())
    except ValueError:
        raise ParseError(f"not a number: {text!r}") from None


def parse_participant(
    content: bytes, expected: date, source_file: str, ingested_at: datetime
) -> pd.DataFrame:
    """Tidy table from one participant file; ParseError if the file is not what we expect."""
    text = content.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 3:
        raise ParseError("participant file has fewer than 3 lines")
    found = _title_date(text.splitlines()[0])  # plain text: the title line has odd quote marks
    if found != expected:
        raise ParseError(f"file is dated {found}, expected {expected}")
    header_index = next(
        (i for i, r in enumerate(rows) if r and r[0].strip() == "Client Type"), None
    )
    if header_index is None:
        raise ParseError("no 'Client Type' header line found")
    header = [c.strip() for c in rows[header_index]]
    needed = {name for _, a, b in CATEGORIES for name in (a, b)}
    missing = sorted(needed - set(header))
    if missing:
        raise ParseError(f"missing columns {missing}")
    position = {name: header.index(name) for name in needed}
    records = []
    seen: set[str] = set()
    for row in rows[header_index + 1 :]:
        if not row or not row[0].strip():
            continue
        client = row[0].strip()
        if client not in CLIENT_TYPES:
            raise ParseError(f"unknown client type {client!r}")
        seen.add(client)
        for category, long_name, short_name in CATEGORIES:
            records.append(
                {
                    "trade_date": expected,
                    "client_type": client,
                    "category": category,
                    "long_contracts": _count(row[position[long_name]]),
                    "short_contracts": _count(row[position[short_name]]),
                }
            )
    if seen != CLIENT_TYPES:
        raise ParseError(f"expected client types {sorted(CLIENT_TYPES)}, found {sorted(seen)}")
    frame = pd.DataFrame.from_records(records)
    frame["source_file"] = source_file
    frame["ingested_at"] = pd.Timestamp(ingested_at)
    frame["schema_version"] = SCHEMA_VERSION
    return frame[PARTICIPANT_COLUMNS]
