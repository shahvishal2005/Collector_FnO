# What: the description of one daily-file dataset: where its files are, how to read and check them.
# In: nothing. Out: the DailyDataset record that the generic backfill job and report work from.
"""A daily dataset is: a URL per day, a parser, a table schema and a quality check."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import pyarrow as pa

from collector.quality.fo_checks import Issue


@dataclass(frozen=True)
class DailyDataset:
    """Everything the generic job needs to know about one dataset."""

    name: str  # also the folder name under silver/ and the catalogue key
    description: str
    kind: str  # 'text' or 'zip': what the downloaded file is
    file_name: Callable[[date], str]
    url: Callable[[str, date], str]  # (archive base URL, day) -> URL
    parse: Callable[[bytes, date, str, datetime], pd.DataFrame]
    schema: pa.Schema
    check: Callable[[pd.DataFrame, date], list[Issue]]
    row_count_jump_check: bool = True  # a fixed-size or tiny table has no meaningful row-count jump
