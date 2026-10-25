# india-fno-collector

Market-data collector for Indian F&O. Personal research use.

- **Pipeline A (built and run): NSE archive backfill.** 2,225 trading days, 2017-10-24 to 2026-10-23. Downloads the exchange's public end-of-day F&O
  files (futures and options on indices and stocks, with open interest), keeps the raw files,
  and writes clean, versioned Parquet tables with a manifest and a quality report.
- **Pipeline B (built, awaiting its first trading day): live Fyers option-chain capture,** run on the
  VPS by Windows Task Scheduler. See `docs/VPS_LIVE.md` (set-up) and `docs/PILOT_DESIGN.md` (goals).

This project **never places orders**. A test (`tests/test_no_order_api.py`) fails if order-related
calls ever appear in the code. It only reads data. It is separate from the research platform
(`Fyers_ORB_Agent`), which reads this project's Parquet files read-only.

## Quick start (Windows)

```
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install numpy==2.4.6 pandas==2.3.3 pyarrow==20.0.0 pydantic==2.14.1 pyyaml==6.0.3 requests==2.31.0 tzdata==2026.5
.venv\Scripts\python -m pip install pytest==9.1.1 ruff==0.17.1 black==26.10.1 mypy==2.4.0 types-PyYAML types-requests "pandas-stubs<2.4"
.venv\Scripts\python -m pip install --no-deps -e .
copy config\config.example.yaml config\config.yaml
.venv\Scripts\python scripts\run_all.py          # ruff, black, mypy, pytest
```

(The pins match the research platform's `.venv-alt`, because Windows Smart App Control blocks some
brand-new package builds.)

## Everyday commands

| Task | Command |
|---|---|
| Backfill everything missing, then manifest and report | `python scripts\backfill_fo.py` |
| Try a short range first | `python scripts\backfill_fo.py --start 2024-06-28 --end 2024-07-12` |
| Retry days NSE said "not found" | `python scripts\backfill_fo.py --recheck-missing` |
| Rebuild the clean tables from the raw files (no network) | `python scripts\backfill_fo.py --reprocess` |
| Rebuild manifest and report only | `python scripts\report_fo.py` |
| Prove the data matches its manifest | `python scripts\check_manifest.py` |
| Live capture for today (VPS; started by Task Scheduler) | `python scripts\run_live.py` |
| Check how the live capture is doing | `python scripts\live_status.py` |
| Propose the Tier 2 stock list from stored option data | `python scripts\derive_tier2.py` |
| Quality gate (run after every change) | `python scripts\run_all.py` |

## Where things are

```
config/            config.example.yaml (copy to config.yaml; unknown keys are rejected)
src/collector/     common/ config/ nse/ normalise/ store/ quality/ jobs/
scripts/           command line entry points
tests/             fixtures are small real excerpts of NSE files
docs/              SCHEMAS.md, RUNBOOK.md, PILOT_DESIGN.md, decisions/
data/              (git-ignored)
  bronze/          raw downloads exactly as served + catalogue.sqlite
  silver/fo_eod/   one Parquet file per trade day (trade_date=YYYY-MM-DD/part-0.parquet)
  manifests/       per-day fingerprints
  reports/         coverage, issues and format-overlap reports
```

## Rules this project follows

Raw files are never modified. Every run is resumable and idempotent. Gaps are reported, never
filled. Timestamps are timezone-aware IST. Every threshold lives in the config. Nothing is pushed
to Git without the owner's say-so. Secrets (for the later Fyers part) live only in `.env`.

Data source terms: the NSE files are public archive downloads used at a polite rate (one request
every 1.5 s by default) for personal research. Check NSE's terms before any other use.
