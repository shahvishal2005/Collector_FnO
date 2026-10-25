# What: allow only one live collector at a time (an OS file lock that frees itself on a crash).
# In: a lock file path. Out: a context manager that raises LockHeld if another copy is running.
"""Single-instance lock.

The collector must be the single writer of its data and must not share Fyers' rate limit with a
second copy of itself. The lock is held by the operating system, so it disappears automatically
if the process dies; no stale-lock cleanup is ever needed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import TracebackType
from typing import IO


class LockHeld(Exception):
    """Another copy of the collector holds the lock."""


class InstanceLock:
    """Exclusive, non-blocking lock on a small file."""

    def __init__(self, path: Path) -> None:
        """Remember the lock file location."""
        self._path = path
        self._handle: IO[str] | None = None

    def acquire(self) -> None:
        """Take the lock or raise LockHeld."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = self._path.open("a+", encoding="utf-8")
        try:
            if sys.platform == "win32":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise LockHeld(f"another collector instance holds {self._path}") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
        self._handle = handle

    def release(self) -> None:
        """Give the lock back (also happens when the process exits)."""
        if self._handle is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None

    def __enter__(self) -> InstanceLock:
        """Acquire on entering a with-block."""
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Release on leaving a with-block."""
        self.release()
