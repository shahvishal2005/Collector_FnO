# What: the validated shape of config.yaml. Unknown keys and impossible values stop the program.
# In: a plain dict read from YAML. Out: an AppConfig object.
"""Configuration schema (pydantic). Every threshold used by the code lives here."""

from __future__ import annotations

from datetime import date, time
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
    total_timeout_seconds: float = Field(gt=0.0)
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


class Tier1Underlying(_Strict):
    """One index whose option chain is captured at the highest frequency."""

    name: str
    spot_symbol: str


def _default_tier1() -> list[Tier1Underlying]:
    """Nifty 50, Bank Nifty, Fin Nifty, Midcap Nifty and Sensex (owner's choice, 2026-10-24)."""
    return [
        Tier1Underlying(name="NIFTY", spot_symbol="NSE:NIFTY50-INDEX"),
        Tier1Underlying(name="BANKNIFTY", spot_symbol="NSE:NIFTYBANK-INDEX"),
        Tier1Underlying(name="FINNIFTY", spot_symbol="NSE:FINNIFTY-INDEX"),
        Tier1Underlying(name="MIDCPNIFTY", spot_symbol="NSE:MIDCPNIFTY-INDEX"),
        Tier1Underlying(name="SENSEX", spot_symbol="BSE:SENSEX-INDEX"),
    ]


def _default_symbol_masters() -> dict[str, str]:
    """Fyers' public symbol master files (contract lists with lot sizes)."""
    return {
        "NSE_FO": "https://public.fyers.in/sym_details/NSE_FO.csv",
        "BSE_FO": "https://public.fyers.in/sym_details/BSE_FO.csv",
    }


class CaptureConfig(_Strict):
    """How the live option-chain scheduler behaves during a trading day (all times are IST)."""

    login_time: time = time(8, 45)
    capture_start: time = time(9, 15)
    capture_end: time = time(15, 30)
    tier1_interval_seconds: int = Field(default=60, ge=10)
    tier2_interval_seconds: int = Field(default=300, ge=10)
    tier1_strikecount: int = Field(default=25, ge=1)  # strikes captured each side of the money
    tier2_strikecount: int = Field(default=10, ge=1)
    tier1_expiry_count: int = Field(default=3, ge=1)  # nearest expiries captured
    tier2_expiry_count: int = Field(default=1, ge=1)
    tier2_file: Path = Path("data/reports/tier2_candidates.csv")
    tier2_limit: int = Field(default=40, ge=0)
    min_call_gap_seconds: float = Field(default=0.25, ge=0.0)  # politeness between API calls
    rate_limit_backoff_seconds: float = Field(default=30.0, ge=0.0)
    max_consecutive_failed_cycles: int = Field(default=5, ge=1)
    market_check_slots: int = Field(default=10, ge=1)  # no-candle checks before 'holiday'
    save_raw: bool = True  # keep every raw API answer (compressed) in bronze
    holidays: list[date] = Field(default_factory=list)  # extra no-trading days (optional)

    @model_validator(mode="after")
    def _check_intervals(self) -> CaptureConfig:
        """Tier 2 cycles must be a whole multiple of Tier 1 cycles; the window must make sense."""
        if self.tier2_interval_seconds % self.tier1_interval_seconds != 0:
            raise ValueError("tier2_interval_seconds must be a multiple of tier1_interval_seconds")
        if not self.login_time < self.capture_start < self.capture_end:
            raise ValueError("need login_time < capture_start < capture_end")
        return self


class LiveConfig(_Strict):
    """Settings for the Fyers live capture and its day-0 probe (read-only market data only)."""

    capture: CaptureConfig = Field(default_factory=CaptureConfig)
    # The scheduler refuses to run on any other computer (so the laptop cannot compete with the VPS
    # for the same Fyers rate limit). Empty list = allowed anywhere (tests, one-off checks).
    allowed_hosts: list[str] = Field(default_factory=list)
    tier1: list[Tier1Underlying] = Field(default_factory=_default_tier1)
    token_path: Path = Path("access_token.txt")
    sdk_log_dir: Path = Path("logs/fyers_sdk")
    symbol_master_urls: dict[str, str] = Field(default_factory=_default_symbol_masters)
    probe_strike_counts: list[int] = Field(default_factory=lambda: [3, 50])
    probe_latency_calls: int = Field(default=10, ge=1)
    probe_call_gap_seconds: float = Field(default=0.4, ge=0.0)
    probe_history_days: int = Field(default=3, ge=1)


class AppConfig(_Strict):
    """The whole configuration."""

    paths: PathsConfig
    nse: NseConfig
    fo_bhavcopy: FoBhavcopyConfig
    backfill: BackfillConfig
    universe: UniverseConfig = UniverseConfig()
    live: LiveConfig = Field(default_factory=LiveConfig)
