# What: run a trading day of live capture: wait, log in, then one cycle per slot to the close.
# In: capture settings, a ChainCollector, the targets, a clock and hooks (login, market check).
# Out: capture files (via the collector), a status file, and a RunSummary saying how the day went.
"""Day scheduler (designed to run unattended on the VPS).

Behaviour that matters in practice:
- It can be started at any time: before the open it waits; after a restart mid-day it joins the
  next slot on the same time grid, so Tier 2 timing stays consistent; after the close it exits.
- Slots missed because a cycle ran long are skipped (and counted), never queued up.
- A weekend or a configured holiday ends the run at once; a weekday where the spot has no candles
  at the open (checked up to three times) is treated as a market holiday.
- Repeated empty cycles abort the run with exit code 1 so Windows Task Scheduler restarts it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from collector.common.timeutil import IST
from collector.config.schema import CaptureConfig
from collector.live.capture import ChainCollector
from collector.live.clock import Clock
from collector.live.status import Status, write_status
from collector.live.targets import Target

log = logging.getLogger(__name__)
_MARKET_CHECKS = 3


@dataclass
class RunOptions:
    """Switches for testing: run outside market hours, or stop after a few cycles."""

    ignore_hours: bool = False
    max_cycles: int | None = None


@dataclass
class RunSummary:
    """How the day went."""

    cycles: int = 0
    ok_calls: int = 0
    failed_calls: int = 0
    rows: int = 0
    skipped_slots: int = 0
    reason: str = ""
    aborted: bool = False


def _sleep_until(clock: Clock, moment: datetime) -> None:
    """Wait until `moment` (returns at once if it has already passed)."""
    remaining = (moment - clock.now()).total_seconds()
    if remaining > 0:
        clock.sleep(remaining)


def run_day(
    cfg: CaptureConfig,
    collector: ChainCollector,
    targets: list[Target],
    *,
    clock: Clock,
    today: date,
    options: RunOptions,
    check_market: Callable[[], bool | None],
    before_open: Callable[[], None] | None = None,
    after_close: Callable[[], None] | None = None,
    status_path: Path | None = None,
) -> RunSummary:
    """Run one trading day. Never raises for a failed cycle; returns a summary."""
    summary = RunSummary()
    status = Status(day=today.isoformat(), state="waiting")

    def publish(state: str, last: datetime | None = None) -> None:
        status.state = state
        status.cycles, status.ok_calls = summary.cycles, summary.ok_calls
        status.failed_calls, status.rows = summary.failed_calls, summary.rows
        status.skipped_slots, status.reason = summary.skipped_slots, summary.reason
        if last is not None:
            status.last_cycle_ts = last.isoformat()
        if status_path is not None:
            write_status(status_path, status, clock.now())

    start_dt = datetime.combine(today, cfg.capture_start, tzinfo=IST)
    end_dt = datetime.combine(today, cfg.capture_end, tzinfo=IST)
    login_dt = datetime.combine(today, cfg.login_time, tzinfo=IST)
    interval = timedelta(seconds=cfg.tier1_interval_seconds)
    ratio = cfg.tier2_interval_seconds // cfg.tier1_interval_seconds
    tier1 = [t for t in targets if t.tier == 1]
    tier2 = [t for t in targets if t.tier != 1]

    if not options.ignore_hours:
        if today.weekday() >= 5 or today in cfg.holidays:
            summary.reason = "weekend or configured holiday"
            publish("finished")
            return summary
        if clock.now() >= end_dt:
            summary.reason = "started after the capture window"
            publish("finished")
            return summary
        publish("waiting")
        _sleep_until(clock, login_dt)

    if before_open is not None:
        try:
            before_open()
        except Exception as exc:  # login failures and similar must end the run clearly
            log.error("start-up failed: %s: %s", type(exc).__name__, exc)
            summary.reason, summary.aborted = f"start-up failed ({type(exc).__name__})", True
            publish("stopped")
            return summary

    if options.ignore_hours:
        grid_start = clock.now()
        slot = grid_start
    else:
        _sleep_until(clock, start_dt)
        grid_start = start_dt
        late = clock.now() - start_dt
        slot = start_dt if late <= timedelta(0) else start_dt + interval * -(-late // interval)

    publish("running")
    market_confirmed = options.ignore_hours
    closed_checks = 0
    consecutive_failed = 0
    while options.ignore_hours or slot <= end_dt:
        if options.max_cycles is not None and summary.cycles >= options.max_cycles:
            summary.reason = "reached the cycle limit"
            break
        _sleep_until(clock, slot)
        skipped = 0
        behind = clock.now() - slot
        if behind >= interval:
            skipped = int(behind // interval)
            slot += interval * skipped
            summary.skipped_slots += skipped
            if not options.ignore_hours and slot > end_dt:
                break
        if not market_confirmed:
            traded = check_market()
            if traded is False:
                closed_checks += 1
                log.warning("no candles for today yet (%d/%d)", closed_checks, _MARKET_CHECKS)
                if closed_checks >= _MARKET_CHECKS:
                    summary.reason = "market closed (no candles today)"
                    break
                slot += interval
                continue
            market_confirmed = True
        index = int((slot - grid_start) // interval)
        todo = tier1 + (tier2 if index % ratio == 0 else [])
        result = collector.run_cycle(slot, todo, skipped)
        summary.cycles += 1
        summary.ok_calls += result.ok_calls
        summary.failed_calls += result.failed_calls
        summary.rows += result.rows
        publish("running", slot)
        if result.ok_calls == 0 and result.planned_calls > 0:
            consecutive_failed += 1
            if consecutive_failed >= cfg.max_consecutive_failed_cycles:
                log.error("%d empty cycles in a row; stopping", consecutive_failed)
                summary.reason, summary.aborted = "too many empty cycles", True
                break
        else:
            consecutive_failed = 0
        slot += interval
    if not summary.reason:
        summary.reason = "capture window finished"
    if after_close is not None and not summary.aborted and not options.ignore_hours:
        try:
            after_close()
        except Exception as exc:  # the end-of-day job must not hide a good capture day
            log.error("end-of-day job failed: %s: %s", type(exc).__name__, exc)
    publish("stopped" if summary.aborted else "finished")
    return summary
