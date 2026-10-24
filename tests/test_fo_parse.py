# What: tests that both bhavcopy formats parse into the same schema and agree on overlap days.
# In: small real excerpts in tests/fixtures. Out: pass/fail.
"""F&O parsing and normalisation."""

from __future__ import annotations

import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from collector.common.timeutil import now_ist
from collector.normalise.fo_eod import (
    FO_EOD_COLUMNS,
    NATURAL_KEY,
    SCHEMA_VERSION,
    ParseError,
    parse_fo_zip,
)
from collector.quality.fo_checks import compare_formats
from tests.conftest import make_zip

NOW = now_ist()


def _old(name: str, day: date) -> pd.DataFrame:
    return parse_fo_zip(make_zip(name), "old", day, name, NOW)


def _new(name: str, day: date) -> pd.DataFrame:
    return parse_fo_zip(make_zip(name), "new", day, name, NOW)


def test_old_format_schema_and_units() -> None:
    frame = _old("old_20171101.csv", date(2017, 11, 1))
    assert list(frame.columns) == FO_EOD_COLUMNS
    assert set(frame["trade_date"]) == {date(2017, 11, 1)}
    first = frame[
        (frame.underlying == "BANKNIFTY")
        & (frame.expiry_date == date(2017, 11, 30))
        & (frame.instrument_type == "FUTIDX")
    ].iloc[0]
    assert first["turnover_inr"] == pytest.approx(760562.92 * 100_000)  # lakh -> rupees
    assert first["open_interest_qty"] == 2059280 and first["chg_in_oi_qty"] == 355360
    assert pd.isna(first["strike"]) and first["option_type"] is None  # futures have neither
    assert pd.isna(first["lot_size"]) and pd.isna(first["trades"])  # not in the old file
    assert (frame["source_format"] == "old").all() and (
        frame["schema_version"] == SCHEMA_VERSION
    ).all()


def test_old_format_options_and_negative_oi_change() -> None:
    frame = _old("old_20171101.csv", date(2017, 11, 1))
    options = frame[frame.instrument_type.isin(["OPTIDX", "OPTSTK"])]
    assert set(options["option_type"]) <= {"CE", "PE"} and options["option_type"].notna().all()
    assert (options["strike"] > 0).all()
    assert (frame["chg_in_oi_qty"] < 0).any()
    assert set(frame["instrument_type"]) <= {"FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK", "FUTIVX"}


def test_new_format_schema_and_codes() -> None:
    frame = _new("new_20261023.csv", date(2026, 10, 23))
    assert list(frame.columns) == FO_EOD_COLUMNS
    assert set(frame["instrument_type"]) == {"FUTIDX", "FUTSTK", "OPTIDX", "OPTSTK"}
    assert frame["lot_size"].notna().all() and frame["underlying_price"].notna().all()
    futures = frame[frame.instrument_type.str.startswith("FUT")]
    assert futures["strike"].isna().all() and futures["option_type"].isna().all()


def test_keys_are_unique() -> None:
    for frame in (
        _old("old_20171101.csv", date(2017, 11, 1)),
        _new("new_20261023.csv", date(2026, 10, 23)),
    ):
        assert not frame.duplicated(NATURAL_KEY).any()


def test_formats_agree_on_the_overlap_day() -> None:
    day = date(2024, 7, 3)
    result = compare_formats(_old("old_20240703.csv", day), _new("new_20240703.csv", day), day)
    assert result.matched_rows == 47 and result.only_old == 0 and result.only_new == 0
    assert result.identical, result.mismatches


def test_wrong_trade_date_is_rejected() -> None:
    with pytest.raises(ParseError, match="trade dates"):
        _old("old_20171101.csv", date(2017, 11, 2))


def test_missing_columns_are_named() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("x.csv", "A,B\n1,2\n")
    with pytest.raises(ParseError, match="missing columns"):
        parse_fo_zip(buffer.getvalue(), "old", date(2017, 11, 1), "x.zip", NOW)


def test_bad_zip_and_unknown_format() -> None:
    with pytest.raises(ParseError, match="not a valid zip"):
        parse_fo_zip(b"not a zip", "old", date(2017, 11, 1), "x", NOW)
    with pytest.raises(ParseError, match="unknown format"):
        parse_fo_zip(make_zip("old_20171101.csv"), "weird", date(2017, 11, 1), "x", NOW)


def test_unknown_instrument_is_rejected() -> None:
    header = (
        "INSTRUMENT,SYMBOL,EXPIRY_DT,STRIKE_PR,OPTION_TYP,OPEN,HIGH,LOW,CLOSE,SETTLE_PR,"
        "CONTRACTS,VAL_INLAKH,OPEN_INT,CHG_IN_OI,TIMESTAMP,"
    )
    text = f"{header}\nFUTXXX,A,30-Nov-2017,0,XX,1,1,1,1,1,1,1,1,1,01-NOV-2017,\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("x.csv", text)
    with pytest.raises(ParseError, match="unknown INSTRUMENT"):
        parse_fo_zip(buffer.getvalue(), "old", date(2017, 11, 1), "x", NOW)
