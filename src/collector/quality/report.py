# What: build the F&O backfill quality report (coverage, issues, format-overlap agreement).
# In: config, layout, catalogue and the trading calendar. Out: CSV files and a Markdown summary.
"""Report generation. Re-reads the stored data, so it can be run at any time."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from collector.config.schema import AppConfig
from collector.normalise.fo_eod import ParseError, parse_fo_zip
from collector.nse.tradingdays import TradingCalendar
from collector.nse.urls import FoFormat, fo_filename, formats_for_date
from collector.quality.coverage import Coverage, analyse_coverage
from collector.quality.fo_checks import (
    ERROR,
    WARN,
    Issue,
    OverlapResult,
    check_day,
    check_row_count_jumps,
    compare_formats,
)
from collector.store.catalogue import Catalogue
from collector.store.layout import FO_DATASET, Layout
from collector.store.manifest import silver_days
from collector.store.parquet import read_table

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportResult:
    """Headline numbers of a report run."""

    days_with_data: int
    errors: int
    warnings: int
    missing_days: int
    overlap_days: int
    overlap_identical: int


def _md_table(frame: pd.DataFrame) -> str:
    """A GitHub-style Markdown table (no extra dependency needed)."""
    header = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    divider = "| " + " | ".join("---" for _ in frame.columns) + " |"
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([header, divider, *body])


def _overlap_results(cfg: AppConfig, layout: Layout, days: list[date]) -> list[OverlapResult]:
    """Compare old and new format on every day that was downloaded in both."""
    results: list[OverlapResult] = []
    for day in days:
        formats = formats_for_date(day, cfg.fo_bhavcopy)
        if len(formats) < 2:
            continue
        frames = {}
        for fmt in formats:
            path = layout.bronze_file(FO_DATASET, day, fo_filename(fmt, day))
            if not path.is_file():
                break
            try:
                frames[fmt] = parse_fo_zip(
                    path.read_bytes(),
                    fmt.value,
                    day,
                    path.name,
                    pd.Timestamp.now(tz="Asia/Kolkata"),
                )
            except ParseError as exc:
                log.error("%s (%s): %s", day, fmt.value, exc)
                break
        if FoFormat.OLD in frames and FoFormat.NEW in frames:
            results.append(compare_formats(frames[FoFormat.OLD], frames[FoFormat.NEW], day))
    return results


def build_report(
    cfg: AppConfig, layout: Layout, catalogue: Catalogue, calendar: TradingCalendar
) -> ReportResult:
    """Run every check over the stored data and write the report files under data/reports."""
    layout.reports_root.mkdir(parents=True, exist_ok=True)
    days = silver_days(layout)
    issues: list[Issue] = []
    rows_by_day: dict[date, int] = {}
    for day in days:
        frame = read_table(layout.fo_silver_file(day))
        rows_by_day[day] = len(frame)
        issues.extend(check_day(frame, day, cfg.backfill.min_expected_underlyings))
    issues.extend(check_row_count_jumps(rows_by_day, cfg.backfill.row_count_change_ratio))

    coverage: Coverage = analyse_coverage(
        set(days), calendar.known_trading_days, calendar.known_until, cfg.backfill.start_date
    )
    overlap = _overlap_results(
        cfg,
        layout,
        [
            d
            for d in calendar.candidates
            if cfg.fo_bhavcopy.overlap_start <= d < cfg.fo_bhavcopy.new_format_start
        ],
    )

    issue_frame = pd.DataFrame(
        [(i.trade_date, i.check, i.severity, i.count, i.detail) for i in issues],
        columns=["trade_date", "check", "severity", "count", "detail"],
    )
    issue_frame.to_csv(layout.reports_root / "fo_eod_issues.csv", index=False)
    coverage.table.to_csv(layout.reports_root / "fo_eod_coverage.csv", index=False)
    pd.DataFrame(
        [{"trade_date": d, "missing": "missing"} for d in coverage.missing]
        + [{"trade_date": d, "missing": "extra"} for d in coverage.extra],
        columns=["trade_date", "missing"],
    ).to_csv(layout.reports_root / "fo_eod_missing_extra_days.csv", index=False)
    overlap_frame = pd.DataFrame(
        [
            {
                "trade_date": r.trade_date, "rows_old": r.rows_old, "rows_new": r.rows_new,
                "matched": r.matched_rows, "only_old": r.only_old, "only_new": r.only_new,
                "identical": r.identical, **{f"mismatch_{k}": v for k, v in r.mismatches.items()},
            }
            for r in overlap
        ]
    )  # fmt: skip
    overlap_frame.to_csv(layout.reports_root / "fo_overlap_compare.csv", index=False)

    errors = sum(1 for i in issues if i.severity == ERROR)
    warnings = sum(1 for i in issues if i.severity == WARN)
    result = ReportResult(
        len(days),
        errors,
        warnings,
        len(coverage.missing),
        len(overlap),
        sum(1 for r in overlap if r.identical),
    )
    _write_markdown(cfg, layout, calendar, coverage, issue_frame, overlap, result, catalogue)
    return result


def _write_markdown(
    cfg: AppConfig,
    layout: Layout,
    calendar: TradingCalendar,
    coverage: Coverage,
    issues: pd.DataFrame,
    overlap: list[OverlapResult],
    result: ReportResult,
    catalogue: Catalogue,
) -> None:
    """Write the human-readable summary."""
    rows = catalogue.rows(FO_DATASET)
    ok = sum(1 for r in rows if r.status == "ok")
    not_found = sum(1 for r in rows if r.status == "not_found")
    lines = [
        "# F&O bhavcopy backfill: quality report",
        "",
        f"Range: {cfg.backfill.start_date} to {cfg.backfill.end_date or 'yesterday'}",
        f"Days with data: **{result.days_with_data}** | catalogue: {ok} files downloaded,"
        f" {not_found} 'not found' answers",
        f"Issues: **{result.errors} errors**, {result.warnings} warnings",
        "",
        "## Coverage by year",
        "",
        _md_table(coverage.table) if not coverage.table.empty else "(no data)",
        "",
    ]
    if coverage.judged_until is None:
        lines += ["Coverage could not be judged: no Nifty candle folder configured or found.", ""]
    else:
        lines += [
            f"Judged against Nifty trading days until {coverage.judged_until}.",
            f"Missing (market open, no file): **{len(coverage.missing)}**"
            + (
                f" e.g. {', '.join(str(d) for d in coverage.missing[:10])}"
                if coverage.missing
                else ""
            ),
            f"Extra (file exists, no Nifty session): **{len(coverage.extra)}**"
            + (f" e.g. {', '.join(str(d) for d in coverage.extra[:10])}" if coverage.extra else ""),
            "",
        ]
    lines += [
        "## Old vs new format on overlap days",
        "",
        f"{result.overlap_identical} of {result.overlap_days} overlap days identical"
        " (turnover compared to Rs 1,000 because the old file rounds to 0.01 lakh).",
        "",
    ]
    if not issues.empty:
        summary = issues.groupby(["severity", "check"])["count"].agg(["size", "sum"]).reset_index()
        summary.columns = pd.Index(["severity", "check", "days", "rows_or_value"])
        lines += ["## Issues by type", "", _md_table(summary), ""]
    else:
        lines += ["## Issues", "", "None.", ""]
    (layout.reports_root / "fo_eod_report.md").write_text("\n".join(lines), encoding="utf-8")
