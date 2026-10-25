# What: the generic backfill job for daily file datasets (download -> bronze -> parse -> silver), resumable.
# In: config, storage layout, catalogue, a download client, a calendar, a DailyDataset and run options.
# Out: raw files in bronze, one Parquet partition per day in silver, catalogue rows, a BackfillSummary.
"""Generic daily-file backfill.

Same rules as the F&O backfill: a day whose silver file exists and whose download is in the
catalogue is skipped; a 'not found' answer (holiday) is remembered unless `recheck_missing`;
raw files are kept exactly as served; a damaged or unexpected file is a parse error for that day,
never a crash. The catalogue key is (dataset name, day, 'file').
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Protocol

from collector.common.hashing import sha256_bytes
from collector.common.timeutil import now_ist
from collector.config.schema import AppConfig
from collector.datasets.base import DailyDataset
from collector.jobs.backfill_fo import BackfillSummary
from collector.normalise.fo_eod import ParseError
from collector.nse.client import FetchResult, FetchStatus, NseError
from collector.nse.tradingdays import TradingCalendar
from collector.store.catalogue import Catalogue, CatalogueRow
from collector.store.layout import Layout
from collector.store.parquet import write_atomic_bytes, write_table

log = logging.getLogger(__name__)
_FORMAT = "file"
_PROGRESS_EVERY = 100


class Fetcher(Protocol):
    """What the job needs from a download client."""

    def fetch_file(self, url: str, kind: str = "zip") -> FetchResult:
        """Download one URL."""


def _load_or_fetch(
    day: date,
    dataset: DailyDataset,
    cfg: AppConfig,
    layout: Layout,
    catalogue: Catalogue,
    client: Fetcher,
    recheck_missing: bool,
    summary: BackfillSummary,
    clock: datetime,
) -> bytes | None:
    """The raw bytes for a day, from disk or the network; None when NSE has no file."""
    existing = catalogue.get(dataset.name, day, _FORMAT)
    name = dataset.file_name(day)
    path = layout.bronze_file(dataset.name, day, name)
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
    url = dataset.url(cfg.nse.archive_base_url, day)
    result = client.fetch_file(url, dataset.kind)
    summary.downloaded += 1
    if result.status is FetchStatus.NOT_FOUND or result.content is None:
        catalogue.record(
            CatalogueRow(dataset.name, day, _FORMAT, "not_found", url, result.http_status,
                         clock.isoformat(), None, None, None)
        )  # fmt: skip
        return None
    write_atomic_bytes(path, result.content)
    catalogue.record(
        CatalogueRow(dataset.name, day, _FORMAT, "ok", url, result.http_status, clock.isoformat(),
                     len(result.content), sha256_bytes(result.content), str(path))
    )  # fmt: skip
    return result.content


def run_dataset_backfill(
    cfg: AppConfig,
    layout: Layout,
    catalogue: Catalogue,
    client: Fetcher,
    calendar: TradingCalendar,
    dataset: DailyDataset,
    *,
    start: date,
    end: date,
    limit: int | None = None,
    recheck_missing: bool = False,
    reprocess: bool = False,
) -> BackfillSummary:
    """Process every candidate day of one dataset in [start, end]."""
    summary = BackfillSummary()
    consecutive_errors = 0
    days = [d for d in calendar.candidates if start <= d <= end]
    log.info("%s: %d candidate days between %s and %s", dataset.name, len(days), start, end)
    attempted = 0
    for day in days:
        silver = layout.dataset_silver_file(dataset.name, day)
        known = catalogue.get(dataset.name, day, _FORMAT)
        if known is not None and not reprocess:
            if silver.is_file() or (known.status == "not_found" and not recheck_missing):
                summary.skipped_complete += 1
                continue
        if limit is not None and attempted >= limit:
            break
        attempted += 1
        summary.considered += 1
        clock = now_ist()
        try:
            data = _load_or_fetch(
                day, dataset, cfg, layout, catalogue, client, recheck_missing, summary, clock
            )
        except NseError as exc:
            consecutive_errors += 1
            summary.network_errors.append(f"{day}: {exc}")
            log.error("%s %s: %s", dataset.name, day, exc)
            if consecutive_errors >= cfg.nse.abort_after_consecutive_errors:
                log.error("aborting after %d consecutive errors", consecutive_errors)
                summary.aborted = True
                break
            continue
        consecutive_errors = 0
        if data is None:
            summary.no_file_days += 1
            continue
        try:
            frame = dataset.parse(data, day, dataset.file_name(day), clock)
        except ParseError as exc:
            summary.parse_errors.append(f"{day}: {exc}")
            log.error("%s %s: parse error: %s", dataset.name, day, exc)
            continue
        write_table(frame, dataset.schema, silver)
        summary.silver_written += 1
        if summary.considered % _PROGRESS_EVERY == 0:
            log.info(
                "%s progress: %d days processed (last %s), %d files written",
                dataset.name, summary.considered, day, summary.silver_written,
            )  # fmt: skip
    return summary
