# What: a polite HTTP client for the NSE public archive (one connection, rate limited, retries).
# In: a URL. Out: a FetchResult (OK with the zip bytes, or NOT_FOUND); errors raise NseError.
"""HTTP client for NSE archive downloads.

A 404 is normal (holiday or weekend) and returned as NOT_FOUND. A 200 that is not a zip file means
the server sent a block or error page, so it raises instead of being mistaken for a holiday.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import StrEnum

import requests

from collector.common.ratelimit import RateLimiter
from collector.common.retry import retry_call
from collector.config.schema import NseConfig

log = logging.getLogger(__name__)

_ZIP_MAGIC = b"PK\x03\x04"
_RETRYABLE_STATUS = {403, 408, 429, 500, 502, 503, 504}


class NseError(Exception):
    """A download failed in a way that is not a plain 'file not found'."""


class _Retryable(NseError):
    """A temporary failure worth retrying (network error, 429, 5xx, ...)."""


class UnexpectedContent(NseError):
    """The server answered 200 but the body is not a zip file (block page or error page)."""


class FetchStatus(StrEnum):
    """Outcome of a download attempt that did not raise."""

    OK = "ok"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class FetchResult:
    """What came back: the status, the HTTP code and the body (only for OK)."""

    status: FetchStatus
    http_status: int
    content: bytes | None


class NseClient:
    """Downloads zip files from the NSE archive, one request at a time."""

    def __init__(
        self,
        cfg: NseConfig,
        session: requests.Session | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        """Keep the settings; build a session and a limiter unless they are supplied."""
        self._cfg = cfg
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": cfg.user_agent, "Accept": "*/*"})
        self._limiter = limiter or RateLimiter(cfg.min_interval_seconds)

    def fetch_zip(self, url: str) -> FetchResult:
        """Download one URL with retries; return OK, NOT_FOUND, or raise NseError."""
        return retry_call(
            lambda: self._once(url),
            attempts=self._cfg.max_attempts,
            base_delay=self._cfg.backoff_base_seconds,
            max_delay=self._cfg.backoff_max_seconds,
            retry_on=(_Retryable,),
        )

    def _once(self, url: str) -> FetchResult:
        """One request. Maps the response to a result or an exception."""
        self._limiter.wait()
        try:
            response = self._session.get(url, timeout=self._cfg.timeout_seconds)
        except requests.RequestException as exc:
            raise _Retryable(f"network error for {url}: {exc}") from exc
        code = response.status_code
        if code == 404:
            return FetchResult(FetchStatus.NOT_FOUND, code, None)
        if code in _RETRYABLE_STATUS:
            raise _Retryable(f"HTTP {code} for {url}")
        if code != 200:
            raise NseError(f"unexpected HTTP {code} for {url}")
        body = response.content
        if not body.startswith(_ZIP_MAGIC):
            raise UnexpectedContent(f"HTTP 200 but not a zip file for {url} ({len(body)} bytes)")
        return FetchResult(FetchStatus.OK, code, body)
