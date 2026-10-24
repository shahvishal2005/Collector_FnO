# What: the day-0 Fyers probe: read-only market-data calls whose raw answers are saved.
# In: a logged-in Fyers client, the live config, an output folder and today's date.
# Out: raw JSON files, summary.json and PROBE_REPORT.md (field names, symbol formats, latencies).
"""Day-0 exploration of the Fyers market-data API.

Only market-data endpoints are used (option chain, quotes, depth, history, public symbol masters).
The profile answer is never saved because it contains personal details; only its status is kept.
Every call is wrapped so one failure never stops the probe: failures are results too.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

from collector.config.schema import LiveConfig

log = logging.getLogger(__name__)
_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
_FUT_PATTERN = re.compile(r"^(?P<ex>[A-Z]+):(?P<und>[A-Z]+)(?P<yy>\d{2})(?P<mon>[A-Z]{3})FUT$")
_OPT_PATTERN = re.compile(
    r"^(?P<ex>[A-Z]+):(?P<und>[A-Z]+)(?P<yy>\d{2})(?P<mon>[A-Z]{3})(?P<strike>\d+)(?P<cp>CE|PE)$"
)


@dataclass
class CallRecord:
    """The outcome of one probe call."""

    name: str
    seconds: float
    ok: bool
    status: str | None = None  # Fyers' 's' field
    code: int | None = None
    message: str | None = None
    error: str | None = None  # exception type name only
    file: str | None = None
    notes: dict[str, Any] = field(default_factory=dict)


def previous_month(yy: int, mon: str) -> tuple[int, str]:
    """The (two-digit year, month abbreviation) one month before the given one."""
    index = _MONTHS.index(mon)
    if index == 0:
        return (yy - 1) % 100, _MONTHS[11]
    return yy, _MONTHS[index - 1]


def expired_variant(symbol: str) -> str | None:
    """Turn a live monthly future/option symbol into the same contract one month earlier."""
    match = _FUT_PATTERN.match(symbol)
    if match:
        yy, mon = previous_month(int(match["yy"]), match["mon"])
        return f"{match['ex']}:{match['und']}{yy:02d}{mon}FUT"
    match = _OPT_PATTERN.match(symbol)
    if match:
        yy, mon = previous_month(int(match["yy"]), match["mon"])
        return f"{match['ex']}:{match['und']}{yy:02d}{mon}{match['strike']}{match['cp']}"
    return None


def find_symbols(
    master_text: str, pattern: re.Pattern[str], underlying: str, limit: int
) -> list[str]:
    """Scan every field of a symbol master for symbols matching a pattern for one underlying."""
    found: list[str] = []
    for row in csv.reader(io.StringIO(master_text)):
        for cell in row:
            match = pattern.match(cell)
            if match and match["und"] == underlying and cell not in found:
                found.append(cell)
                break
        if len(found) >= limit:
            break
    return found


def summarize_chain(response: dict[str, Any]) -> dict[str, Any]:
    """Describe an option-chain answer: top-level keys, row counts and the fields of a row."""
    data = response.get("data")
    summary: dict[str, Any] = {"top_level_keys": sorted(response.keys())}
    if not isinstance(data, dict):
        return summary
    summary["data_keys"] = sorted(data.keys())
    rows = data.get("optionsChain")
    if isinstance(rows, list):
        summary["row_count"] = len(rows)
        keys: set[str] = set()
        for row in rows:
            if isinstance(row, dict):
                keys.update(row.keys())
        summary["row_fields"] = sorted(keys)
        summary["option_types"] = sorted(
            {str(r.get("option_type")) for r in rows if isinstance(r, dict)}
        )
        strikes = {r.get("strike_price") for r in rows if isinstance(r, dict)}
        summary["distinct_strikes"] = len([s for s in strikes if s not in (None, -1)])
    expiries = data.get("expiryData")
    if isinstance(expiries, list):
        summary["expiry_count"] = len(expiries)
        summary["expiry_sample"] = expiries[:3]
    return summary


def second_expiry(response: dict[str, Any]) -> str | None:
    """The epoch (as text) of the second listed expiry in an option-chain answer, if any."""
    data = response.get("data")
    expiries = data.get("expiryData") if isinstance(data, dict) else None
    if isinstance(expiries, list) and len(expiries) >= 2 and isinstance(expiries[1], dict):
        value = expiries[1].get("expiry")
        return str(value) if value else None
    return None


def pick_option_symbol(response: dict[str, Any]) -> str | None:
    """The first call/put symbol found in an option-chain answer."""
    data = response.get("data")
    rows = data.get("optionsChain") if isinstance(data, dict) else None
    if isinstance(rows, list):
        for row in rows:
            if (
                isinstance(row, dict)
                and row.get("option_type") in ("CE", "PE")
                and row.get("symbol")
            ):
                return str(row["symbol"])
    return None


class Probe:
    """Runs and records probe calls."""

    def __init__(
        self,
        client: Any,
        cfg: LiveConfig,
        out_dir: Path,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        http_get: Callable[..., Any] = requests.get,
    ) -> None:
        """Keep the client, settings and output folder."""
        self._client = client
        self._cfg = cfg
        self._out = out_dir
        self._sleep = sleep
        self._clock = clock
        self._http_get = http_get
        self.records: list[CallRecord] = []
        out_dir.mkdir(parents=True, exist_ok=True)

    def _save(self, name: str, payload: Any) -> str:
        """Write a raw answer next to the report and return its file name."""
        file_name = f"{name}.json"
        (self._out / file_name).write_text(
            json.dumps(payload, indent=1, default=str), encoding="utf-8"
        )
        return file_name

    def call(
        self, name: str, func: Callable[..., Any], *, save: bool = True, **kwargs: Any
    ) -> tuple[CallRecord, dict[str, Any] | None]:
        """Run one API call, time it, save the raw answer, and never raise."""
        started = self._clock()
        response: dict[str, Any] | None = None
        record = CallRecord(name=name, seconds=0.0, ok=False)
        try:
            raw = func(**kwargs)
            if isinstance(raw, dict):
                response = raw
                record.status = str(raw.get("s")) if raw.get("s") is not None else None
                code = raw.get("code")
                record.code = (
                    int(code)
                    if isinstance(code, int | float | str) and str(code).lstrip("-").isdigit()
                    else None
                )
                message = raw.get("message")
                record.message = str(message)[:200] if message else None
                record.ok = record.status in ("ok", None) and (
                    record.code is None or record.code == 200
                )
                if save:
                    record.file = self._save(name, raw)
        except Exception as exc:  # the SDK raises many kinds of errors; all become results
            record.error = type(exc).__name__
        record.seconds = round(self._clock() - started, 3)
        self.records.append(record)
        log.info(
            "%s: ok=%s status=%s code=%s %.2fs",
            name,
            record.ok,
            record.status,
            record.code,
            record.seconds,
        )
        self._sleep(self._cfg.probe_call_gap_seconds)
        return record, response

    def download_master(self, label: str, url: str) -> str | None:
        """Download one public symbol master and save it; return the text or None."""
        started = self._clock()
        record = CallRecord(name=f"symbol_master_{label}", seconds=0.0, ok=False)
        text: str | None = None
        try:
            response = self._http_get(url, timeout=60)
            record.code = int(response.status_code)
            if response.status_code == 200:
                text = response.text
                (self._out / f"symbol_master_{label}.csv").write_text(text, encoding="utf-8")
                record.file = f"symbol_master_{label}.csv"
                record.ok = True
                record.notes = {"lines": text.count("\n"), "first_lines": text.splitlines()[:3]}
        except Exception as exc:
            record.error = type(exc).__name__
        record.seconds = round(self._clock() - started, 3)
        self.records.append(record)
        return text

    def run(self, today: date) -> list[CallRecord]:
        """Execute the whole probe."""
        self.call("profile_status_only", self._client.get_profile, save=False)
        masters = {
            label: self.download_master(label, url)
            for label, url in self._cfg.symbol_master_urls.items()
        }
        chain_symbol_for: dict[str, str | None] = {}
        expiries_for: dict[str, str | None] = {}
        spots = [u.spot_symbol for u in self._cfg.tier1]
        for under in self._cfg.tier1:
            for count in self._cfg.probe_strike_counts:
                record, response = self.call(
                    f"optionchain_{under.name}_{count}",
                    self._client.optionchain,
                    data={"symbol": under.spot_symbol, "strikecount": count, "timestamp": ""},
                )
                if response is not None:
                    record.notes = summarize_chain(response)
                    chain_symbol_for.setdefault(under.name, pick_option_symbol(response))
                    if count == min(self._cfg.probe_strike_counts):
                        expiries_for[under.name] = second_expiry(response)
        for under in self._cfg.tier1:  # a later expiry is addressed by its epoch as `timestamp`
            epoch = expiries_for.get(under.name)
            if epoch:
                record, response = self.call(
                    f"optionchain_{under.name}_expiry2",
                    self._client.optionchain,
                    data={
                        "symbol": under.spot_symbol,
                        "strikecount": min(self._cfg.probe_strike_counts),
                        "timestamp": epoch,
                    },
                )
                if response is not None:
                    record.notes = {
                        **summarize_chain(response),
                        "sample_symbols": [
                            r.get("symbol")
                            for r in response.get("data", {}).get("optionsChain", [])[:3]
                        ],
                    }
        self.call("quotes_spots", self._client.quotes, data={"symbols": ",".join(spots)})
        first = self._cfg.tier1[0]
        sample = chain_symbol_for.get(first.name)
        range_to = today
        range_from = today - timedelta(days=self._cfg.probe_history_days + 4)
        history_args = {
            "resolution": "1", "date_format": "1", "range_from": range_from.isoformat(),
            "range_to": range_to.isoformat(), "cont_flag": "1", "oi_flag": "1",
        }  # fmt: skip
        if sample:
            self.call("quotes_option_sample", self._client.quotes, data={"symbols": sample})
            self.call(
                "depth_option_sample",
                self._client.depth,
                data={"symbol": sample, "ohlcv_flag": "1"},
            )
            rec, resp = self.call(
                "history_option_sample",
                self._client.history,
                data={"symbol": sample, **history_args},
            )
            if resp is not None:
                candles = resp.get("candles")
                rec.notes = {
                    "candle_count": len(candles) if isinstance(candles, list) else None,
                    "first_candle": candles[0] if isinstance(candles, list) and candles else None,
                    "values_per_candle": (
                        len(candles[0]) if isinstance(candles, list) and candles else None
                    ),
                }
        # expired contracts: build the same contract one month earlier from the live symbol master
        nse_master = masters.get("NSE_FO")
        if nse_master:
            futs = find_symbols(nse_master, _FUT_PATTERN, first.name, 1)
            opts = find_symbols(nse_master, _OPT_PATTERN, first.name, 1)
            for kind, symbols in (("future", futs), ("option", opts)):
                if symbols:
                    expired = expired_variant(symbols[0])
                    if expired:
                        rec, resp = self.call(
                            f"history_expired_{kind}",
                            self._client.history,
                            data={"symbol": expired, **history_args},
                        )
                        rec.notes = {
                            "symbol_tried": expired,
                            "candle_count": len(resp.get("candles", [])) if resp else None,
                        }
        for index in range(self._cfg.probe_latency_calls):
            self.call(
                f"latency_optionchain_{index:02d}",
                self._client.optionchain,
                save=False,
                data={
                    "symbol": first.spot_symbol,
                    "strikecount": min(self._cfg.probe_strike_counts),
                    "timestamp": "",
                },
            )
        self._write_reports()
        return self.records

    def _write_reports(self) -> None:
        """summary.json (machine-readable) and PROBE_REPORT.md (for people)."""
        (self._out / "summary.json").write_text(
            json.dumps([asdict(r) for r in self.records], indent=1, default=str), encoding="utf-8"
        )
        latencies = [r.seconds for r in self.records if r.name.startswith("latency_")]
        lines = [
            "# Fyers day-0 probe report",
            "",
            "| call | ok | status | code | seconds | note |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for r in self.records:
            note = r.error or r.message or ""
            lines.append(
                f"| {r.name} | {r.ok} | {r.status} | {r.code} | {r.seconds} | {note[:80]} |"
            )
        if latencies:
            ordered = sorted(latencies)
            lines += [
                "",
                f"Latency over {len(ordered)} sequential option-chain calls: min {ordered[0]}s,"
                f" median {ordered[len(ordered) // 2]}s, max {ordered[-1]}s.",
            ]
        failed_limits = [r for r in self.records if r.code == 429]
        lines += ["", f"Rate-limit answers (429): {len(failed_limits)}"]
        (self._out / "PROBE_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
