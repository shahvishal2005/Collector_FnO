# What: build NSE archive file names and URLs, and decide which F&O file format applies on a date.
# In: a date and the format-cutover settings. Out: URLs and the list of formats to try.
"""NSE archive URLs. Pure functions: no network."""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from collector.config.schema import FoBhavcopyConfig

_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


class FoFormat(StrEnum):
    """The two F&O end-of-day file formats NSE has used."""

    OLD = "old"  # fo<DD><MON><YYYY>bhav.csv.zip, until early July 2024
    NEW = "new"  # BhavCopy_NSE_FO_0_0_0_<YYYYMMDD>_F_0000.csv.zip (UDiFF), from July 2024


def month_abbr(day: date) -> str:
    """Three-letter upper-case month (locale independent)."""
    return _MONTHS[day.month - 1]


def fo_filename(fmt: FoFormat, day: date) -> str:
    """The file name NSE uses for the F&O bhavcopy of a given day and format."""
    if fmt is FoFormat.OLD:
        return f"fo{day.day:02d}{month_abbr(day)}{day.year}bhav.csv.zip"
    return f"BhavCopy_NSE_FO_0_0_0_{day:%Y%m%d}_F_0000.csv.zip"


def fo_url(base_url: str, fmt: FoFormat, day: date) -> str:
    """The full download URL for the F&O bhavcopy of a given day and format."""
    base = base_url.rstrip("/")
    name = fo_filename(fmt, day)
    if fmt is FoFormat.OLD:
        return f"{base}/content/historical/DERIVATIVES/{day.year}/{month_abbr(day)}/{name}"
    return f"{base}/content/fo/{name}"


def formats_for_date(day: date, cfg: FoBhavcopyConfig) -> list[FoFormat]:
    """Formats to download for a day; the first one is the primary source.

    Before the overlap window: old only. Inside it: old (primary) and new, so the two can be
    compared. From the new-format start: new only.
    """
    if day >= cfg.new_format_start:
        return [FoFormat.NEW]
    if day >= cfg.overlap_start:
        return [FoFormat.OLD, FoFormat.NEW]
    return [FoFormat.OLD]
