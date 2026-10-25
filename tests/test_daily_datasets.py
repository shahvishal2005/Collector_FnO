# What: tests for the M3 datasets: parsers, checks, the generic backfill job, manifests and the report.
# In: small real excerpts in tests/fixtures and a fake download client. Out: pass/fail.
"""Participant OI/volume, ban list and index close."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from collector.common.timeutil import now_ist
from collector.config.schema import AppConfig
from collector.datasets.registry import DATASETS
from collector.jobs.backfill_daily import run_dataset_backfill
from collector.normalise.fo_ban import BAN_COLUMNS, parse_ban_list
from collector.normalise.fo_eod import ParseError
from collector.normalise.index_close import INDEX_CLOSE_COLUMNS, parse_index_close
from collector.normalise.participant import PARTICIPANT_COLUMNS, parse_participant
from collector.nse.client import FetchResult, FetchStatus, NseError
from collector.nse.tradingdays import TradingCalendar
from collector.quality.daily_checks import check_ban, check_index_close, check_participant
from collector.quality.daily_report import build_dataset_report
from collector.store.catalogue import Catalogue
from collector.store.dataset_manifest import (
    build_dataset_manifest,
    check_dataset_manifest,
    dataset_days,
)
from collector.store.layout import Layout
from collector.store.parquet import write_table
from tests.conftest import FIXTURES, make_config

NOW = now_ist()
D17, D26 = date(2017, 10, 24), date(2026, 10, 23)


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---- parsers ----
def test_participant_oi_is_tidy_and_adds_up() -> None:
    frame = parse_participant(_read("participant_oi_20171024.csv"), D17, "f", NOW)
    assert list(frame.columns) == PARTICIPANT_COLUMNS and len(frame) == 35
    assert set(frame["client_type"]) == {"Client", "DII", "FII", "Pro", "TOTAL"}
    assert set(frame["category"]) == {
        "FUTIDX",
        "FUTSTK",
        "OPTIDX_CE",
        "OPTIDX_PE",
        "OPTSTK_CE",
        "OPTSTK_PE",
        "TOTAL",
    }
    fii = frame[(frame["client_type"] == "FII") & (frame["category"] == "FUTIDX")].iloc[0]
    assert (fii["long_contracts"], fii["short_contracts"]) == (226653, 145698)
    assert check_participant(frame, D17) == []


def test_participant_files_with_odd_title_quotes_still_parse() -> None:
    oi = parse_participant(_read("participant_oi_20261023.csv"), D26, "f", NOW)
    vol = parse_participant(_read("participant_vol_20261023.csv"), D26, "f", NOW)
    assert len(oi) == len(vol) == 35
    total = oi[(oi["client_type"] == "FII") & (oi["category"] == "TOTAL")].iloc[0]
    assert total["long_contracts"] == 6678878
    assert check_participant(oi, D26) == [] and check_participant(vol, D26) == []


def test_ban_list_with_names_and_with_nil() -> None:
    names = parse_ban_list(_read("ban_20171024.csv"), D17, "f", NOW)
    assert list(names.columns) == BAN_COLUMNS and list(names["symbol"][:3]) == [
        "BEML",
        "DHFL",
        "HDIL",
    ]
    assert len(names) == 8 and check_ban(names, D17) == []
    nil = parse_ban_list(_read("ban_20180601_nil.csv"), date(2018, 6, 1), "f", NOW)
    assert (
        nil.empty and list(nil.columns) == BAN_COLUMNS
    )  # nobody banned: an empty table, not an error
    assert list(parse_ban_list(_read("ban_20261023.csv"), D26, "f", NOW)["symbol"]) == [
        "AMBUJACEM",
        "KAYNES",
        "SAIL",
    ]


def test_index_close() -> None:
    frame = parse_index_close(_read("index_close_20171024.csv"), D17, "f", NOW)
    assert list(frame.columns) == INDEX_CLOSE_COLUMNS and len(frame) == 13
    nifty = frame[frame["index_name"] == "Nifty 50"].iloc[0]
    assert nifty["close"] == 10207.7 and nifty["volume"] == 223914325 and nifty["pe"] == 26.42
    assert str(frame["volume"].dtype) == "Int64" and check_index_close(frame, D17) == []
    assert len(parse_index_close(_read("index_close_20261023.csv"), D26, "f", NOW)) == 13


def test_wrong_dates_and_broken_files_are_rejected() -> None:
    with pytest.raises(ParseError, match="dated"):
        parse_participant(_read("participant_oi_20171024.csv"), date(2017, 10, 25), "f", NOW)
    with pytest.raises(ParseError, match="dated"):
        parse_ban_list(_read("ban_20171024.csv"), date(2017, 10, 25), "f", NOW)
    with pytest.raises(ParseError, match="expected"):
        parse_index_close(_read("index_close_20171024.csv"), date(2017, 10, 25), "f", NOW)
    with pytest.raises(ParseError):
        parse_participant(b"hello\nworld\n!\n", D17, "f", NOW)
    with pytest.raises(ParseError, match="first line"):
        parse_ban_list(b"<html>blocked</html>", D17, "f", NOW)
    with pytest.raises(ParseError, match="missing columns"):
        parse_index_close(b"A,B\n1,2\n", D17, "f", NOW)


# ---- checks ----
def test_participant_checks_catch_a_broken_total() -> None:
    frame = parse_participant(_read("participant_oi_20171024.csv"), D17, "f", NOW)
    broken = frame.copy()
    row = broken[(broken["client_type"] == "FII") & (broken["category"] == "FUTIDX")].index[0]
    broken.loc[row, "long_contracts"] += 5
    assert any(i.check == "PARTICIPANTS_DO_NOT_ADD_UP" for i in check_participant(broken, D17))
    assert any(i.check == "UNEXPECTED_ROW_COUNT" for i in check_participant(frame.iloc[1:], D17))


def test_ban_and_index_checks() -> None:
    frame = parse_ban_list(_read("ban_20171024.csv"), D17, "f", NOW)
    dup = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    assert any(i.check == "DUPLICATE_SYMBOL" for i in check_ban(dup, D17))
    index = parse_index_close(_read("index_close_20171024.csv"), D17, "f", NOW)
    bad = index.copy()
    bad.loc[0, ["high", "low"]] = [1.0, 5.0]
    assert any(i.check == "HIGH_BELOW_LOW" for i in check_index_close(bad, D17))
    twice = pd.concat([index, index.iloc[[0]]], ignore_index=True)
    assert any(i.check == "DUPLICATE_INDEX" for i in check_index_close(twice, D17))


# ---- generic backfill job ----
class FakeClient:
    """Serves the fixture matching the URL, 404 for anything else."""

    def __init__(self, fail_on: str | None = None, html_on: str | None = None) -> None:
        self.urls: list[str] = []
        self._fail_on, self._html_on = fail_on, html_on
        self._files = {
            "fao_participant_oi_24102017": "participant_oi_20171024.csv",
            "fao_participant_oi_23102026": "participant_oi_20261023.csv",
            "fo_secban_24102017": "ban_20171024.csv",
            "fo_secban_01062018": "ban_20180601_nil.csv",
            "ind_close_all_24102017": "index_close_20171024.csv",
        }

    def fetch_file(self, url: str, kind: str = "zip") -> FetchResult:
        self.urls.append(url)
        assert kind == "text"
        if self._fail_on and self._fail_on in url:
            raise NseError("simulated outage")
        for token, name in self._files.items():
            if token in url:
                body = b"<html>x</html>" if self._html_on and self._html_on in url else _read(name)
                return FetchResult(FetchStatus.OK, 200, body)
        return FetchResult(FetchStatus.NOT_FOUND, 404, None)


def _setup(tmp_path: Path) -> tuple[AppConfig, Layout, Catalogue, TradingCalendar]:
    cfg = make_config(tmp_path)
    layout = Layout(cfg.paths.data_root)
    cal = TradingCalendar([D17, date(2017, 10, 25), date(2018, 6, 1), D26], None, None)
    return cfg, layout, Catalogue(layout.catalogue_path), cal


def test_job_downloads_stores_resumes_and_reports(tmp_path: Path) -> None:
    cfg, layout, catalogue, cal = _setup(tmp_path)
    client = FakeClient()
    poi = DATASETS["participant_oi"]
    first = run_dataset_backfill(cfg, layout, catalogue, client, cal, poi, start=D17, end=D26)
    assert first.silver_written == 2 and first.no_file_days == 2 and not first.parse_errors
    assert dataset_days(layout, "participant_oi") == [D17, D26]
    raw = layout.bronze_file("participant_oi", D17, "fao_participant_oi_24102017.csv")
    assert raw.read_bytes() == _read("participant_oi_20171024.csv")  # kept exactly as served

    again = run_dataset_backfill(cfg, layout, catalogue, client, cal, poi, start=D17, end=D26)
    assert again.skipped_complete == 4 and again.downloaded == 0

    manifest = build_dataset_manifest(layout, "participant_oi")
    assert list(manifest["trade_date"]) == ["2017-10-24", "2026-10-23"] and set(
        manifest["rows"]
    ) == {35}
    assert check_dataset_manifest(layout, "participant_oi") == []
    report = build_dataset_report(cfg, layout, catalogue, cal, poi)
    assert report.errors == 0 and report.days_with_data == 2
    assert (
        (layout.reports_root / "participant_oi_report.md")
        .read_text(encoding="utf-8")
        .startswith("# participant_oi")
    )


def test_an_empty_ban_day_is_stored_as_an_empty_table(tmp_path: Path) -> None:
    cfg, layout, catalogue, cal = _setup(tmp_path)
    summary = run_dataset_backfill(
        cfg,
        layout,
        catalogue,
        FakeClient(),
        cal,
        DATASETS["fo_ban"],
        start=date(2018, 6, 1),
        end=date(2018, 6, 1),
    )
    assert summary.silver_written == 1 and dataset_days(layout, "fo_ban") == [date(2018, 6, 1)]
    stored = pd.read_parquet(layout.dataset_silver_file("fo_ban", date(2018, 6, 1)))
    assert stored.empty and list(stored.columns) == BAN_COLUMNS


def test_reprocess_rebuilds_from_bronze_without_the_network(tmp_path: Path) -> None:
    cfg, layout, catalogue, cal = _setup(tmp_path)
    client = FakeClient()
    dataset = DATASETS["index_close"]
    run_dataset_backfill(cfg, layout, catalogue, client, cal, dataset, start=D17, end=D17)
    layout.dataset_silver_file("index_close", D17).unlink()
    calls = len(client.urls)
    redo = run_dataset_backfill(
        cfg, layout, catalogue, client, cal, dataset, start=D17, end=D17, reprocess=True
    )
    assert redo.silver_written == 1 and redo.reused == 1 and len(client.urls) == calls


def test_errors_are_contained(tmp_path: Path) -> None:
    cfg, layout, catalogue, cal = _setup(tmp_path)
    html = run_dataset_backfill(
        cfg,
        layout,
        catalogue,
        FakeClient(html_on="fo_secban"),
        cal,
        DATASETS["fo_ban"],
        start=D17,
        end=D17,
    )
    assert (
        html.parse_errors and html.silver_written == 0
    )  # an HTML page is a parse error for that day
    outage = run_dataset_backfill(
        cfg,
        layout,
        catalogue,
        FakeClient(fail_on="ind_close"),
        cal,
        DATASETS["index_close"],
        start=D17,
        end=date(2017, 10, 25),
    )
    assert len(outage.network_errors) == 2 and not outage.aborted  # below the abort threshold of 3
    streak = run_dataset_backfill(
        cfg,
        layout,
        catalogue,
        FakeClient(fail_on="ind_close"),
        cal,
        DATASETS["index_close"],
        start=D17,
        end=D26,
    )
    assert streak.aborted  # three failures in a row stop the run


def test_manifest_detects_a_changed_file(tmp_path: Path) -> None:
    cfg, layout, catalogue, cal = _setup(tmp_path)
    dataset = DATASETS["participant_oi"]
    run_dataset_backfill(cfg, layout, catalogue, FakeClient(), cal, dataset, start=D17, end=D17)
    build_dataset_manifest(layout, "participant_oi")
    frame = parse_participant(_read("participant_oi_20171024.csv"), D17, "other", NOW)
    write_table(frame.iloc[:5], dataset.schema, layout.dataset_silver_file("participant_oi", D17))
    assert any("checksum" in p for p in check_dataset_manifest(layout, "participant_oi"))
    assert check_dataset_manifest(layout, "fo_ban")[0].startswith("manifest not found")


def test_registry_urls_and_file_names() -> None:
    base = "https://nsearchives.nseindia.com/"
    day = date(2026, 10, 23)
    assert DATASETS["participant_oi"].url(base, day) == (
        "https://nsearchives.nseindia.com/content/nsccl/fao_participant_oi_23102026.csv"
    )
    assert DATASETS["participant_volume"].file_name(day) == "fao_participant_vol_23102026.csv"
    assert DATASETS["fo_ban"].url(base, day).endswith("/archives/fo/sec_ban/fo_secban_23102026.csv")
    assert (
        DATASETS["index_close"]
        .url(base, day)
        .endswith("/content/indices/ind_close_all_23102026.csv")
    )
    assert all(d.kind == "text" for d in DATASETS.values())


def test_fractional_contract_counts_are_kept_exactly() -> None:
    """On 2017-11-24 and 2017-12-06 NSE published counts such as 787007.6667 (thirds)."""
    day = date(2017, 11, 24)
    frame = parse_participant(_read("participant_oi_20171124_fractional.csv"), day, "f", NOW)
    client = frame[(frame["client_type"] == "Client") & (frame["category"] == "OPTIDX_PE")].iloc[0]
    assert client["long_contracts"] == 787007.6667 and client["short_contracts"] == 960374.3333
    total = frame[(frame["client_type"] == "TOTAL") & (frame["category"] == "TOTAL")].iloc[0]
    assert total["long_contracts"] == 5610638 and str(frame["long_contracts"].dtype) == "float64"
    found = {i.check: i for i in check_participant(frame, day)}
    assert (
        found["FRACTIONAL_CONTRACTS"].severity == "info" and found["FRACTIONAL_CONTRACTS"].count > 0
    )
    assert "PARTICIPANTS_DO_NOT_ADD_UP" not in found  # the fractions still add up to TOTAL
    other = parse_participant(
        _read("participant_oi_20171206_fractional.csv"), date(2017, 12, 6), "f", NOW
    )
    assert not [i for i in check_participant(other, date(2017, 12, 6)) if i.severity == "error"]


def test_calendar_falls_back_to_the_days_that_have_fo_files() -> None:
    from collector.nse.tradingdays import calendar_with_fallback

    fo_days = frozenset(
        {date(2024, 11, 1), date(2024, 11, 4), date(2024, 11, 5)}
    )  # 1 Nov = Muhurat Friday
    cal = calendar_with_fallback(date(2024, 11, 1), date(2024, 11, 8), None, fo_days)
    assert cal.known_trading_days == fo_days and cal.known_until == date(2024, 11, 5)
    assert date(2024, 11, 2) not in cal.candidates  # a plain Saturday is still not asked for
    weekend = calendar_with_fallback(
        date(2024, 3, 1),
        date(2024, 3, 8),
        None,
        frozenset({date(2024, 3, 2)}),  # a special Saturday session
    )
    assert date(2024, 3, 2) in weekend.candidates
    assert (
        calendar_with_fallback(
            date(2024, 11, 1), date(2024, 11, 8), None, frozenset()
        ).known_trading_days
        is None
    )
