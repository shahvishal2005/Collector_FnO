# What: the F&O bhavcopy backfill job (download -> bronze -> parse -> silver), resumable and polite.
# In: config, storage layout, a download client, a calendar and run options (range, limit, flags).
# Out: bronze files, silver Parquet partitions, catalogue rows and a BackfillSummary.
"""F&O archive backfill.

Resume rules: a day whose silver file exists and whose downloads are all in the catalogue is
skipped. A 'not found' answer is remembered (holiday) unless `recheck_missing` is set. Raw files
are never overwritten with different content silently: a re-download replaces the catalogue row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

from collector.common.hashing import sha256_bytes
from collector.common.timeutil import now_ist
from collector.config.schema import AppConfig
from collector.normalise.fo_eod import FO_EOD_SCHEMA, ParseError, parse_fo_zip
from collector.nse.client import FetchResult, FetchStatus, NseError
from collector.nse.tradingdays import TradingCalendar
from collector.nse.urls import FoFormat, fo_filename, fo_url, formats_for_date
from collector.store.catalogue import Catalogue, CatalogueRow
from collector.store.layout import FO_DATASET, Layout
from collector.store.parquet import write_atomic_bytes, write_table

log = logging.getLogger(__name__)
_PROGRESS_EVERY = 25


class Fetcher(Protocol):
    """What the job needs from a download client."""

    def fetch_zip(self, url: str) -> FetchResult:
        """Download one URL."""


@dataclass
class BackfillSummary:
    """What a run did."""

    considered: int = 0
    downloaded: int = 0
    reused: int = 0
    no_file_days: int = 0
    silver_written: int = 0
    skipped_complete: int = 0
    parse_errors: list[str] = field(default_factory=list)
    network_errors: list[str] = field(default_factory=list)
    aborted: bool = False


def _load_or_fetch(
    day: date,
    fmt: FoFormat,
    cfg: AppConfig,
    layout: Layout,
    catalogue: Catalogue,
    client: Fetcher,
    recheck_missing: bool,
    summary: BackfillSummary,
    clock: datetime,
) -> bytes | None:
    """Return the raw zip bytes for a day and format, from disk or the network; None if no file."""
    existing = catalogue.get(FO_DATASET, day, fmt.value)
    name = fo_filename(fmt, day)
    path = layout.bronze_file(FO_DATASET, day, name)
    if existing is not None and existing.status == FetchStatus.OK.value and path.is_file():
        data = path.read_bytes()
        if existing.sha256 == sha256_bytes(data):
            summary.reused += 1
            return data
        log.warning("%s: bronze file checksum differs from the catalogue; downloading again", name)
    elif (
        existing is not None
        and existing.status == FetchStatus.NOT_FOUND.value
        and not recheck_missing
    ):
        return None
    url = fo_url(cfg.nse.archive_base_url, fmt, day)
    result = client.fetch_zip(url)
    summary.downloaded += 1
    if result.status is FetchStatus.NOT_FOUND or result.content is None:
        catalogue.record(
            CatalogueRow(FO_DATASET, day, fmt.value, "not_found", url, result.http_status,
                         clock.isoformat(), None, None, None)
        )  # fmt: skip
        return None
    write_atomic_bytes(path, result.content)
    catalogue.record(
        CatalogueRow(FO_DATASET, day, fmt.value, "ok", url, result.http_status, clock.isoformat(),
                     len(result.content), sha256_bytes(result.content), str(path))
    )  # fmt: skip
    return result.content


def run_backfill(
    cfg: AppConfig,
    layout: Layout,
    catalogue: Catalogue,
    client: Fetcher,
    calendar: TradingCalendar,
    *,
    start: date,
    end: date,
    limit: int | None = None,
    recheck_missing: bool = False,
    reprocess: bool = False,
) -> BackfillSummary:
    """Process every candidate day in [start, end]; stop early on `limit` or repeated errors."""
    summary = BackfillSummary()
    consecutive_errors = 0
    days = [d for d in calendar.candidates if start <= d <= end]
    log.info("backfill: %d candidate days between %s and %s", len(days), start, end)
    attempted = 0
    for day in days:
        formats = formats_for_date(day, cfg.fo_bhavcopy)
        silver = layout.fo_silver_file(day)
        complete = all(catalogue.get(FO_DATASET, day, f.value) is not None for f in formats)
        if complete and silver.is_file() and not reprocess:
            summary.skipped_complete += 1
            continue
        if complete and not silver.is_file() and not reprocess:
            only_missing = all(
                (row := catalogue.get(FO_DATASET, day, f.value)) is not None
                and row.status == "not_found"
                for f in formats
            )
            if only_missing and not recheck_missing:
                summary.skipped_complete += 1
                continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        summary.considered += 1
        clock = now_ist()
        try:
            contents = {
                fmt: _load_or_fetch(
                    day, fmt, cfg, layout, catalogue, client, recheck_missing, summary, clock
                )
                for fmt in formats
            }
        except NseError as exc:
            consecutive_errors += 1
            summary.network_errors.append(f"{day}: {exc}")
            log.error("%s: %s", day, exc)
            if consecutive_errors >= cfg.nse.abort_after_consecutive_errors:
                log.error("aborting after %d consecutive errors", consecutive_errors)
                summary.aborted = True
                break
            continue
        consecutive_errors = 0
        primary = next(((fmt, data) for fmt, data in contents.items() if data is not None), None)
        if primary is None:
            summary.no_file_days += 1
            continue
        fmt, data = primary
        try:
            frame = parse_fo_zip(data, fmt.value, day, fo_filename(fmt, day), clock)
        except ParseError as exc:
            summary.parse_errors.append(f"{day}: {exc}")
            log.error("%s: parse error: %s", day, exc)
            continue
        write_table(frame, FO_EOD_SCHEMA, silver)
        summary.silver_written += 1
        if summary.considered % _PROGRESS_EVERY == 0:
            log.info(
                "progress: %d days processed (last %s), %d silver files written",
                summary.considered, day, summary.silver_written,
            )  # fmt: skip
    return summary
