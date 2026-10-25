# What: tests for the live-capture health verdict (missing cycles, stalls, late starts, failures).
# In: small synthetic health tables. Out: pass/fail.
"""Verdict tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from collector.live.verdict import judge_day
from tests.live.helpers import capture_config, ist

DAY = date(2026, 10, 26)
CAP = capture_config()


def _cycles(first: datetime, count: int, gap_every: int = 0) -> pd.DataFrame:
    stamps = []
    for index in range(count):
        if gap_every and index and index % gap_every == 0:
            first += timedelta(minutes=5)  # a gap of five missing slots
        stamps.append((first + timedelta(minutes=index)).isoformat())
    return pd.DataFrame({"cycle_ts": stamps})


def _calls(ok: int, failed: int = 0) -> pd.DataFrame:
    return pd.DataFrame({"ok": [True] * ok + [False] * failed})


def _judge(cycles: pd.DataFrame, calls: pd.DataFrame, state: str, now: datetime, real: bool = True):  # type: ignore[no-untyped-def]
    return judge_day(cycles, calls, state=state, now=now, cap=CAP, day=DAY, real_day=real)


def test_a_clean_finished_day_is_healthy() -> None:
    verdict = _judge(
        _cycles(ist(2026, 10, 26, 9, 15), 31), _calls(300), "finished", ist(2026, 10, 26, 16, 0)
    )
    assert verdict.healthy and verdict.expected == 31 and verdict.recorded == 31


def test_a_short_test_run_is_not_reported_as_missing_cycles() -> None:
    sunday_noon = ist(2026, 10, 25, 12, 0)
    verdict = _judge(
        _cycles(sunday_noon, 2), _calls(70), "finished", ist(2026, 10, 25, 20, 0), real=False
    )
    assert verdict.healthy  # compared with its own span, not with a full trading day


def test_gaps_inside_the_run_are_reported() -> None:
    verdict = _judge(
        _cycles(ist(2026, 10, 26, 9, 15), 20, gap_every=5),
        _calls(200),
        "finished",
        ist(2026, 10, 26, 16, 0),
    )
    assert any("missing cycles" in p for p in verdict.problems)


def test_a_running_but_silent_collector_is_flagged_as_stalled() -> None:
    cycles = _cycles(ist(2026, 10, 26, 9, 15), 10)  # last cycle 09:24
    verdict = _judge(cycles, _calls(100), "running", ist(2026, 10, 26, 9, 40))
    assert any("stalled" in p for p in verdict.problems)


def test_late_start_failures_and_early_stop_are_flagged() -> None:
    late = _judge(
        _cycles(ist(2026, 10, 26, 9, 40), 5), _calls(50), "finished", ist(2026, 10, 26, 16, 0)
    )
    assert any("late start" in p for p in late.problems)
    failing = _judge(
        _cycles(ist(2026, 10, 26, 9, 15), 10), _calls(80, 20), "finished", ist(2026, 10, 26, 16, 0)
    )
    assert any("failed calls" in p for p in failing.problems)
    stopped = _judge(
        _cycles(ist(2026, 10, 26, 9, 15), 10), _calls(100), "stopped", ist(2026, 10, 26, 16, 0)
    )
    assert any("stopped early" in p for p in stopped.problems)
