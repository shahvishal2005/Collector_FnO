# What: read Fyers' public symbol-master CSV (live contracts) into a clean "contract_master" table.
# In: the CSV text and a label such as NSE_FO. Out: a DataFrame in CONTRACT_MASTER_SCHEMA.
"""Contract master (symbol, lot size, expiry, strike, option type) from Fyers' symbol master.

The file has no header. Columns used (positions verified on 2026-10-24): 0 token, 1 description,
2 instrument code, 3 lot size, 4 tick size, 8 expiry epoch, 9 symbol, 13 underlying name,
15 strike (-1 for futures), 16 option type (XX for futures).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime

import pandas as pd
import pyarrow as pa

from collector.common.timeutil import IST

CONTRACT_MASTER_SCHEMA = pa.schema(
    [
        ("exchange_file", pa.string()),
        ("symbol", pa.string()),
        ("fy_token", pa.string()),
        ("description", pa.string()),
        ("instrument_code", pa.int32()),
        ("lot_size", pa.int64()),
        ("tick_size", pa.float64()),
        ("underlying", pa.string()),
        ("expiry_date", pa.date32()),
        ("strike", pa.float64()),
        ("option_type", pa.string()),
    ]
)
CONTRACT_MASTER_COLUMNS = [f.name for f in CONTRACT_MASTER_SCHEMA]
_MIN_COLUMNS = 17


def parse_symbol_master(text: str, label: str) -> pd.DataFrame:
    """Parse the CSV text; rows that do not look like contracts are skipped."""
    records = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) < _MIN_COLUMNS:
            continue
        try:
            expiry = datetime.fromtimestamp(int(row[8]), IST).date()
            strike = float(row[15])
            records.append(
                {
                    "exchange_file": label,
                    "symbol": row[9].strip(),
                    "fy_token": row[0].strip(),
                    "description": row[1].strip(),
                    "instrument_code": int(row[2]),
                    "lot_size": int(float(row[3])),
                    "tick_size": float(row[4]),
                    "underlying": row[13].strip(),
                    "expiry_date": expiry,
                    "strike": strike if strike >= 0 else float("nan"),
                    "option_type": row[16].strip() if row[16].strip() in ("CE", "PE") else None,
                }
            )
        except ValueError:
            continue
    frame = pd.DataFrame.from_records(records, columns=CONTRACT_MASTER_COLUMNS)
    frame["instrument_code"] = frame["instrument_code"].astype("int32")
    return frame
