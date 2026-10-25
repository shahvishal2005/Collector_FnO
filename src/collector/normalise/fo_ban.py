# What: read NSE's daily F&O ban list ("securities in ban period") into a table.
# In: the file bytes, the date it was requested for, its source name. Out: a DataFrame in BAN_SCHEMA.
"""F&O ban list.

The file's first line says 'Securities in Ban For Trade Date DD-MON-YYYY:' followed by either
'NIL' (nobody banned) or numbered lines 'n,SYMBOL'. A day with nobody banned is a real result,
so it is stored as an EMPTY table for that day: that way 'no ban' is different from 'no file'.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd
import pyarrow as pa

from collector.normalise.fo_eod import ParseError

SCHEMA_VERSION = 1
BAN_SCHEMA = pa.schema(
    [
        ("trade_date", pa.date32()),
        ("position", pa.int32()),
        ("symbol", pa.string()),
        ("source_file", pa.string()),
        ("ingested_at", pa.timestamp("us", tz="Asia/Kolkata")),
        ("schema_version", pa.int32()),
    ]
)
BAN_COLUMNS = [f.name for f in BAN_SCHEMA]
_MONTHS = {
    m: i + 1
    for i, m in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])
}  # fmt: skip
_FIRST_LINE = re.compile(
    r"Trade Date\s+(\d{1,2})-([A-Za-z]{3})-(\d{4})\s*:\s*(NIL)?", re.IGNORECASE
)


def parse_ban_list(
    content: bytes, expected: date, source_file: str, ingested_at: datetime
) -> pd.DataFrame:
    """One day's ban list; ParseError if the first line does not carry the expected date."""
    lines = [ln.strip() for ln in content.decode("utf-8-sig", errors="replace").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        raise ParseError("ban file is empty")
    match = _FIRST_LINE.search(lines[0])
    if not match or match[2].upper() not in _MONTHS:
        raise ParseError(f"unrecognised first line: {lines[0][:80]!r}")
    found = date(int(match[3]), _MONTHS[match[2].upper()], int(match[1]))
    if found != expected:
        raise ParseError(f"file is dated {found}, expected {expected}")
    records = []
    if not match[4]:  # not 'NIL'
        for line in lines[1:]:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2 or not parts[0].isdigit() or not parts[1]:
                raise ParseError(f"unrecognised ban line: {line[:60]!r}")
            records.append({"trade_date": expected, "position": int(parts[0]), "symbol": parts[1]})
    frame = pd.DataFrame.from_records(records, columns=["trade_date", "position", "symbol"])
    frame["source_file"] = source_file
    frame["ingested_at"] = pd.Timestamp(ingested_at)
    frame["schema_version"] = SCHEMA_VERSION
    frame["position"] = frame["position"].astype("int32")
    return frame[BAN_COLUMNS]
