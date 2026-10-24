# What: shared test helpers (fixture zips, a test config).
# In: fixture CSV files. Out: zip bytes and an AppConfig that stores everything under tmp_path.
"""Test helpers."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from collector.config.schema import AppConfig

FIXTURES = Path(__file__).parent / "fixtures"


def make_zip(csv_name: str, inner_name: str | None = None) -> bytes:
    """Zip one fixture CSV in memory (as NSE ships it)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(FIXTURES / csv_name, inner_name or csv_name)
    return buffer.getvalue()


def make_config(tmp_path: Path, **overrides: object) -> AppConfig:
    """A valid config whose data and logs live in tmp_path."""
    raw: dict[str, object] = {
        "paths": {"data_root": str(tmp_path / "data"), "logs_root": str(tmp_path / "logs")},
        "nse": {
            "archive_base_url": "https://example.test",
            "user_agent": "test-agent",
            "min_interval_seconds": 0.0,
            "timeout_seconds": 5.0,
            "max_attempts": 2,
            "backoff_base_seconds": 0.0,
            "backoff_max_seconds": 0.0,
            "abort_after_consecutive_errors": 3,
        },
        "fo_bhavcopy": {"overlap_start": date(2024, 7, 3), "new_format_start": date(2024, 7, 8)},
        "backfill": {
            "start_date": date(2017, 10, 24),
            "min_expected_underlyings": 3,
            "row_count_change_ratio": 0.5,
        },
    }
    raw.update(overrides)
    return AppConfig.model_validate(raw)


@pytest.fixture
def cfg(tmp_path: Path) -> AppConfig:
    """The default test configuration."""
    return make_config(tmp_path)
