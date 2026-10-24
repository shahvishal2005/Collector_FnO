# Changelog

## 0.1.0 (2026-10-24)
- M0: project skeleton, validated config, logging, retry, rate limiter, quality gate, no-order guard.
- M1: NSE F&O bhavcopy downloader (old and new formats), parsers, normalisation to the `fo_eod`
  schema, Parquet storage with atomic writes, SQLite download catalogue.
- M2: resumable backfill job, manifest with checksum check, quality checks, coverage analysis
  against the Nifty trading days, old/new format overlap comparison, report generation.
- Tier 2 proposal: `scripts/derive_tier2.py` ranks stock options by premium turnover over the
  latest stored days (config section `universe`).
- Docs: README, SCHEMAS, RUNBOOK, PILOT_DESIGN, decision 0001.
