# What: enforce a minimum gap between consecutive requests (politeness to the data source).
# In: the minimum interval in seconds. Out: calls to wait() block until the gap has passed.
"""A tiny single-threaded rate limiter."""

from __future__ import annotations

import time
from collections.abc import Callable


class RateLimiter:
    """Blocks so that two wait() calls are never closer than `min_interval` seconds."""

    def __init__(
        self,
        min_interval: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Remember the interval; clock and sleep can be replaced in tests."""
        self._interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def wait(self) -> None:
        """Sleep just long enough to respect the interval, then record the time."""
        now = self._clock()
        if self._last is not None:
            remaining = self._interval - (now - self._last)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last = now
