# What: tests for the day-0 probe using a fake Fyers client (no network, no credentials).
# In: canned answers. Out: pass/fail.
"""Probe tests."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from collector.config.schema import LiveConfig
from collector.fyers.probe import (
    _FUT_PATTERN,
    _OPT_PATTERN,
    Probe,
    expired_variant,
    find_symbols,
    pick_option_symbol,
    previous_month,
    second_expiry,
    summarize_chain,
)

CHAIN = {
    "s": "ok",
    "code": 200,
    "data": {
        "optionsChain": [
            {"symbol": "NSE:NIFTY50-INDEX", "option_type": "", "strike_price": -1},
            {
                "symbol": "NSE:NIFTY26OCT25000CE",
                "option_type": "CE",
                "strike_price": 25000,
                "oi": 5,
            },
            {
                "symbol": "NSE:NIFTY26OCT25000PE",
                "option_type": "PE",
                "strike_price": 25000,
                "oi": 7,
            },
        ],
        "expiryData": [
            {"date": "27-10-2026", "expiry": "1793095800", "expiry_flag": "M"},
            {"date": "03-11-2026", "expiry": "1793700600", "expiry_flag": "W"},
        ],
    },
}
MASTER = (
    "1,NIFTY 26 OCT FUT,11,75,0.05,,,,,NSE:NIFTY26OCTFUT,10,11,x,NIFTY,26000,0,XX\n"
    "2,NIFTY 26 OCT 25000 CE,14,75,0.05,,,,,NSE:NIFTY26OCT25000CE,10,11,x,NIFTY,26000,25000,CE\n"
)


class FakeClient:
    """Answers like Fyers' SDK, with the profile holding personal data that must never be saved."""

    def get_profile(self) -> dict[str, Any]:
        return {"s": "ok", "code": 200, "data": {"name": "SECRET NAME", "email": "x@y.z"}}

    def optionchain(self, data: dict[str, Any]) -> dict[str, Any]:
        return CHAIN

    def quotes(self, data: dict[str, Any]) -> dict[str, Any]:
        return {"s": "ok", "code": 200, "d": []}

    def depth(self, data: dict[str, Any]) -> dict[str, Any]:
        return {"s": "ok", "code": 200, "d": {}}

    def history(self, data: dict[str, Any]) -> dict[str, Any]:
        if "SEP" in data["symbol"]:
            return {"s": "error", "code": -300, "message": "Invalid symbol", "candles": []}
        return {"s": "ok", "code": 200, "candles": [[1, 2, 3, 4, 5, 6, 7]]}


class FakeResponse:
    status_code = 200
    text = MASTER


def test_symbol_helpers() -> None:
    assert previous_month(26, "OCT") == (26, "SEP")
    assert previous_month(26, "JAN") == (25, "DEC")
    assert expired_variant("NSE:NIFTY26OCTFUT") == "NSE:NIFTY26SEPFUT"
    assert expired_variant("NSE:NIFTY26JAN25000CE") == "NSE:NIFTY25DEC25000CE"
    assert expired_variant("NSE:RELIANCE-EQ") is None
    assert find_symbols(MASTER, _FUT_PATTERN, "NIFTY", 1) == ["NSE:NIFTY26OCTFUT"]
    assert find_symbols(MASTER, _OPT_PATTERN, "NIFTY", 1) == ["NSE:NIFTY26OCT25000CE"]
    assert find_symbols(MASTER, _OPT_PATTERN, "BANKNIFTY", 1) == []


def test_chain_summary_and_symbol_pick() -> None:
    summary = summarize_chain(CHAIN)
    assert summary["row_count"] == 3 and summary["distinct_strikes"] == 1
    assert "oi" in summary["row_fields"] and summary["expiry_count"] == 2
    assert second_expiry(CHAIN) == "1793700600"
    assert second_expiry({"data": {"expiryData": [{"expiry": "1"}]}}) is None
    assert second_expiry({"s": "error"}) is None
    assert pick_option_symbol(CHAIN) == "NSE:NIFTY26OCT25000CE"
    assert summarize_chain({"s": "error"}) == {"top_level_keys": ["s"]}


def test_probe_runs_saves_raw_answers_and_never_saves_the_profile(tmp_path: Path) -> None:
    cfg = LiveConfig(probe_strike_counts=[3], probe_latency_calls=2, probe_call_gap_seconds=0.0)
    probe = Probe(
        FakeClient(),
        cfg,
        tmp_path,
        sleep=lambda s: None,
        http_get=lambda url, timeout: FakeResponse(),
    )
    records = probe.run(date(2026, 10, 24))
    names = {r.name for r in records}
    assert {
        "profile_status_only",
        "optionchain_NIFTY_3",
        "quotes_spots",
        "history_option_sample",
    } <= names
    assert {"history_expired_future", "history_expired_option"} <= names
    assert (tmp_path / "optionchain_NIFTY_3.json").is_file()
    assert "optionchain_NIFTY_expiry2" in names and "optionchain_SENSEX_expiry2" in names
    assert (tmp_path / "symbol_master_NSE_FO.csv").is_file()
    assert not (tmp_path / "profile_status_only.json").exists()
    everything = "".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("*") if p.is_file())
    assert "SECRET NAME" not in everything and "x@y.z" not in everything
    summary = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    expired = next(r for r in summary if r["name"] == "history_expired_future")
    assert expired["ok"] is False and expired["code"] == -300
    assert "Fyers day-0 probe report" in (tmp_path / "PROBE_REPORT.md").read_text(encoding="utf-8")


def test_a_failing_call_is_recorded_not_raised(tmp_path: Path) -> None:
    class Broken(FakeClient):
        def optionchain(self, data: dict[str, Any]) -> dict[str, Any]:
            raise RuntimeError("boom")

    cfg = LiveConfig(probe_strike_counts=[3], probe_latency_calls=1, probe_call_gap_seconds=0.0)
    probe = Probe(
        Broken(), cfg, tmp_path, sleep=lambda s: None, http_get=lambda url, timeout: FakeResponse()
    )
    records = probe.run(date(2026, 10, 24))
    failed = [r for r in records if r.name.startswith("optionchain_")]
    assert failed and all(r.error == "RuntimeError" and not r.ok for r in failed)
