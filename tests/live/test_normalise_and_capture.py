# What: tests for the option-chain normaliser and one capture cycle (files, health, errors).
# In: a real chain fixture, a fake Fyers client and a simulated clock. Out: pass/fail.
"""Normalisation and capture."""

from __future__ import annotations

import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from collector.live.capture import ChainCollector, classify_error
from collector.live.targets import Target
from collector.normalise.option_chain import (
    OPTION_CHAIN_COLUMNS,
    ChainError,
    expiries_from_response,
    expiry_date_from_epoch,
    normalise_chain,
)
from collector.store.layout import Layout
from collector.store.parquet import read_table
from tests.live.helpers import FakeClock, FakeFyers, capture_config, ist, load_chain

DAY = date(2026, 10, 26)
SLOT = ist(2026, 10, 26, 9, 15)
NIFTY = Target("NIFTY", "NSE:NIFTY50-INDEX", 1, 25, 2)


def test_normalise_real_chain() -> None:
    chain = load_chain()
    frame = normalise_chain(
        chain, underlying="NIFTY", tier=1, expiry_epoch="1793095800", expiry_flag="M",
        snapshot_ts=SLOT, received_ts=ist(2026, 10, 26, 9, 15, 2),
    )  # fmt: skip
    assert list(frame.columns) == OPTION_CHAIN_COLUMNS
    assert len(frame) == 14 and set(frame["option_type"]) == {
        "CE",
        "PE",
    }  # the spot row is not a row
    assert (frame["expiry_date"] == date(2026, 10, 27)).all() and (
        frame["expiry_flag"] == "M"
    ).all()
    assert (frame["underlying_ltp"] == 22600).all() and (frame["vix"] == 16.86).all()
    assert frame["oi_qty"].notna().all() and str(frame["oi_qty"].dtype) == "Int64"
    assert frame["total_call_oi"].iloc[0] == 267687940
    pe = frame[(frame["strike"] == 22450) & (frame["option_type"] == "PE")].iloc[0]
    assert pe["symbol"] == "NSE:NIFTY26OCT22450PE" and pe["volume_units"] == 322159500
    assert pe["prev_oi_qty"] + pe["oi_ch_qty"] == pe["oi_qty"]


def test_expiry_helpers() -> None:
    assert expiry_date_from_epoch("1793095800") == date(2026, 10, 27)
    listed = expiries_from_response(load_chain())
    assert listed[0] == ("1793095800", "M") and listed[1][1] == "W" and len(listed) == 18
    assert expiries_from_response({"s": "error"}) == []


def test_unusable_answers_raise() -> None:
    kwargs: dict[str, Any] = {
        "underlying": "X", "tier": 1, "expiry_epoch": "1793095800", "expiry_flag": None,
        "snapshot_ts": SLOT, "received_ts": SLOT,
    }  # fmt: skip
    with pytest.raises(ChainError, match="not ok"):
        normalise_chain({"s": "error", "code": -300, "message": "bad"}, **kwargs)
    with pytest.raises(ChainError, match="optionsChain"):
        normalise_chain({"s": "ok", "data": {}}, **kwargs)


def test_classify_error() -> None:
    assert classify_error({"code": 429, "message": ""}) == ("rate_limit", 429)
    assert classify_error({"code": 1, "message": "Too many requests"})[0] == "rate_limit"
    assert classify_error({"code": -16, "message": "Could not authenticate the user"})[0] == "auth"
    assert classify_error({"code": -300, "message": "Invalid symbol"}) == ("api", -300)
    assert classify_error({})[0] == "api"


def _collector(
    tmp_path: Path, client: FakeFyers, renew: Any = None, **cfg: Any
) -> tuple[ChainCollector, Layout, FakeClock]:
    layout = Layout(tmp_path / "data")
    clock = FakeClock(SLOT)
    collector = ChainCollector(
        DAY, capture_config(**cfg), layout, clock, lambda: client, renew or (lambda: None)
    )
    return collector, layout, clock


def test_cycle_writes_rows_raw_file_and_health(tmp_path: Path) -> None:
    client = FakeFyers()
    collector, layout, _ = _collector(tmp_path, client)
    result = collector.run_cycle(SLOT, [NIFTY])
    assert (result.planned_calls, result.ok_calls, result.failed_calls) == (2, 2, 0)
    assert result.rows == 28 and result.rate_limit_hits == 0
    # one discovery call plus one call per captured expiry
    assert [c["timestamp"] for c in client.calls] == ["", "1793095800", "1793700600"]
    frame = read_table(layout.chain_silver_file(DAY, "091500"))
    assert len(frame) == 28 and set(frame["expiry_flag"]) == {"M", "W"}
    raw = gzip.decompress(layout.chain_raw_file(DAY, "091500").read_bytes()).decode().splitlines()
    assert len(raw) == 2 and json.loads(raw[0])["underlying"] == "NIFTY"
    health = layout.live_health_dir(DAY)
    calls = pd.read_csv(health / "calls.csv")
    assert len(calls) == 3 and calls["ok"].all()  # discovery + 2 expiries
    cycles = pd.read_csv(health / "cycles.csv")
    assert cycles.loc[0, "ok_calls"] == 2 and cycles.loc[0, "rows"] == 28


def test_expiries_are_discovered_once_per_day(tmp_path: Path) -> None:
    client = FakeFyers()
    collector, _, clock = _collector(tmp_path, client)
    collector.run_cycle(SLOT, [NIFTY])
    before = len(client.calls)
    collector.run_cycle(ist(2026, 10, 26, 9, 16), [NIFTY])
    assert len(client.calls) - before == 2  # only the two expiry calls, no new discovery


def test_raw_saving_can_be_switched_off(tmp_path: Path) -> None:
    collector, layout, _ = _collector(tmp_path, FakeFyers(), save_raw=False)
    collector.run_cycle(SLOT, [NIFTY])
    assert not layout.chain_raw_file(DAY, "091500").exists()
    assert layout.chain_silver_file(DAY, "091500").exists()


def test_authentication_answer_triggers_one_relogin_and_retry(tmp_path: Path) -> None:
    renewed: list[int] = []

    def script(n: int, data: dict[str, Any]) -> Any:
        if n == 1:  # the very first call is refused
            return {"s": "error", "code": -16, "message": "Could not authenticate the user"}
        return None

    collector, _, _ = _collector(tmp_path, FakeFyers(script), renew=lambda: renewed.append(1))
    result = collector.run_cycle(SLOT, [NIFTY])
    assert renewed == [1] and result.ok_calls == 2 and result.failed_calls == 0


def test_rate_limit_pauses_and_is_counted(tmp_path: Path) -> None:
    def script(n: int, data: dict[str, Any]) -> Any:
        return {"s": "error", "code": 429, "message": "limit"} if n == 2 else None

    collector, _, clock = _collector(tmp_path, FakeFyers(script))
    result = collector.run_cycle(SLOT, [NIFTY])
    assert result.rate_limit_hits == 1 and result.ok_calls == 1 and result.failed_calls == 1
    assert clock.slept >= 30.0  # backed off


def test_exceptions_and_bad_shapes_become_gaps_not_crashes(tmp_path: Path) -> None:
    def script(n: int, data: dict[str, Any]) -> Any:
        if n == 2:
            raise RuntimeError("boom")
        if n == 3:
            return {"s": "ok", "data": {}}
        return None

    collector, layout, _ = _collector(tmp_path, FakeFyers(script))
    result = collector.run_cycle(SLOT, [NIFTY])
    assert result.ok_calls == 0 and result.failed_calls == 2 and result.rows == 0
    calls = pd.read_csv(layout.live_health_dir(DAY) / "calls.csv")
    assert sorted(calls[~calls["ok"]]["error_kind"]) == ["exception", "shape"]
    assert not layout.chain_silver_file(DAY, "091500").exists()  # nothing to store


def test_failed_discovery_is_a_visible_failure(tmp_path: Path) -> None:
    collector, layout, _ = _collector(
        tmp_path, FakeFyers(lambda n, d: {"s": "error", "code": -300, "message": "x"})
    )
    result = collector.run_cycle(SLOT, [NIFTY])
    assert result.planned_calls == 1 and result.failed_calls == 1 and result.ok_calls == 0
    cycles = pd.read_csv(layout.live_health_dir(DAY) / "cycles.csv")
    assert cycles.loc[0, "failed_calls"] == 1
