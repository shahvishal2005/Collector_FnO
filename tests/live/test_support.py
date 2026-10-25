# What: tests for supporting pieces: lock, host guard, status, targets, contract master, market.
# In: temp files and tiny fixtures. Out: pass/fail.
"""Supporting pieces of the live capture."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from collector.config.schema import CaptureConfig, LiveConfig
from collector.live.host import host_allowed
from collector.live.lock import InstanceLock, LockHeld
from collector.live.market import market_has_traded_today
from collector.live.status import Status, read_status, write_status
from collector.live.targets import build_targets, equity_symbol, load_tier2_names
from collector.normalise.contract_master import CONTRACT_MASTER_COLUMNS, parse_symbol_master
from tests.live.helpers import ist

MASTER = (
    "101126102748699,BANKNIFTY 27 Oct 26 FUT,11,30,0.2,,0915-1540|1815-1915:,2026-10-23,"
    "1793095800,NSE:BANKNIFTY26OCTFUT,10,11,48699,BANKNIFTY,26009,-1.0,XX,101000000026009,None,0,0.0\n"
    "101126102751329,NIFTY 27 Oct 26 22450 PE,14,65,0.05,,0915-1540|1815-1915:,2026-10-23,"
    "1793095800,NSE:NIFTY26OCT22450PE,10,14,51329,NIFTY,26000,22450.0,PE,101000000026000,None,0,0.0\n"
    "garbage,line\n"
)


def test_second_instance_cannot_take_the_lock(tmp_path: Path) -> None:
    path = tmp_path / "live.lock"
    with InstanceLock(path):
        with pytest.raises(LockHeld):
            InstanceLock(path).acquire()
    with InstanceLock(path):  # free again after release
        pass


def test_host_guard() -> None:
    assert host_allowed([], "ANY-PC")
    assert host_allowed(["vps-1", "VPS-2"], "Vps-2")
    assert not host_allowed(["vps-1"], "LAPTOP")


def test_status_file_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "s" / "live_status.json"
    assert read_status(path) is None
    write_status(
        path, Status(day="2026-10-26", state="running", cycles=4), ist(2026, 10, 26, 9, 20)
    )
    data = read_status(path)
    assert data is not None and data["cycles"] == 4
    assert str(data["updated_at"]).startswith("2026-10-26T09:20")
    path.write_text("not json", encoding="utf-8")
    assert read_status(path) is None


def test_targets_and_tier2_file(tmp_path: Path) -> None:
    file = tmp_path / "tier2.csv"
    file.write_text("rank,underlying\n1,RELIANCE\n2,HDFCBANK\n3,TCS\n", encoding="utf-8")
    assert load_tier2_names(file, 2) == ["RELIANCE", "HDFCBANK"]
    assert load_tier2_names(file, 0) == [] and load_tier2_names(tmp_path / "missing.csv", 5) == []
    assert equity_symbol("M&M") == "NSE:M&M-EQ"
    targets = build_targets(LiveConfig(), ["RELIANCE"])
    assert [t.tier for t in targets] == [1, 1, 1, 1, 1, 2]
    assert targets[0].name == "NIFTY" and targets[-1].spot_symbol == "NSE:RELIANCE-EQ"
    assert targets[0].strikecount == 25 and targets[-1].strikecount == 10


def test_capture_config_rules() -> None:
    with pytest.raises(ValidationError, match="multiple"):
        CaptureConfig(tier1_interval_seconds=60, tier2_interval_seconds=90)
    with pytest.raises(ValidationError, match="login_time"):
        CaptureConfig(login_time="10:00:00", capture_start="09:15:00")  # type: ignore[arg-type]
    cfg = CaptureConfig(login_time="08:45:00", capture_start="09:15:00", capture_end="15:30:00")  # type: ignore[arg-type]
    assert cfg.capture_start.hour == 9


def test_contract_master_parsing() -> None:
    frame = parse_symbol_master(MASTER, "NSE_FO")
    assert list(frame.columns) == CONTRACT_MASTER_COLUMNS and len(frame) == 2  # garbage skipped
    future = frame[frame["symbol"] == "NSE:BANKNIFTY26OCTFUT"].iloc[0]
    assert future["lot_size"] == 30 and future["expiry_date"] == date(2026, 10, 27)
    assert future["option_type"] is None and str(future["strike"]) == "nan"
    option = frame[frame["option_type"] == "PE"].iloc[0]
    assert (
        option["strike"] == 22450 and option["lot_size"] == 65 and option["underlying"] == "NIFTY"
    )


class _History:
    def __init__(self, answer: Any) -> None:
        self._answer = answer

    def history(self, data: dict[str, Any]) -> Any:
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def test_market_check_fails_open() -> None:
    today = date(2026, 10, 26)
    assert (
        market_has_traded_today(_History({"s": "ok", "candles": [[1, 2, 3, 4, 5, 6]]}), "S", today)
        is True
    )
    assert market_has_traded_today(_History({"s": "ok", "candles": []}), "S", today) is False
    assert market_has_traded_today(_History({"s": "no_data"}), "S", today) is False
    assert market_has_traded_today(_History({"s": "error", "code": -300}), "S", today) is None
    assert market_has_traded_today(_History(RuntimeError("x")), "S", today) is None
    assert market_has_traded_today(_History("odd"), "S", today) is None


def test_done_marker_roundtrip(tmp_path: Path) -> None:
    from collector.live.status import is_done, write_done

    day = date(2026, 10, 26)
    assert not is_done(tmp_path, day)
    write_done(
        tmp_path,
        day,
        {"cycles": 376, "reason": "capture window finished"},
        ist(2026, 10, 26, 15, 31),
    )
    assert is_done(tmp_path, day) and not is_done(tmp_path, date(2026, 10, 27))
