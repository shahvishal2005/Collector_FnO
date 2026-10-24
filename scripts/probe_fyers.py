# What: day-0 probe of the Fyers market-data API (read-only); saves raw answers for study.
# In: optional --interactive (allow browser login) / --config / --day. Out: data/probe/<time>/.
"""Run the day-0 Fyers probe. Needs the Fyers variables in this project's .env (never printed)."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from collector.common.logsetup import setup_logging
from collector.common.timeutil import now_ist, today_ist
from collector.config import ConfigError, load_config
from collector.fyers.errors import AuthError
from collector.fyers.probe import Probe
from collector.fyers.secrets import load_secrets
from collector.fyers.session import build_client, get_access_token

log = logging.getLogger("probe_fyers")


def main() -> int:
    """Log in (reusing a valid token), run the probe, print where the report is."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--interactive", action="store_true", help="allow the browser login fallback"
    )
    args = parser.parse_args()
    try:
        cfg = load_config(args.config)
        secrets = load_secrets()
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        return 2
    setup_logging(cfg.paths.logs_root, "probe_fyers")
    try:
        token = get_access_token(secrets, cfg.live.token_path, allow_browser=args.interactive)
    except AuthError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return 3
    client = build_client(secrets, token, cfg.live.sdk_log_dir)
    out_dir = cfg.paths.data_root / "probe" / f"{now_ist():%Y%m%d_%H%M%S}"
    probe = Probe(client, cfg.live, out_dir)
    records = probe.run(today_ist())
    ok = sum(1 for r in records if r.ok)
    print(f"{ok}/{len(records)} calls ok. Report: {out_dir / 'PROBE_REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
