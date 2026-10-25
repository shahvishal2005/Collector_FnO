# What: test helpers for the live capture: a simulated clock and a fake Fyers client.
# In: nothing. Out: FakeClock, FakeFyers and a ready-made capture configuration.
"""Helpers (no network, no real credentials)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from collector.common.timeutil import IST
from collector.config.schema import CaptureConfig

FIXTURES = Path(__file__).parents[1] / "fixtures"


def load_chain() -> dict[str, Any]:
    """A real Nifty option-chain answer (3 strikes each side) captured by the day-0 probe."""
    data: dict[str, Any] = json.loads((FIXTURES / "chain_nifty_3.json").read_text(encoding="utf-8"))
    return data


class FakeClock:
    """Time that only moves when someone sleeps (or advance() is called)."""

    def __init__(self, start: datetime) -> None:
        self.current = start
        self.slept = 0.0

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        if seconds > 0:
            self.slept += seconds
            self.current += timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


def ist(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> datetime:
    """A timezone-aware IST moment."""
    return datetime(year, month, day, hour, minute, second, tzinfo=IST)


def capture_config(**overrides: Any) -> CaptureConfig:
    """A short test day (09:15 to 09:45) with quick settings."""
    values: dict[str, Any] = {
        "login_time": time(8, 45),
        "capture_start": time(9, 15),
        "capture_end": time(9, 45),
        "tier1_interval_seconds": 60,
        "tier2_interval_seconds": 300,
        "tier1_expiry_count": 2,
        "tier2_expiry_count": 1,
        "min_call_gap_seconds": 0.25,
        "rate_limit_backoff_seconds": 30.0,
        "max_consecutive_failed_cycles": 3,
    }
    values.update(overrides)
    return CaptureConfig(**values)


class FakeFyers:
    """Answers option-chain calls with the real fixture, or with scripted problems."""

    def __init__(self, on_call: Callable[[int, dict[str, Any]], Any] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._on_call = on_call
        self._chain = load_chain()

    def optionchain(self, data: dict[str, Any]) -> Any:
        self.calls.append(data)
        if self._on_call is not None:
            outcome = self._on_call(len(self.calls), data)
            if outcome is not None:
                return outcome
        return self._chain
