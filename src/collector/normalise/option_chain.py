# What: turn one Fyers option-chain answer into clean table rows ("option_chain" schema).
# In: the raw answer (a dict), which underlying/expiry it was for, and the two timestamps.
# Out: a DataFrame in OPTION_CHAIN_SCHEMA (one row per call/put), or ChainError if unusable.
"""Option-chain normalisation.

Facts about the answer (from the day-0 probe, docs/PROBE_FINDINGS.md): `data.optionsChain` holds
an index/stock row first (strike -1, no option type) and then one row per option; it has no
implied volatility. Volume is in units; open interest is in units. `data.expiryData` lists the
available expiries (epoch as text, flag M or W). The rows carry no expiry, so the expiry the call
was made for is passed in.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd
import pyarrow as pa

from collector.common.timeutil import IST

SCHEMA_VERSION = 1

OPTION_CHAIN_SCHEMA = pa.schema(
    [
        ("snapshot_ts", pa.timestamp("us", tz="Asia/Kolkata")),
        ("received_ts", pa.timestamp("us", tz="Asia/Kolkata")),
        ("underlying", pa.string()),
        ("tier", pa.int32()),
        ("expiry_date", pa.date32()),
        ("expiry_flag", pa.string()),
        ("strike", pa.float64()),
        ("option_type", pa.string()),
        ("symbol", pa.string()),
        ("fy_token", pa.string()),
        ("ltp", pa.float64()),
        ("ltp_ch", pa.float64()),
        ("ltp_chp", pa.float64()),
        ("bid", pa.float64()),
        ("ask", pa.float64()),
        ("volume_units", pa.int64()),
        ("oi_qty", pa.int64()),
        ("prev_oi_qty", pa.int64()),
        ("oi_ch_qty", pa.int64()),
        ("oi_ch_pct", pa.float64()),
        ("underlying_ltp", pa.float64()),
        ("future_price", pa.float64()),
        ("vix", pa.float64()),
        ("total_call_oi", pa.int64()),
        ("total_put_oi", pa.int64()),
        ("schema_version", pa.int32()),
    ]
)
OPTION_CHAIN_COLUMNS = [field.name for field in OPTION_CHAIN_SCHEMA]


class ChainError(Exception):
    """The answer is an error or does not have the expected shape."""


def expiry_date_from_epoch(epoch: str | int) -> date:
    """The calendar date (IST) of an expiry given as epoch seconds."""
    return datetime.fromtimestamp(int(epoch), IST).date()


def expiries_from_response(response: dict[str, Any]) -> list[tuple[str, str | None]]:
    """The (epoch text, flag) of every expiry listed in an answer, nearest first."""
    data = response.get("data")
    listed = data.get("expiryData") if isinstance(data, dict) else None
    result: list[tuple[str, str | None]] = []
    if isinstance(listed, list):
        for entry in listed:
            if isinstance(entry, dict) and entry.get("expiry"):
                flag = entry.get("expiry_flag")
                result.append((str(entry["expiry"]), str(flag) if flag else None))
    return result


def _num(row: dict[str, Any], key: str) -> float:
    """A number from a row, or NaN when missing."""
    value = row.get(key)
    return float(value) if isinstance(value, int | float) else float("nan")


def _int(row: dict[str, Any], key: str) -> int | None:
    """A whole number from a row, or None when missing."""
    value = row.get(key)
    return int(value) if isinstance(value, int | float) else None


def normalise_chain(
    response: dict[str, Any],
    *,
    underlying: str,
    tier: int,
    expiry_epoch: str,
    expiry_flag: str | None,
    snapshot_ts: datetime,
    received_ts: datetime,
) -> pd.DataFrame:
    """One call's answer to rows. Raises ChainError if the answer is not a usable chain."""
    if response.get("s") != "ok":
        raise ChainError(f"answer not ok: code={response.get('code')} {response.get('message')}")
    data = response.get("data")
    rows = data.get("optionsChain") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not isinstance(data, dict):
        raise ChainError("answer has no optionsChain list")
    spot = next((r for r in rows if isinstance(r, dict) and r.get("option_type") in ("", None)), {})
    vix_data = data.get("indiavixData")
    vix = _num(vix_data, "ltp") if isinstance(vix_data, dict) else float("nan")
    expiry = expiry_date_from_epoch(expiry_epoch)
    records: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("option_type") not in ("CE", "PE"):
            continue
        records.append(
            {
                "snapshot_ts": pd.Timestamp(snapshot_ts),
                "received_ts": pd.Timestamp(received_ts),
                "underlying": underlying,
                "tier": tier,
                "expiry_date": expiry,
                "expiry_flag": expiry_flag,
                "strike": _num(row, "strike_price"),
                "option_type": row["option_type"],
                "symbol": str(row.get("symbol", "")),
                "fy_token": str(row.get("fyToken", "")) or None,
                "ltp": _num(row, "ltp"),
                "ltp_ch": _num(row, "ltpch"),
                "ltp_chp": _num(row, "ltpchp"),
                "bid": _num(row, "bid"),
                "ask": _num(row, "ask"),
                "volume_units": _int(row, "volume"),
                "oi_qty": _int(row, "oi"),
                "prev_oi_qty": _int(row, "prev_oi"),
                "oi_ch_qty": _int(row, "oich"),
                "oi_ch_pct": _num(row, "oichp"),
                "underlying_ltp": _num(spot, "ltp"),
                "future_price": _num(spot, "fp"),
                "vix": vix,
                "total_call_oi": _int(data, "callOi"),
                "total_put_oi": _int(data, "putOi"),
                "schema_version": SCHEMA_VERSION,
            }
        )
    frame = pd.DataFrame.from_records(records, columns=OPTION_CHAIN_COLUMNS)
    for column in (
        "volume_units", "oi_qty", "prev_oi_qty", "oi_ch_qty", "total_call_oi", "total_put_oi",
    ):  # fmt: skip
        frame[column] = frame[column].astype("Int64")
    return frame
