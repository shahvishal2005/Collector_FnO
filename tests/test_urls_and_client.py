# What: tests for NSE URL building, format selection and the polite download client.
# In: a fake HTTP session. Out: pass/fail.
"""URLs and client."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest
import requests

from collector.common.ratelimit import RateLimiter
from collector.config.schema import AppConfig
from collector.nse.client import FetchStatus, NseClient, NseError, UnexpectedContent
from collector.nse.urls import FoFormat, fo_filename, fo_url, formats_for_date
from tests.conftest import make_config, make_zip


def test_old_and_new_urls() -> None:
    day = date(2017, 11, 1)
    assert fo_filename(FoFormat.OLD, day) == "fo01NOV2017bhav.csv.zip"
    assert fo_url("https://x.test/", FoFormat.OLD, day) == (
        "https://x.test/content/historical/DERIVATIVES/2017/NOV/fo01NOV2017bhav.csv.zip"
    )
    assert (
        fo_filename(FoFormat.NEW, date(2026, 10, 23))
        == "BhavCopy_NSE_FO_0_0_0_20261023_F_0000.csv.zip"
    )
    assert fo_url("https://x.test", FoFormat.NEW, date(2026, 10, 23)).endswith(
        "/content/fo/BhavCopy_NSE_FO_0_0_0_20261023_F_0000.csv.zip"
    )


def test_format_selection(cfg: AppConfig) -> None:
    assert formats_for_date(date(2020, 1, 2), cfg.fo_bhavcopy) == [FoFormat.OLD]
    assert formats_for_date(date(2024, 7, 2), cfg.fo_bhavcopy) == [FoFormat.OLD]
    assert formats_for_date(date(2024, 7, 3), cfg.fo_bhavcopy) == [FoFormat.OLD, FoFormat.NEW]
    assert formats_for_date(date(2024, 7, 5), cfg.fo_bhavcopy) == [FoFormat.OLD, FoFormat.NEW]
    assert formats_for_date(date(2024, 7, 8), cfg.fo_bhavcopy) == [FoFormat.NEW]
    assert formats_for_date(date(2026, 10, 23), cfg.fo_bhavcopy) == [FoFormat.NEW]


class FakeResponse:
    """Just enough of requests.Response."""

    def __init__(
        self, status_code: int, content: bytes = b"", on_chunk: Callable[[], None] | None = None
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.closed = False
        self._on_chunk = on_chunk

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        """Yield the body in 10-byte pieces; `on_chunk` lets a test make time pass."""
        for start in range(0, len(self.content), 10):
            if self._on_chunk:
                self._on_chunk()
            yield self.content[start : start + 10]

    def close(self) -> None:
        self.closed = True


class FakeSession:
    """Plays back a list of responses (or exceptions) and records the calls."""

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url: str, timeout: float, stream: bool = False) -> FakeResponse:
        self.calls.append(url)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, FakeResponse)
        return item


def _client(tmp_path: Path, script: list[object]) -> tuple[NseClient, FakeSession]:
    cfg = make_config(tmp_path)
    session = FakeSession(script)
    return NseClient(cfg.nse, session=session, limiter=RateLimiter(0.0)), session  # type: ignore[arg-type]


def test_ok_and_not_found(tmp_path: Path) -> None:
    body = make_zip("old_20171101.csv")
    client, session = _client(tmp_path, [FakeResponse(200, body), FakeResponse(404, b"<html>")])
    ok = client.fetch_zip("u1")
    assert ok.status is FetchStatus.OK and ok.content == body
    missing = client.fetch_zip("u2")
    assert missing.status is FetchStatus.NOT_FOUND and missing.content is None
    assert session.headers["User-Agent"] == "test-agent"


def test_server_error_is_retried_then_succeeds(tmp_path: Path) -> None:
    body = make_zip("old_20171101.csv")
    client, session = _client(tmp_path, [FakeResponse(503), FakeResponse(200, body)])
    assert client.fetch_zip("u").status is FetchStatus.OK
    assert len(session.calls) == 2


def test_network_error_gives_up_after_max_attempts(tmp_path: Path) -> None:
    client, session = _client(tmp_path, [requests.ConnectionError("down")] * 2)
    with pytest.raises(NseError):
        client.fetch_zip("u")
    assert len(session.calls) == 2


def test_200_html_is_not_mistaken_for_a_holiday(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, [FakeResponse(200, b"<html>blocked</html>")])
    with pytest.raises(UnexpectedContent):
        client.fetch_zip("u")


def test_unexpected_status_raises(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, [FakeResponse(401)])
    with pytest.raises(NseError):
        client.fetch_zip("u")


def test_a_stalled_download_is_cut_off_and_retried(tmp_path: Path) -> None:
    """A response that keeps trickling in past the total time limit is abandoned, then retried."""
    body = make_zip("old_20171101.csv")
    now = [0.0]

    def slow() -> None:
        now[0] += 10.0  # every piece takes 10 s; the test config allows 30 s in total

    slow_response = FakeResponse(200, body, on_chunk=slow)
    good = FakeResponse(200, body)
    cfg = make_config(tmp_path)
    session = FakeSession([slow_response, good])
    client = NseClient(
        cfg.nse, session=session, limiter=RateLimiter(0.0), clock=lambda: now[0]  # type: ignore[arg-type]
    )
    result = client.fetch_zip("u")
    assert result.status is FetchStatus.OK and result.content == body
    assert slow_response.closed and len(session.calls) == 2
