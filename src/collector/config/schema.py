# What: the validated shape of config.yaml. Unknown keys and impossible values stop the program.
# In: a plain dict read from YAML. Out: an AppConfig object.
"""Configuration schema (pydantic). Every threshold used by the code lives here."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    """Base class: reject unknown keys and freeze values after loading."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PathsConfig(_Strict):
    """Where data and logs live."""

    data_root: Path = Path("data")
    logs_root: Path = Path("logs")
    nifty_candles_root: Path | None = None


class NseConfig(_Strict):
    """How politely and how patiently we talk to the NSE archive."""

    archive_base_url: str = "https://nsearchives.nseindia.com"
    user_agent: str
    min_interval_seconds: float = Field(ge=0.0)
    timeout_seconds: float = Field(gt=0.0)
    max_attempts: int = Field(ge=1)
    backoff_base_seconds: float = Field(ge=0.0)
    backoff_max_seconds: float = Field(ge=0.0)
    abort_after_consecutive_errors: int = Field(ge=1)


class FoBhavcopyConfig(_Strict):
    """Which F&O file format applies on which dates."""

    overlap_start: date
    new_format_start: date

    @model_validator(mode="after")
    def _check_order(self) -> FoBhavcopyConfig:
        """The overlap window must start before the new-only period."""
        if self.overlap_start > self.new_format_start:
            raise ValueError("fo_bhavcopy.overlap_start must not be after new_format_start")
        return self


class BackfillConfig(_Strict):
    """The date range and sanity thresholds of the archive backfill."""

    start_date: date
    end_date: date | None = None
    min_expected_underlyings: int = Field(ge=1)
    row_count_change_ratio: float = Field(gt=0.0)


class UniverseConfig(_Strict):
    """How the Tier 2 stock list is derived from the stored option data."""

    window_days: int = Field(default=60, ge=5)
    tier2_size: int = Field(default=40, ge=1)
    min_day_share: float = Field(default=0.8, gt=0.0, le=1.0)


class AppConfig(_Strict):
    """The whole configuration."""

    paths: PathsConfig
    nse: NseConfig
    fo_bhavcopy: FoBhavcopyConfig
    backfill: BackfillConfig
    universe: UniverseConfig = UniverseConfig()
