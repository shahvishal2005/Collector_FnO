# What: retry a function with exponential backoff. The sleep function can be replaced in tests.
# In: a callable, the exceptions worth retrying, and the backoff settings.
# Out: the callable's result, or the last exception after the final attempt.
"""Retry with backoff."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")
log = logging.getLogger(__name__)


def retry_call(
    func: Callable[[], T],
    *,
    attempts: int,
    base_delay: float,
    max_delay: float,
    retry_on: tuple[type[BaseException], ...],
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call func up to `attempts` times, waiting base_delay * 2**n (capped) between tries."""
    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return func()
        except retry_on as exc:
            last = exc
            if attempt == attempts:
                break
            delay = min(max_delay, base_delay * (2 ** (attempt - 1)))
            log.warning(
                "attempt %d/%d failed (%s); retrying in %.1fs", attempt, attempts, exc, delay
            )
            sleep(delay)
    assert last is not None
    raise last
