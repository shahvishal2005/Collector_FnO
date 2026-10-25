# What: decide whether a day's live capture looks healthy, from its health records.
# In: the cycle and call tables, the run state, the time and the capture settings.
# Out: a Verdict listing what is wrong (an empty list means healthy).
"""Health verdict for the live capture.

The expected number of cycles is measured from the first recorded cycle to the last one (or to
now while the run is still going), so a short test run or a deliberate late start is not reported
as 'missing cycles'. A late start is reported on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

from collector.common.timeutil import IST
from collector.config.schema import CaptureConfig

_SLACK_CYCLES = 3
_MIN_SHARE = 0.9
_MAX_FAILED_SHARE = 0.05


@dataclass(frozen=True)
class Verdict:
    """The outcome: counts and a list of problems."""

    expected: int
    recorded: int
    problems: list[str]

    @property
    def healthy(self) -> bool:
        """True when nothing is wrong."""
        return not self.problems


def judge_day(
    cycles: pd.DataFrame,
    calls: pd.DataFrame,
    *,
    state: str,
    now: datetime,
    cap: CaptureConfig,
    day: date,
    real_day: bool,
) -> Verdict:
    """Look for missing cycles, many failed calls, a stall, a late start or an early stop."""
    interval = timedelta(seconds=cap.tier1_interval_seconds)
    stamps = pd.to_datetime(cycles["cycle_ts"], utc=True).dt.tz_convert(IST)
    first, last = stamps.min().to_pydatetime(), stamps.max().to_pydatetime()
    end = now if state == "running" else last
    expected = max(1, int((end - first) // interval) + 1)
    recorded = len(cycles)
    problems: list[str] = []
    if recorded < _MIN_SHARE * expected:
        problems.append(f"missing cycles: {recorded} recorded, about {expected} expected")
    failed = int((~calls["ok"]).sum())
    if failed > _MAX_FAILED_SHARE * max(1, len(calls)):
        problems.append(f"many failed calls: {failed} of {len(calls)}")
    if state == "running" and now - last > _SLACK_CYCLES * interval:
        minutes = int((now - last).total_seconds() // 60)
        problems.append(f"stalled: no cycle for {minutes} minutes while the run says 'running'")
    if real_day:
        start = datetime.combine(day, cap.capture_start, tzinfo=IST)
        if first - start > _SLACK_CYCLES * interval:
            problems.append(
                f"late start: first cycle at {first:%H:%M} (window opens {start:%H:%M})"
            )
    if state == "stopped":
        problems.append("the run stopped early (aborted); Task Scheduler should restart it")
    return Verdict(expected, recorded, problems)
