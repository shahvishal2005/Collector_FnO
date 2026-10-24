# 0001: Project scope and first choices (2026-10-24)

Decided with the owner.

1. **Separate project** named `india-fno-collector`, independent from the research platform
   (`Fyers_ORB_Agent`). It runs on its own, is deployed on the Windows VPS in production, and
   exposes versioned Parquet files that other projects read read-only.
2. **Read-only data collection.** No order placement of any kind, enforced by a test.
3. **First deliverable: NSE archive backfill (milestones M0 to M2)** because it needs no broker
   login and gives years of F&O history. The live Fyers pilot is designed in parallel
   (`PILOT_DESIGN.md`) and built next.
4. **Tier 1 underlyings for live capture:** Nifty 50, Bank Nifty, Fin Nifty, Midcap Nifty and
   Sensex (the owner asked for Sensex to be included). Configurable.
5. **Tier 2 stocks:** derived from the backfill data (option activity ranking), not hand-picked.
6. **Data location:** inside this project under `data/` (git-ignored), Parquet files, with raw
   files kept as downloaded. Whether and how the research platform gets a copy is decided later.
7. **Alerts (Telegram and email):** wanted, built last.
8. **Environment:** Python 3.11 with the same pinned package versions as the research platform's
   `.venv-alt`, to avoid Windows Smart App Control blocking new builds.
9. **Quality bar copied from the research platform:** one config file, unknown keys rejected,
   header comment on every file, tests with the code, docs updated in the same change, and a
   quality gate (`scripts/run_all.py`).
10. **Politeness toward NSE:** one connection, 1.5 s between requests, retries with backoff, abort
    after repeated errors, browser-like User-Agent. Personal research use only.

## Facts established while building M1 (probe of the live archive, 2026-10-24)
- Old-format files exist from 2005 to 2024-07-05; new-format files from 2024-07-03 to today.
- On 2024-07-03..05 both exist and carry identical contracts, prices, volume and open interest
  (turnover differs only by the old file's lakh rounding).
- A 404 means holiday or no file; a 200 that is not a zip file means a block page and is an error.
- Volume is in contracts (lots); open interest is in units; old turnover is in lakh rupees.
