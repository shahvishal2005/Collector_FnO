# What: read NSE F&O bhavcopy zip files (old and new format) into one clean table, "fo_eod".
# In: zip bytes, the file's expected trade date, its source name. Out: a DataFrame in FO_EOD_SCHEMA.
"""F&O end-of-day normalisation.

Units after normalisation (verified on the overlap days 2024-07-03..05, where both formats give
identical contracts):
- volume_contracts: number of contracts (lots) traded.
- open_interest_qty / chg_in_oi_qty: open interest in units (shares/index units), not lots.
- turnover_inr: rupees (the old file reports lakh rupees; it is multiplied by 100,000).
- lot_size: only in the new format; null for old rows (not guessed).
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime

import numpy as np
import pandas as pd
import pyarrow as pa

SCHEMA_VERSION = 1
LAKH = 100_000.0

FO_EOD_SCHEMA = pa.schema(
    [
        ("trade_date", pa.date32()),
        ("instrument_type", pa.string()),
        ("underlying", pa.string()),
        ("expiry_date", pa.date32()),
        ("strike", pa.float64()),
        ("option_type", pa.string()),
        ("open", pa.float64()),
        ("high", pa.float64()),
        ("low", pa.float64()),
        ("close", pa.float64()),
        ("last_price", pa.float64()),
        ("prev_close", pa.float64()),
        ("underlying_price", pa.float64()),
        ("settle_price", pa.float64()),
        ("volume_contracts", pa.int64()),
        ("turnover_inr", pa.float64()),
        ("trades", pa.int64()),
        ("open_interest_qty", pa.int64()),
        ("chg_in_oi_qty", pa.int64()),
        ("lot_size", pa.int64()),
        ("source_format", pa.string()),
        ("source_file", pa.string()),
        ("ingested_at", pa.timestamp("us", tz="Asia/Kolkata")),
        ("schema_version", pa.int32()),
    ]
)
FO_EOD_COLUMNS = [field.name for field in FO_EOD_SCHEMA]
NATURAL_KEY = [
    "trade_date",
    "instrument_type",
    "underlying",
    "expiry_date",
    "strike",
    "option_type",
]

_OLD_REQUIRED = [
    "INSTRUMENT", "SYMBOL", "EXPIRY_DT", "STRIKE_PR", "OPTION_TYP", "OPEN", "HIGH", "LOW",
    "CLOSE", "SETTLE_PR", "CONTRACTS", "VAL_INLAKH", "OPEN_INT", "CHG_IN_OI", "TIMESTAMP",
]  # fmt: skip
_NEW_REQUIRED = [
    "TradDt", "FinInstrmTp", "TckrSymb", "XpryDt", "StrkPric", "OptnTp", "OpnPric", "HghPric",
    "LwPric", "ClsPric", "LastPric", "PrvsClsgPric", "UndrlygPric", "SttlmPric", "OpnIntrst",
    "ChngInOpnIntrst", "TtlTradgVol", "TtlTrfVal", "TtlNbOfTxsExctd", "NewBrdLotQty",
]  # fmt: skip
_MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}  # fmt: skip
_NEW_INSTRUMENTS = {"IDF": "FUTIDX", "STF": "FUTSTK", "IDO": "OPTIDX", "STO": "OPTSTK"}
_OLD_INSTRUMENTS = {"FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK", "FUTIVX"}
FUTURE_TYPES = {"FUTIDX", "FUTSTK", "FUTIVX"}
OPTION_TYPES = {"OPTIDX", "OPTSTK"}


class ParseError(Exception):
    """A bhavcopy file does not look like the format we expect."""


def read_csv_from_zip(content: bytes) -> pd.DataFrame:
    """Open the single CSV inside the zip and return it with every column as text."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise ParseError(f"expected exactly one CSV in the zip, found {archive.namelist()}")
            data = archive.read(names[0])
    except zipfile.BadZipFile as exc:
        raise ParseError(f"not a valid zip file: {exc}") from exc
    frame = pd.read_csv(io.BytesIO(data), dtype=str, index_col=False, keep_default_na=False)
    frame.columns = [str(c).strip() for c in frame.columns]
    return frame


def _require(frame: pd.DataFrame, columns: list[str]) -> None:
    """Raise ParseError naming any missing column."""
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ParseError(f"missing columns {missing}; found {list(frame.columns)}")


def _num(series: pd.Series) -> pd.Series:
    """Text to float; blank becomes NaN; anything else non-numeric raises."""
    cleaned = series.astype(str).str.strip().replace({"": np.nan, "-": np.nan})
    return pd.to_numeric(cleaned, errors="raise").astype("float64")


def _int(series: pd.Series) -> pd.Series:
    """Text to nullable integer."""
    return _num(series).round().astype("Int64")


def _option_type(column: pd.Series, is_future: pd.Series) -> pd.Series:
    """CE / PE for option rows; None for futures and for anything else."""
    cleaned = column.str.strip().str.upper()
    valid = cleaned.isin(["CE", "PE"]) & ~is_future
    values = [text if keep else None for text, keep in zip(cleaned, valid, strict=True)]
    return pd.Series(values, index=cleaned.index, dtype=object)


def _old_dates(series: pd.Series) -> pd.Series:
    """Parse 'dd-Mon-yyyy' (any case) without depending on the computer's language."""
    parts = series.astype(str).str.strip().str.split("-", expand=True)
    if parts.shape[1] != 3:
        raise ParseError("date column is not in dd-Mon-yyyy form")
    months = parts[1].str.upper().map(_MONTHS)
    if months.isna().any():
        raise ParseError(f"unknown month name in dates: {sorted(set(parts[1][months.isna()]))}")
    stamp = pd.to_datetime(
        {"year": parts[2].astype(int), "month": months.astype(int), "day": parts[0].astype(int)}
    )
    return stamp.dt.date


def _finish(frame: pd.DataFrame, fmt: str, source_file: str, ingested_at: datetime) -> pd.DataFrame:
    """Add lineage columns, fix column order and return the table sorted by its natural key."""
    frame["source_format"] = fmt
    frame["source_file"] = source_file
    frame["ingested_at"] = pd.Timestamp(ingested_at)
    frame["schema_version"] = SCHEMA_VERSION
    ordered = frame[FO_EOD_COLUMNS].copy()
    return ordered.sort_values(NATURAL_KEY, na_position="first").reset_index(drop=True)


def _check_trade_date(frame: pd.DataFrame, expected: date) -> None:
    """The file's own date column must equal the date we asked for."""
    found = set(frame["trade_date"])
    if found != {expected}:
        raise ParseError(f"file contains trade dates {sorted(found)}, expected {expected}")


def normalise_old(
    raw: pd.DataFrame, expected: date, source_file: str, ingested_at: datetime
) -> pd.DataFrame:
    """Old-format table (until early July 2024) to the fo_eod schema."""
    _require(raw, _OLD_REQUIRED)
    unknown = set(raw["INSTRUMENT"].str.strip()) - _OLD_INSTRUMENTS
    if unknown:
        raise ParseError(f"unknown INSTRUMENT values {sorted(unknown)}")
    instrument = raw["INSTRUMENT"].str.strip()
    is_future = instrument.isin(FUTURE_TYPES)
    option_type = _option_type(raw["OPTION_TYP"], is_future)
    strike = _num(raw["STRIKE_PR"]).where(~is_future, float("nan"))
    out = pd.DataFrame(
        {
            "trade_date": _old_dates(raw["TIMESTAMP"]),
            "instrument_type": instrument,
            "underlying": raw["SYMBOL"].str.strip(),
            "expiry_date": _old_dates(raw["EXPIRY_DT"]),
            "strike": strike,
            "option_type": option_type,
            "open": _num(raw["OPEN"]),
            "high": _num(raw["HIGH"]),
            "low": _num(raw["LOW"]),
            "close": _num(raw["CLOSE"]),
            "last_price": float("nan"),
            "prev_close": float("nan"),
            "underlying_price": float("nan"),
            "settle_price": _num(raw["SETTLE_PR"]),
            "volume_contracts": _int(raw["CONTRACTS"]),
            "turnover_inr": _num(raw["VAL_INLAKH"]) * LAKH,
            "trades": pd.array([pd.NA] * len(raw), dtype="Int64"),
            "open_interest_qty": _int(raw["OPEN_INT"]),
            "chg_in_oi_qty": _int(raw["CHG_IN_OI"]),
            "lot_size": pd.array([pd.NA] * len(raw), dtype="Int64"),
        }
    )
    _check_trade_date(out, expected)
    return _finish(out, "old", source_file, ingested_at)


def normalise_new(
    raw: pd.DataFrame, expected: date, source_file: str, ingested_at: datetime
) -> pd.DataFrame:
    """New (UDiFF) format table (from July 2024) to the fo_eod schema."""
    _require(raw, _NEW_REQUIRED)
    codes = raw["FinInstrmTp"].str.strip()
    unknown = set(codes) - set(_NEW_INSTRUMENTS)
    if unknown:
        raise ParseError(f"unknown FinInstrmTp values {sorted(unknown)}")
    instrument = codes.map(_NEW_INSTRUMENTS)
    symbol = raw["TckrSymb"].str.strip()
    instrument = instrument.where(
        ~((instrument == "FUTIDX") & symbol.str.contains("VIX")), "FUTIVX"
    )
    is_future = instrument.isin(FUTURE_TYPES)
    option_type = _option_type(raw["OptnTp"], is_future)
    strike = _num(raw["StrkPric"]).where(~is_future, float("nan"))
    out = pd.DataFrame(
        {
            "trade_date": pd.to_datetime(raw["TradDt"].str.strip(), format="%Y-%m-%d").dt.date,
            "instrument_type": instrument,
            "underlying": symbol,
            "expiry_date": pd.to_datetime(raw["XpryDt"].str.strip(), format="%Y-%m-%d").dt.date,
            "strike": strike,
            "option_type": option_type,
            "open": _num(raw["OpnPric"]),
            "high": _num(raw["HghPric"]),
            "low": _num(raw["LwPric"]),
            "close": _num(raw["ClsPric"]),
            "last_price": _num(raw["LastPric"]),
            "prev_close": _num(raw["PrvsClsgPric"]),
            "underlying_price": _num(raw["UndrlygPric"]),
            "settle_price": _num(raw["SttlmPric"]),
            "volume_contracts": _int(raw["TtlTradgVol"]),
            "turnover_inr": _num(raw["TtlTrfVal"]),
            "trades": _int(raw["TtlNbOfTxsExctd"]),
            "open_interest_qty": _int(raw["OpnIntrst"]),
            "chg_in_oi_qty": _int(raw["ChngInOpnIntrst"]),
            "lot_size": _int(raw["NewBrdLotQty"]),
        }
    )
    _check_trade_date(out, expected)
    return _finish(out, "new", source_file, ingested_at)


def parse_fo_zip(
    content: bytes, fmt: str, expected: date, source_file: str, ingested_at: datetime
) -> pd.DataFrame:
    """Zip bytes of either format to the fo_eod table."""
    raw = read_csv_from_zip(content)
    if fmt == "old":
        return normalise_old(raw, expected, source_file, ingested_at)
    if fmt == "new":
        return normalise_new(raw, expected, source_file, ingested_at)
    raise ParseError(f"unknown format {fmt!r}")
