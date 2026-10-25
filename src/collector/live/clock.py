# What: a clock the scheduler can use, so tests can run a whole trading day in a blink.
# In: nothing. Out: the current IST time and a sleep function (real or simulated).
"""Clock abstraction."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Protocol

from collector.common.timeutil import now_ist


class Clock(Protocol):
    """What the scheduler needs from time."""

    def now(self) -> datetime:
        """The current time (timezone-aware, IST)."""

    def sleep(self, seconds: float) -> None:
        """Wait."""


class SystemClock:
    """The real clock."""

    def now(self) -> datetime:
        """The current IST time."""
        return now_ist()

    def sleep(self, seconds: float) -> None:
        """Really wait."""
        if seconds > 0:
            time.sleep(seconds)
