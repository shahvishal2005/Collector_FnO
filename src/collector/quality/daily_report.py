# What: build the quality report of one daily dataset (coverage, issues) from its stored files.
# In: config, layout, catalogue, calendar and a DailyDataset. Out: CSV files and a Markdown summary.
"""Generic report for the M3 datasets. Re-reads the stored data, so it can be run any time."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from collector.config.schema import AppConfig
from collector.datasets.base import DailyDataset
from collector.nse.tradingdays import TradingCalendar
from collector.quality.coverage import analyse_coverage
from collector.quality.fo_checks import ERROR, WARN, Issue, check_row_count_jumps
from collector.quality.report import _md_table
from collector.store.catalogue import Catalogue
from collector.store.dataset_manifest import dataset_days
from collector.store.layout import Layout
from collector.store.parquet import read_table


@dataclass(frozen=True)
class DatasetReport:
    """Headline numbers of a report run."""

    name: str
    days_with_data: int
    errors: int
    warnings: int
    missing_days: int
    extra_days: int


def build_dataset_report(
    cfg: AppConfig,
    layout: Layout,
    catalogue: Catalogue,
    calendar: TradingCalendar,
    dataset: DailyDataset,
) -> DatasetReport:
    """Run the dataset's checks over every stored day and write the report files."""
    layout.reports_root.mkdir(parents=True, exist_ok=True)
    days = dataset_days(layout, dataset.name)
    issues: list[Issue] = []
    rows_by_day: dict[date, int] = {}
    for day in days:
        frame = read_table(layout.dataset_silver_file(dataset.name, day))
        rows_by_day[day] = len(frame)
        issues.extend(dataset.check(frame, day))
    if dataset.row_count_jump_check:
        issues.extend(check_row_count_jumps(rows_by_day, cfg.backfill.row_count_change_ratio))
    coverage = analyse_coverage(
        set(days), calendar.known_trading_days, calendar.known_until, cfg.backfill.start_date
    )
    prefix = layout.reports_root / dataset.name
    pd.DataFrame(
        [(i.trade_date, i.check, i.severity, i.count, i.detail) for i in issues],
        columns=["trade_date", "check", "severity", "count", "detail"],
    ).to_csv(f"{prefix}_issues.csv", index=False)
    coverage.table.to_csv(f"{prefix}_coverage.csv", index=False)
    pd.DataFrame(
        [{"trade_date": d, "missing": "missing"} for d in coverage.missing]
        + [{"trade_date": d, "missing": "extra"} for d in coverage.extra],
        columns=["trade_date", "missing"],
    ).to_csv(f"{prefix}_missing_extra_days.csv", index=False)
    errors = sum(1 for i in issues if i.severity == ERROR)
    warnings = sum(1 for i in issues if i.severity == WARN)
    rows = catalogue.rows(dataset.name)
    ok = sum(1 for r in rows if r.status == "ok")
    not_found = sum(1 for r in rows if r.status == "not_found")
    lines = [
        f"# {dataset.name}: quality report",
        "",
        dataset.description,
        "",
        f"Days with data: **{len(days)}** | catalogue: {ok} files downloaded, {not_found} 'not found'",
        f"Issues: **{errors} errors**, {warnings} warnings, {len(issues) - errors - warnings} info",
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
    if issues:
        table = pd.DataFrame(
            [(i.severity, i.check, i.count) for i in issues], columns=["severity", "check", "count"]
        )
        summary = table.groupby(["severity", "check"])["count"].agg(["size", "sum"]).reset_index()
        summary.columns = pd.Index(["severity", "check", "days", "rows_or_value"])
        lines += ["## Issues by type", "", _md_table(summary), ""]
    else:
        lines += ["## Issues", "", "None.", ""]
    (layout.reports_root / f"{dataset.name}_report.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )
    return DatasetReport(
        dataset.name, len(days), errors, warnings, len(coverage.missing), len(coverage.extra)
    )
