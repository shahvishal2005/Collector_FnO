# Changelog

## 0.1.0 (2026-10-24)
- M0: project skeleton, validated config, logging, retry, rate limiter, quality gate, no-order guard.
- M1: NSE F&O bhavcopy downloader (old and new formats), parsers, normalisation to the `fo_eod`
  schema, Parquet storage with atomic writes, SQLite download catalogue.
- M2: resumable backfill job, manifest with checksum check, quality checks, coverage analysis
  against the Nifty trading days, old/new format overlap comparison, report generation.
- Tier 2 proposal: `scripts/derive_tier2.py` ranks stock options by premium turnover over the
  latest stored days (config section `universe`).
- Fyers login ported from the research platform (TOTP login, token store, secrets loader) with its
  tests; day-0 read-only probe (`scripts/probe_fyers.py`) and its findings (`docs/PROBE_FINDINGS.md`).
- Full F&O backfill completed 2026-10-24 (2,225 days, 0 errors; see `docs/BACKFILL_RESULT.md`).
- Downloads now have a total time limit (`nse.total_timeout_seconds`); stalled files are retried.
- Quality checks tuned from real data: universe floor 100; settlement-close quirk reported as info.
- Live option-chain scheduler for the VPS (M5): one cycle per minute for indices, stocks every five
  minutes, restart-safe time grid, single-instance lock, host guard, health logs, status file,
  Windows Task Scheduler install script. See `docs/VPS_LIVE.md`.
- Docs: README, SCHEMAS, RUNBOOK, PILOT_DESIGN, decision 0001.
