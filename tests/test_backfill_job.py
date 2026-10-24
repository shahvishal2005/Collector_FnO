# What: end-to-end tests of the backfill job with a fake download client (no network).
# In: fixture zips served by a fake client. Out: pass/fail.
"""Backfill job."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from collector.config.schema import AppConfig
from collector.jobs.backfill_fo import run_backfill
from collector.nse.client import FetchResult, FetchStatus, NseError
from collector.nse.tradingdays import TradingCalendar
from collector.quality.report import build_report
from collector.store.catalogue import Catalogue
from collector.store.layout import Layout
from collector.store.manifest import build_manifest, check_manifest, silver_days
from tests.conftest import make_config, make_zip

D1 = date(2017, 11, 1)  # served (old format)
D2 = date(2017, 11, 2)  # holiday: 404
D3 = date(2024, 7, 3)  # overlap day: both formats served
D4 = date(2026, 10, 23)  # new format only


class FakeClient:
    """Serves fixture zips by URL fragment and records every request."""

    def __init__(self, errors: set[str] | None = None) -> None:
        self.urls: list[str] = []
        self.errors = errors or set()
        self.files = {
            "fo01NOV2017bhav": make_zip("old_20171101.csv"),
            "fo03JUL2024bhav": make_zip("old_20240703.csv"),
            "BhavCopy_NSE_FO_0_0_0_20240703": make_zip("new_20240703.csv"),
            "BhavCopy_NSE_FO_0_0_0_20261023": make_zip("new_20261023.csv"),
        }

    def fetch_zip(self, url: str) -> FetchResult:
        self.urls.append(url)
        if any(token in url for token in self.errors):
            raise NseError("simulated outage")
        for token, body in self.files.items():
            if token in url:
                return FetchResult(FetchStatus.OK, 200, body)
        return FetchResult(FetchStatus.NOT_FOUND, 404, None)


def _setup(tmp_path: Path) -> tuple[AppConfig, Layout, Catalogue, TradingCalendar]:
    cfg = make_config(tmp_path)
    layout = Layout(cfg.paths.data_root)
    cal = TradingCalendar([D1, D2, D3, D4], None, None)
    return cfg, layout, Catalogue(layout.catalogue_path), cal


def test_end_to_end_resume_and_report(tmp_path: Path) -> None:
    cfg, layout, catalogue, cal = _setup(tmp_path)
    client = FakeClient()
    first = run_backfill(cfg, layout, catalogue, client, cal, start=D1, end=D4)
    assert first.silver_written == 3 and first.no_file_days == 1 and not first.parse_errors
    assert silver_days(layout) == [D1, D3, D4]
    assert len(client.urls) == 5  # D1, D2, D3 old+new, D4
    # raw files are kept exactly as served
    assert (
        layout.bronze_file("nse_fo", D1, "fo01NOV2017bhav.csv.zip").read_bytes()
        == client.files["fo01NOV2017bhav"]
    )

    again = run_backfill(cfg, layout, catalogue, client, cal, start=D1, end=D4)
    assert again.skipped_complete == 4 and again.downloaded == 0 and len(client.urls) == 5

    rechecked = run_backfill(
        cfg, layout, catalogue, client, cal, start=D2, end=D2, recheck_missing=True
    )
    assert rechecked.downloaded == 1 and len(client.urls) == 6

    manifest = build_manifest(layout)
    assert list(manifest["trade_date"]) == [D1.isoformat(), D3.isoformat(), D4.isoformat()]
    assert check_manifest(layout) == []
    result = build_report(cfg, layout, catalogue, cal)
    assert result.errors == 0 and result.overlap_days == 1 and result.overlap_identical == 1
    assert (
        (layout.reports_root / "fo_eod_report.md").read_text(encoding="utf-8").startswith("# F&O")
    )


def test_reprocess_rebuilds_silver_from_bronze_without_network(tmp_path: Path) -> None:
    cfg, layout, catalogue, cal = _setup(tmp_path)
    client = FakeClient()
    run_backfill(cfg, layout, catalogue, client, cal, start=D1, end=D1)
    layout.fo_silver_file(D1).unlink()
    calls = len(client.urls)
    redo = run_backfill(cfg, layout, catalogue, client, cal, start=D1, end=D1, reprocess=True)
    assert redo.silver_written == 1 and redo.reused == 1 and len(client.urls) == calls


def test_limit_and_abort_on_repeated_errors(tmp_path: Path) -> None:
    cfg, layout, catalogue, cal = _setup(tmp_path)
    limited = run_backfill(cfg, layout, catalogue, FakeClient(), cal, start=D1, end=D4, limit=1)
    assert limited.considered == 1
    days = [date(2017, 11, 6) + (date(2017, 11, 7) - date(2017, 11, 6)) * n for n in range(5)]
    cfg2, layout2, catalogue2, _ = _setup(tmp_path / "second")
    outage = run_backfill(
        cfg2,
        layout2,
        catalogue2,
        FakeClient(errors={"NOV2017"}),
        TradingCalendar(days, None, None),
        start=days[0],
        end=days[-1],
    )
    assert outage.aborted and len(outage.network_errors) == 3  # abort_after_consecutive_errors


def test_corrupt_file_is_a_parse_error_not_a_crash(tmp_path: Path) -> None:
    cfg, layout, catalogue, cal = _setup(tmp_path)
    client = FakeClient()
    client.files["fo01NOV2017bhav"] = make_zip("new_20261023.csv")  # wrong content for the date
    summary = run_backfill(
        cfg, layout, catalogue, client, TradingCalendar([D1], None, None), start=D1, end=D1
    )
    assert summary.parse_errors and summary.silver_written == 0 and silver_days(layout) == []
