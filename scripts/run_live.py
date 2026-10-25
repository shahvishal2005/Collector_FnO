# What: the live capture for one trading day (started by Task Scheduler on the VPS).
# In: optional --test/--ignore-hours/--max-cycles/--force/--config. Out: capture files, logs.
"""Run the live option-chain capture (market-data calls only; it cannot place orders).

Exit codes: 0 finished or market closed; 1 aborted (Task Scheduler restarts it); 2 bad config or
credentials; 3 another instance is running; 4 this computer is not allowed to run it.
"""

from __future__ import annotations

import argparse
import gzip
import logging
import socket
import sys
from pathlib import Path
from typing import Any

import requests

from collector.common.logsetup import setup_logging
from collector.common.timeutil import today_ist
from collector.config import ConfigError, load_config
from collector.fyers.auth import login_with_totp
from collector.fyers.errors import AuthError
from collector.fyers.secrets import load_secrets
from collector.fyers.session import build_client, get_access_token
from collector.fyers.token_store import save_token
from collector.live.capture import ChainCollector
from collector.live.clock import SystemClock
from collector.live.host import host_allowed
from collector.live.lock import InstanceLock, LockHeld
from collector.live.market import market_has_traded_today
from collector.live.runner import RunOptions, run_day
from collector.live.status import is_done, write_done
from collector.live.targets import build_targets, load_tier2_names
from collector.normalise.contract_master import CONTRACT_MASTER_SCHEMA, parse_symbol_master
from collector.store.layout import Layout
from collector.store.parquet import write_atomic_bytes, write_table

log = logging.getLogger("run_live")


def main() -> int:
    """Set everything up and run the day."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--test", action="store_true", help="write under data/_test, not the real folders"
    )
    parser.add_argument(
        "--ignore-hours", action="store_true", help="capture now, outside market hours"
    )
    parser.add_argument("--max-cycles", type=int, default=None, help="stop after this many cycles")
    parser.add_argument("--force", action="store_true", help="ignore the allowed-host list")
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
        secrets = load_secrets()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    setup_logging(cfg.paths.logs_root, "run_live")
    if not args.force and not host_allowed(cfg.live.allowed_hosts):
        log.error(
            "this computer (%s) is not in live.allowed_hosts; refusing to run", socket.gethostname()
        )
        return 4
    data_root = cfg.paths.data_root / "_test" if args.test else cfg.paths.data_root
    layout = Layout(data_root)
    today = today_ist()
    clock = SystemClock()
    holder: dict[str, Any] = {}
    real_day = not args.test and not args.ignore_hours
    if real_day and is_done(data_root, today):
        log.info("today's capture is already complete; nothing to do")
        return 0

    def login(force: bool) -> None:
        """Log in (reusing a valid token unless forced) and keep the client."""
        if force:
            token = login_with_totp(secrets)
            save_token(token, cfg.live.token_path)
        else:
            token = get_access_token(secrets, cfg.live.token_path, allow_browser=False)
        holder["client"] = build_client(secrets, token, cfg.live.sdk_log_dir)

    def before_open() -> None:
        """Log in and save today's contract list (the list is nice to have; login is essential)."""
        login(False)
        for label, url in cfg.live.symbol_master_urls.items():
            target = layout.contract_master_file(today).with_name(f"contracts_{label}.parquet")
            if target.is_file():
                continue  # already saved today (a restart); do not download it again
            try:
                response = requests.get(url, timeout=60)
                response.raise_for_status()
                write_atomic_bytes(
                    layout.contract_master_raw(today, label), gzip.compress(response.content)
                )
                frame = parse_symbol_master(response.text, label)
                write_table(frame, CONTRACT_MASTER_SCHEMA, target)
                log.info("contract master %s: %d contracts", label, len(frame))
            except (requests.RequestException, OSError) as exc:
                log.warning("contract master %s not saved (%s)", label, type(exc).__name__)

    tier2 = load_tier2_names(cfg.live.capture.tier2_file, cfg.live.capture.tier2_limit)
    targets = build_targets(cfg.live, tier2)
    log.info("targets: %d (tier 1: %d, tier 2: %d)", len(targets), len(cfg.live.tier1), len(tier2))
    collector = ChainCollector(
        today, cfg.live.capture, layout, clock, lambda: holder["client"], lambda: login(True)
    )
    options = RunOptions(ignore_hours=args.ignore_hours, max_cycles=args.max_cycles)
    try:
        with InstanceLock(data_root / "live.lock"):
            summary = run_day(
                cfg.live.capture, collector, targets, clock=clock, today=today, options=options,
                check_market=lambda: market_has_traded_today(
                    holder["client"], cfg.live.tier1[0].spot_symbol, today
                ),
                before_open=before_open,
                status_path=data_root / "live_status.json",
            )  # fmt: skip
    except LockHeld as exc:
        log.error("%s", exc)
        return 3
    except AuthError as exc:
        log.error("login failed: %s", exc)
        return 1
    log.info("finished: %s", summary)
    if real_day and not summary.aborted:
        write_done(
            data_root, today, {"cycles": summary.cycles, "reason": summary.reason}, clock.now()
        )
    return 1 if summary.aborted else 0


if __name__ == "__main__":
    sys.exit(main())
