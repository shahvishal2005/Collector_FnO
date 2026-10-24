# What: one place to configure logging (console plus a rotating-by-day file).
# In: the logs folder and a level. Out: the root logger configured.
"""Logging setup."""

from __future__ import annotations

import logging
from pathlib import Path

from collector.common.timeutil import now_ist

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(logs_root: Path, name: str, level: int = logging.INFO) -> Path:
    """Log to the console and to logs/<name>_<date>.log; return the log file path."""
    logs_root.mkdir(parents=True, exist_ok=True)
    log_file = logs_root / f"{name}_{now_ist():%Y%m%d}.log"
    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    formatter = logging.Formatter(_FORMAT)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    return log_file
