# What: tests of the day scheduler using a simulated clock (a whole morning runs in a moment).
# In: a fake Fyers client, a simulated clock, small capture settings. Out: pass/fail.
"""Day runner behaviour."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from collector.config.schema import CaptureConfig
from collector.fyers.errors import AuthError
from collector.live.capture import ChainCollector
from collector.live.runner import RunOptions, RunSummary, run_day
from collector.live.status import read_status
from collector.live.targets import Target
from collector.store.layout import Layout
from tests.live.helpers import FakeClock, FakeFyers, capture_config, ist

MONDAY = date(2026, 10, 26)
TARGETS = [
    Target("NIFTY", "NSE:NIFTY50-INDEX", 1, 25, 2),
    Target("RELIANCE", "NSE:RELIANCE-EQ", 2, 10, 1),
]


def _run(
    tmp_path: Path,
    start: datetime,
    *,
    cfg: CaptureConfig | None = None,
    client: FakeFyers | None = None,
    options: RunOptions | None = None,
    today: date = MONDAY,
    check: Callable[[], bool | None] = lambda: True,
    before_open: Callable[[], None] | None = None,
    after_close: Callable[[], None] | None = None,
) -> tuple[RunSummary, Layout, FakeClock, FakeFyers]:
    cfg = cfg or capture_config()
    client = client or FakeFyers()
    layout = Layout(tmp_path / "data")
    clock = FakeClock(start)
    collector = ChainCollector(today, cfg, layout, clock, lambda: client, lambda: None)
    summary = run_day(
        cfg, collector, TARGETS, clock=clock, today=today, options=options or RunOptions(),
        check_market=check, before_open=before_open, after_close=after_close,
        status_path=layout.root / "live_status.json",
    )  # fmt: skip
    return summary, layout, clock, client


def _tier2_minutes(layout: Layout, day: date) -> list[int]:
    calls = pd.read_csv(layout.live_health_dir(day) / "calls.csv")
    stamps = pd.to_datetime(calls[calls["underlying"] == "RELIANCE"]["cycle_ts"].unique(), utc=True)
    return sorted({int(s.tz_convert("Asia/Kolkata").minute) for s in stamps})


def test_a_whole_morning_is_scheduled_on_the_grid(tmp_path: Path) -> None:
    called: list[str] = []
    summary, layout, clock, _ = _run(
        tmp_path, ist(2026, 10, 26, 8, 0), before_open=lambda: called.append("open"),
        after_close=lambda: called.append("close"),
    )  # fmt: skip
    assert summary.cycles == 31 and not summary.aborted  # 09:15 .. 09:45 every minute
    assert summary.reason == "capture window finished" and called == ["open", "close"]
    assert len(list((layout.root / "silver" / "option_chain").rglob("cycle_*.parquet"))) == 31
    assert _tier2_minutes(layout, MONDAY) == [15, 20, 25, 30, 35, 40, 45]  # stocks every 5 minutes
    status = read_status(layout.root / "live_status.json")
    assert status is not None and status["state"] == "finished" and status["cycles"] == 31
    assert clock.now() >= ist(2026, 10, 26, 9, 45)


def test_waits_for_login_time_then_for_the_open(tmp_path: Path) -> None:
    seen: list[datetime] = []
    clock_holder: dict[str, FakeClock] = {}

    def before_open() -> None:
        seen.append(clock_holder["c"].now())

    cfg = capture_config()
    client = FakeFyers()
    layout = Layout(tmp_path / "data")
    clock = FakeClock(ist(2026, 10, 26, 7, 0))
    clock_holder["c"] = clock
    collector = ChainCollector(MONDAY, cfg, layout, clock, lambda: client, lambda: None)
    run_day(cfg, collector, TARGETS, clock=clock, today=MONDAY, options=RunOptions(max_cycles=1),
            check_market=lambda: True, before_open=before_open)  # fmt: skip
    assert seen == [ist(2026, 10, 26, 8, 45)]
    first_call = pd.read_csv(layout.live_health_dir(MONDAY) / "cycles.csv")["cycle_ts"].iloc[0]
    assert str(first_call).startswith("2026-10-26 09:15:00")


def test_restart_mid_morning_joins_the_same_grid(tmp_path: Path) -> None:
    summary, layout, _, _ = _run(tmp_path, ist(2026, 10, 26, 9, 22, 30))
    first = pd.read_csv(layout.live_health_dir(MONDAY) / "cycles.csv")["cycle_ts"].iloc[0]
    assert str(first).startswith("2026-10-26 09:23:00")  # next slot on the minute grid
    assert summary.cycles == 23  # 09:23 .. 09:45
    assert _tier2_minutes(layout, MONDAY) == [25, 30, 35, 40, 45]  # same 5-minute phase as before


def test_weekend_holiday_and_late_start_end_the_run_quickly(tmp_path: Path) -> None:
    sat, _, _, client = _run(tmp_path, ist(2026, 10, 24, 8, 0), today=date(2026, 10, 24))
    assert sat.cycles == 0 and "weekend" in sat.reason and client.calls == []
    holiday_cfg = capture_config(holidays=[MONDAY])
    hol, _, _, _ = _run(tmp_path / "h", ist(2026, 10, 26, 8, 0), cfg=holiday_cfg)
    assert hol.cycles == 0 and "holiday" in hol.reason
    late, _, _, _ = _run(tmp_path / "l", ist(2026, 10, 26, 16, 0))
    assert late.cycles == 0 and "after the capture window" in late.reason


def test_a_market_with_no_candles_is_treated_as_closed_after_three_checks(tmp_path: Path) -> None:
    summary, _, _, client = _run(tmp_path, ist(2026, 10, 26, 8, 0), check=lambda: False)
    assert summary.cycles == 0 and "market closed" in summary.reason and client.calls == []
    unknown, _, _, _ = _run(tmp_path / "u", ist(2026, 10, 26, 8, 0), check=lambda: None)
    assert unknown.cycles == 31  # an unknown answer never stops the day


def test_one_false_check_followed_by_candles_still_runs(tmp_path: Path) -> None:
    answers = iter([False, True])
    summary, _, _, _ = _run(tmp_path, ist(2026, 10, 26, 8, 0), check=lambda: next(answers))
    assert summary.cycles == 30  # the 09:15 slot was spent on the check; 09:16 .. 09:45 ran


def test_slots_missed_by_a_slow_cycle_are_skipped_not_queued(tmp_path: Path) -> None:
    holder: dict[str, FakeClock] = {}

    def slow_once(n: int, data: dict[str, Any]) -> Any:
        if n == 5:
            holder["c"].advance(150)  # one call hangs for 2.5 minutes
        return None

    cfg = capture_config()
    client = FakeFyers(slow_once)
    layout = Layout(tmp_path / "data")
    clock = FakeClock(ist(2026, 10, 26, 9, 0))
    holder["c"] = clock
    collector = ChainCollector(MONDAY, cfg, layout, clock, lambda: client, lambda: None)
    summary = run_day(cfg, collector, TARGETS, clock=clock, today=MONDAY, options=RunOptions(),
                      check_market=lambda: True)  # fmt: skip
    # the stall ends about 09:17:33, so the 09:16 slot is skipped and the run resumes at 09:17
    assert summary.skipped_slots == 1 and summary.cycles == 30
    cycles = pd.read_csv(layout.live_health_dir(MONDAY) / "cycles.csv")
    assert int(cycles["skipped_slots"].sum()) == summary.skipped_slots


def test_repeated_empty_cycles_abort_the_run(tmp_path: Path) -> None:
    client = FakeFyers(lambda n, d: {"s": "error", "code": -300, "message": "down"})
    summary, layout, _, _ = _run(tmp_path, ist(2026, 10, 26, 8, 0), client=client)
    assert summary.aborted and summary.cycles == 3 and summary.reason == "too many empty cycles"
    status = read_status(layout.root / "live_status.json")
    assert status is not None and status["state"] == "stopped"


def test_a_failing_start_up_aborts_cleanly(tmp_path: Path) -> None:
    def broken() -> None:
        raise AuthError("login refused")

    summary, _, _, client = _run(tmp_path, ist(2026, 10, 26, 8, 0), before_open=broken)
    assert summary.aborted and summary.reason.startswith("start-up failed") and client.calls == []


def test_test_mode_runs_now_outside_market_hours_and_stops_at_the_limit(tmp_path: Path) -> None:
    sunday = ist(2026, 10, 25, 20, 0)
    summary, layout, clock, _ = _run(
        tmp_path,
        sunday,
        today=date(2026, 10, 25),
        options=RunOptions(ignore_hours=True, max_cycles=3),
    )
    assert summary.cycles == 3 and summary.reason == "reached the cycle limit"
    assert (clock.now() - sunday).total_seconds() < 400  # three cycles, about a minute apart


def test_a_broken_end_of_day_job_does_not_fail_the_day(tmp_path: Path) -> None:
    def boom() -> None:
        raise RuntimeError("eod broke")

    summary, _, _, _ = _run(tmp_path, ist(2026, 10, 26, 8, 0), after_close=boom)
    assert summary.cycles == 31 and not summary.aborted
