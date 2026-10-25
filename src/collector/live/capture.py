# What: run one live capture cycle: call the option-chain endpoint per target, store results.
# In: the targets of the cycle, the cycle's time slot, a Fyers client and a clock.
# Out: raw answers (compressed) in bronze, normalised rows in silver, health records, a CycleResult.
"""Option-chain capture for one cycle.

Failures never stop a cycle: each failed call becomes a health row (a visible gap). A rate-limit
answer triggers a pause; an authentication answer triggers one re-login and one retry per cycle.
Only market-data endpoints are used.
"""

from __future__ import annotations

import gzip
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from collector.config.schema import CaptureConfig
from collector.live.clock import Clock
from collector.live.health import CallHealth, CycleHealth, HealthLog
from collector.live.targets import Target
from collector.normalise.option_chain import (
    OPTION_CHAIN_SCHEMA,
    ChainError,
    expiries_from_response,
    normalise_chain,
)
from collector.store.layout import Layout
from collector.store.parquet import write_atomic_bytes, write_table

log = logging.getLogger(__name__)
_AUTH_CODES = {-8, -15, -16, 401, 403}


@dataclass(frozen=True)
class CycleResult:
    """What one cycle achieved."""

    planned_calls: int
    ok_calls: int
    failed_calls: int
    rows: int
    rate_limit_hits: int


def classify_error(response: dict[str, Any]) -> tuple[str, int | None]:
    """Map a Fyers error answer to ('rate_limit' | 'auth' | 'api', code)."""
    raw = response.get("code")
    code = int(raw) if isinstance(raw, int | float) else None
    message = str(response.get("message", "")).lower()
    if code == 429 or "too many" in message or "rate limit" in message:
        return "rate_limit", code
    if code in _AUTH_CODES or "authenticate" in message or "token" in message:
        return "auth", code
    return "api", code


class ChainCollector:
    """Captures option chains for a trading day."""

    def __init__(
        self,
        day: date,
        cfg: CaptureConfig,
        layout: Layout,
        clock: Clock,
        get_client: Callable[[], Any],
        renew_client: Callable[[], None],
    ) -> None:
        """Remember everything a cycle needs; expiries are discovered lazily and cached."""
        self._day = day
        self._cfg = cfg
        self._layout = layout
        self._clock = clock
        self._get_client = get_client
        self._renew_client = renew_client
        self._health = HealthLog(layout.live_health_dir(day))
        self._expiries: dict[str, list[tuple[str, str | None]]] = {}

    # ---- one API call ----
    def _fetch(
        self, target: Target, epoch: str, strikecount: int
    ) -> tuple[dict[str, Any] | None, str, int | None]:
        """Call the option-chain endpoint; return (answer, error_kind, code). '' means success."""
        try:
            answer = self._get_client().optionchain(
                data={"symbol": target.spot_symbol, "strikecount": strikecount, "timestamp": epoch}
            )
        except Exception as exc:  # the SDK raises many kinds of errors; all become health rows
            log.warning("%s: call failed (%s)", target.name, type(exc).__name__)
            return None, "exception", None
        if not isinstance(answer, dict):
            return None, "shape", None
        if answer.get("s") != "ok":
            kind, code = classify_error(answer)
            return answer, kind, code
        return answer, "", None

    def _call_with_recovery(
        self, target: Target, epoch: str, strikecount: int, state: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, int | None, float, datetime]:
        """One call; one re-login and retry on an auth answer; a pause on a rate-limit answer."""
        started = self._clock.now()
        answer, kind, code = self._fetch(target, epoch, strikecount)
        if kind == "auth" and not state["renewed"]:
            state["renewed"] = True
            log.warning("authentication answer; logging in again")
            try:
                self._renew_client()
            except Exception as exc:
                log.error("re-login failed (%s)", type(exc).__name__)
            else:
                answer, kind, code = self._fetch(target, epoch, strikecount)
        received = self._clock.now()
        if kind == "rate_limit":
            state["rate_limit_hits"] += 1
            self._clock.sleep(self._cfg.rate_limit_backoff_seconds)
        else:
            self._clock.sleep(self._cfg.min_call_gap_seconds)
        return answer, kind, code, (received - started).total_seconds(), received

    # ---- expiries ----
    def expiries_for(
        self, target: Target, cycle_ts: datetime, state: dict[str, Any]
    ) -> list[tuple[str, str | None]]:
        """The target's expiries (nearest first); discovered once per day with one extra call."""
        known = self._expiries.get(target.name)
        if known:
            return known
        answer, kind, code, seconds, _ = self._call_with_recovery(target, "", 1, state)
        listed = expiries_from_response(answer) if answer is not None and kind == "" else []
        self._health.call(
            CallHealth(
                self._day,
                cycle_ts,
                target.name,
                "",
                target.tier,
                bool(listed),
                kind or ("shape" if not listed else ""),
                code,
                round(seconds, 3),
                0,
            )
        )
        if listed:
            self._expiries[target.name] = listed
        return listed

    # ---- one cycle ----
    def run_cycle(
        self, cycle_ts: datetime, targets: list[Target], skipped_slots: int = 0
    ) -> CycleResult:
        """Capture every target's nearest expiries, write the files and the health rows."""
        started = self._clock.now()
        state: dict[str, Any] = {"renewed": False, "rate_limit_hits": 0}
        frames: list[pd.DataFrame] = []
        raw_lines: list[str] = []
        planned = ok = failed = 0
        for target in targets:
            expiries = self.expiries_for(target, cycle_ts, state)
            if not expiries:
                planned += 1
                failed += 1
                continue
            for epoch, flag in expiries[: target.expiry_count]:
                planned += 1
                answer, kind, code, seconds, received = self._call_with_recovery(
                    target, epoch, target.strikecount, state
                )
                rows = 0
                if kind == "" and answer is not None:
                    try:
                        frame = normalise_chain(
                            answer, underlying=target.name, tier=target.tier, expiry_epoch=epoch,
                            expiry_flag=flag, snapshot_ts=cycle_ts, received_ts=received,
                        )  # fmt: skip
                    except ChainError as exc:
                        log.warning("%s: unusable answer (%s)", target.name, exc)
                        kind = "shape"
                    else:
                        frames.append(frame)
                        rows = len(frame)
                if self._cfg.save_raw and answer is not None:
                    raw_lines.append(
                        json.dumps(
                            {"underlying": target.name, "tier": target.tier, "expiry_epoch": epoch,
                             "received_at": received.isoformat(), "response": answer},
                            default=str,
                        )
                    )  # fmt: skip
                if kind == "":
                    ok += 1
                else:
                    failed += 1
                self._health.call(
                    CallHealth(
                        self._day,
                        cycle_ts,
                        target.name,
                        epoch,
                        target.tier,
                        kind == "",
                        kind,
                        code,
                        round(seconds, 3),
                        rows,
                    )
                )
        label = cycle_ts.strftime("%H%M%S")
        if raw_lines:
            payload = gzip.compress(("\n".join(raw_lines) + "\n").encode("utf-8"))
            write_atomic_bytes(self._layout.chain_raw_file(self._day, label), payload)
        total_rows = 0
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            total_rows = len(combined)
            write_table(
                combined, OPTION_CHAIN_SCHEMA, self._layout.chain_silver_file(self._day, label)
            )
        finished = self._clock.now()
        self._health.cycle(
            CycleHealth(
                self._day,
                cycle_ts,
                started,
                finished,
                planned,
                ok,
                failed,
                total_rows,
                state["rate_limit_hits"],
                skipped_slots,
            )
        )
        return CycleResult(planned, ok, failed, total_rows, state["rate_limit_hits"])
