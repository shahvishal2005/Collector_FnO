# What: tests for config loading, the rate limiter, retry, time helpers and hashing.
# In: temp files. Out: pass/fail.
"""Common helpers and configuration."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
import yaml

from collector.common.hashing import sha256_bytes, sha256_file
from collector.common.ratelimit import RateLimiter
from collector.common.retry import retry_call
from collector.common.timeutil import IST, daterange, require_aware
from collector.config import ConfigError, config_hash, load_config
from tests.conftest import make_config

EXAMPLE = Path(__file__).parents[1] / "config" / "config.example.yaml"


def test_example_config_is_valid() -> None:
    cfg = load_config(EXAMPLE)
    assert cfg.backfill.start_date == date(2017, 10, 24)
    assert cfg.fo_bhavcopy.overlap_start < cfg.fo_bhavcopy.new_format_start


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    raw = yaml.safe_load(EXAMPLE.read_text(encoding="utf-8"))
    raw["nse"]["surprise"] = 1
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="surprise"):
        load_config(bad)


def test_missing_config_names_the_fix(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config.example.yaml"):
        load_config(tmp_path / "nope.yaml")


def test_overlap_order_is_validated(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="overlap_start"):
        make_config(
            tmp_path,
            fo_bhavcopy={"overlap_start": date(2024, 8, 1), "new_format_start": date(2024, 7, 8)},
        )


def test_config_hash_is_stable_and_sensitive(tmp_path: Path) -> None:
    a, b = make_config(tmp_path), make_config(tmp_path)
    assert config_hash(a) == config_hash(b)
    other = make_config(
        tmp_path,
        backfill={
            "start_date": date(2018, 1, 1),
            "min_expected_underlyings": 3,
            "row_count_change_ratio": 0.5,
        },
    )
    assert config_hash(a) != config_hash(other)


def test_rate_limiter_waits_only_when_needed() -> None:
    now = [0.0]
    slept: list[float] = []

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(2.0, clock=lambda: now[0], sleep=sleep)
    limiter.wait()  # first call never waits
    now[0] += 0.5
    limiter.wait()  # 1.5 s still to wait
    now[0] += 5.0
    limiter.wait()  # enough time has passed
    assert slept == [1.5]


def test_retry_succeeds_after_failures_and_gives_up() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise ValueError("temporary")
        return "ok"

    waits: list[float] = []
    assert (
        retry_call(
            flaky,
            attempts=3,
            base_delay=1.0,
            max_delay=10.0,
            retry_on=(ValueError,),
            sleep=waits.append,
        )
        == "ok"
    )
    assert waits == [1.0, 2.0]
    with pytest.raises(ValueError):
        retry_call(
            lambda: (_ for _ in ()).throw(ValueError("x")),
            attempts=2,
            base_delay=0,
            max_delay=0,
            retry_on=(ValueError,),
            sleep=lambda s: None,
        )


def test_non_retryable_error_is_not_retried() -> None:
    calls = {"n": 0}

    def boom() -> None:
        calls["n"] += 1
        raise KeyError("fatal")

    with pytest.raises(KeyError):
        retry_call(
            boom,
            attempts=5,
            base_delay=0,
            max_delay=0,
            retry_on=(ValueError,),
            sleep=lambda s: None,
        )
    assert calls["n"] == 1


def test_naive_datetime_is_refused() -> None:
    with pytest.raises(ValueError):
        require_aware(datetime(2026, 1, 1))
    assert require_aware(datetime(2026, 1, 1, tzinfo=IST)).tzinfo is not None


def test_daterange_is_inclusive() -> None:
    assert list(daterange(date(2026, 1, 1), date(2026, 1, 3))) == [
        date(2026, 1, d) for d in (1, 2, 3)
    ]


def test_hashes_agree(tmp_path: Path) -> None:
    path = tmp_path / "f.bin"
    path.write_bytes(b"hello")
    assert sha256_file(path) == sha256_bytes(b"hello")
