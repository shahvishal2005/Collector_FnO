# What: tests for quality checks, Parquet/catalogue/manifest storage and the trading calendar.
# In: fixture data and temp folders. Out: pass/fail.
"""Quality, storage and calendar."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from collector.common.timeutil import IST, now_ist
from collector.normalise.fo_eod import FO_EOD_SCHEMA, parse_fo_zip
from collector.nse.tradingdays import build_calendar
from collector.quality.coverage import analyse_coverage
from collector.quality.fo_checks import ERROR, check_day, check_row_count_jumps, compare_formats
from collector.store.catalogue import Catalogue, CatalogueRow
from collector.store.layout import Layout
from collector.store.manifest import build_manifest, check_manifest, silver_days
from collector.store.parquet import read_table, write_table
from tests.conftest import make_zip

DAY = date(2017, 11, 1)


def _frame() -> pd.DataFrame:
    return parse_fo_zip(make_zip("old_20171101.csv"), "old", DAY, "f", now_ist())


def _checks(frame: pd.DataFrame) -> set[str]:
    return {i.check for i in check_day(frame, DAY, 3)}


def test_clean_fixture_has_no_errors() -> None:
    assert not [i for i in check_day(_frame(), DAY, 3) if i.severity == ERROR]


def test_each_defect_is_detected() -> None:
    frame = _frame()
    dup = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    assert "DUPLICATE_KEY" in _checks(dup)
    negative = frame.copy()
    negative.loc[0, "open_interest_qty"] = -5
    assert "NEGATIVE_OPEN_INTEREST_QTY" in _checks(negative)
    broken = frame.copy()
    broken.loc[0, ["volume_contracts", "high", "low"]] = [10, 1.0, 5.0]
    assert "HIGH_BELOW_LOW" in _checks(broken)
    opt = frame[frame.instrument_type == "OPTIDX"].index[0]
    no_type = frame.copy()
    no_type.loc[opt, "option_type"] = None
    assert "OPTION_WITHOUT_TYPE" in _checks(no_type)
    expired = frame.copy()
    expired.loc[0, "expiry_date"] = date(2017, 10, 1)
    assert "EXPIRY_BEFORE_TRADE" in _checks(expired)
    wrong_day = frame.copy()
    wrong_day["trade_date"] = date(2017, 11, 2)
    assert "DATE_MISMATCH" in _checks(wrong_day)
    assert "FEW_UNDERLYINGS" in {i.check for i in check_day(frame.iloc[:2], DAY, 50)}
    assert _checks(frame.iloc[0:0]) == {"EMPTY_DAY"}


def test_close_outside_range_is_info_for_settlement_and_warn_otherwise() -> None:
    frame = _frame()
    row = frame[frame.instrument_type == "FUTSTK"].index[0]
    frame.loc[row, ["volume_contracts", "open", "high", "low", "close", "settle_price"]] = [
        3, 100.0, 101.0, 99.0, 105.0, 105.0,
    ]  # fmt: skip
    found = {i.check: i.severity for i in check_day(frame, DAY, 3)}
    assert found["SETTLEMENT_CLOSE_OUTSIDE_RANGE"] == "info"
    assert "CLOSE_OUTSIDE_RANGE" not in found
    frame.loc[row, "settle_price"] = 104.0
    found = {i.check: i.severity for i in check_day(frame, DAY, 3)}
    assert found["CLOSE_OUTSIDE_RANGE"] == "warn"


def test_row_count_jump_detection() -> None:
    counts = {date(2024, 1, d): 1000 for d in range(1, 11)}
    counts[date(2024, 1, 11)] = 100
    flagged = check_row_count_jumps(counts, 0.5)
    assert [i.trade_date for i in flagged] == [date(2024, 1, 11)]
    assert check_row_count_jumps({date(2024, 1, 1): 5}, 0.5) == []


def test_compare_formats_detects_a_difference() -> None:
    day = date(2024, 7, 3)
    old = parse_fo_zip(make_zip("old_20240703.csv"), "old", day, "o", now_ist())
    new = parse_fo_zip(make_zip("new_20240703.csv"), "new", day, "n", now_ist())
    changed = new.copy()
    changed.loc[0, "open_interest_qty"] = changed.loc[0, "open_interest_qty"] + 1
    result = compare_formats(old, changed, day)
    assert not result.identical and result.mismatches["open_interest_qty"] == 1
    dropped = compare_formats(old, new.iloc[1:], day)
    assert dropped.only_old == 1


def test_parquet_roundtrip_and_atomic_replace(tmp_path: Path) -> None:
    path = tmp_path / "a" / "part-0.parquet"
    frame = _frame()
    write_table(frame, FO_EOD_SCHEMA, path)
    back = read_table(path)
    assert len(back) == len(frame) and list(back.columns) == list(frame.columns)
    assert pq.read_schema(path).field("ingested_at").type == pa.timestamp("us", tz="Asia/Kolkata")
    assert not list(path.parent.glob("*.tmp"))
    write_table(frame.iloc[:3], FO_EOD_SCHEMA, path)  # replaces cleanly
    assert len(read_table(path)) == 3


def test_catalogue_records_and_resumes(tmp_path: Path) -> None:
    catalogue = Catalogue(tmp_path / "c.sqlite")
    assert catalogue.get("nse_fo", DAY, "old") is None
    row = CatalogueRow("nse_fo", DAY, "old", "ok", "u", 200, "t", 10, "abc", "p")
    catalogue.record(row)
    assert catalogue.get("nse_fo", DAY, "old") == row
    catalogue.record(
        CatalogueRow("nse_fo", DAY, "old", "not_found", "u", 404, "t2", None, None, None)
    )
    assert catalogue.get("nse_fo", DAY, "old") is not None
    assert [r.status for r in catalogue.rows("nse_fo")] == ["not_found"]


def test_manifest_detects_changes(tmp_path: Path) -> None:
    layout = Layout(tmp_path / "data")
    write_table(_frame(), FO_EOD_SCHEMA, layout.fo_silver_file(DAY))
    assert silver_days(layout) == [DAY]
    assert check_manifest(layout) and "not found" in check_manifest(layout)[0]
    manifest = build_manifest(layout)
    assert manifest.loc[0, "rows"] == len(_frame())
    assert check_manifest(layout) == []
    write_table(_frame().iloc[:5], FO_EOD_SCHEMA, layout.fo_silver_file(DAY))
    assert any("checksum" in p for p in check_manifest(layout))
    write_table(
        _frame(),
        FO_EOD_SCHEMA,
        layout.fo_silver_file(date(2017, 11, 2)).parent.parent
        / "trade_date=2017-11-02"
        / "part-0.parquet",
    )
    assert any("not in manifest" in p for p in check_manifest(layout))


def _write_candles(root: Path, days: list[date]) -> None:
    stamps = pd.DatetimeIndex([pd.Timestamp(d.isoformat() + " 09:15", tz=IST) for d in days])
    for year in sorted({d.year for d in days}):
        part = root / f"year={year}"
        part.mkdir(parents=True)
        pd.DataFrame({"ts": [s for s in stamps if s.year == year]}).to_parquet(
            part / "candles.parquet"
        )


def test_calendar_adds_weekend_sessions_and_reports_coverage(tmp_path: Path) -> None:
    root = tmp_path / "candles"
    trading = [
        date(2020, 11, 12),
        date(2020, 11, 13),
        date(2020, 11, 14),
    ]  # Fri, Sat (Muhurat), plus Thu
    _write_candles(root, trading)
    cal = build_calendar(date(2020, 11, 11), date(2020, 11, 16), root)
    assert date(2020, 11, 14) in cal.candidates and date(2020, 11, 15) not in cal.candidates
    assert cal.known_until == date(2020, 11, 14)
    held = {date(2020, 11, 12), date(2020, 11, 14), date(2020, 11, 11)}
    coverage = analyse_coverage(held, cal.known_trading_days, cal.known_until, date(2020, 11, 11))
    assert coverage.missing == [date(2020, 11, 13)] and coverage.extra == [date(2020, 11, 11)]
    assert int(coverage.table.loc[0, "missing_days"]) == 1


def test_calendar_without_candles_uses_weekdays(tmp_path: Path) -> None:
    cal = build_calendar(date(2020, 11, 9), date(2020, 11, 15), None)
    assert len(cal.candidates) == 5 and cal.known_trading_days is None
    judged = analyse_coverage({date(2020, 11, 9)}, None, None, date(2020, 11, 9))
    assert judged.judged_until is None and judged.missing == []
    gone = build_calendar(date(2020, 11, 9), date(2020, 11, 15), tmp_path / "does-not-exist")
    assert gone.known_trading_days is None


@pytest.mark.parametrize("name", ["old_20171101.csv"])
def test_checks_do_not_modify_input(name: str) -> None:
    frame = _frame()
    before = frame.copy()
    check_day(frame, DAY, 3)
    pd.testing.assert_frame_equal(frame, before)
