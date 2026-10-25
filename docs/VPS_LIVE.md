# Live capture on the VPS

The live scheduler is built for the **Windows VPS**, running unattended. It must not run on the
laptop (it would compete with the VPS for the same Fyers rate limit). `live.allowed_hosts` in
`config\config.yaml` enforces this: set it to the VPS computer name and the scheduler refuses to
start anywhere else (override only with `--force`).

## What it does each weekday
1. Windows Task Scheduler starts `scripts\run_live.py` at 08:40.
2. It waits for `login_time` (08:45), logs in (automatic TOTP login; never opens a browser),
   and saves the day's contract list (lot sizes, expiries, strikes) from Fyers' public symbol masters.
3. From 09:15 it checks that the market actually traded today (spot candles exist). Only after
   `market_check_slots` (default 10) minutes with no candles does it call the day a holiday and exit
   with code 0. An unclear answer never stops the day (it fails open).
4. Every minute (`tier1_interval_seconds`) it captures the option chains of the five indices
   (nearest 3 expiries, 25 strikes each side). Every fifth minute it also captures the Tier 2
   stocks (nearest expiry, 10 strikes each side).
5. At 15:30 it stops, exits, and writes `data\live_done\DATE.json`. Task Scheduler launches it
   again every 5 minutes until 15:40: a launch on a finished day exits at once, and a launch while
   it is running is refused by the lock. If it crashed or the VPS restarted mid-day, the next
   launch (within 5 minutes) **joins the next minute on the same time grid**; a slot missed by a
   slow cycle is skipped and counted, never queued. The contract lists are downloaded once a day.
6. Nothing is ever filled in: a failed call is a row in the health log.

Protections: one copy at a time (OS file lock), host guard, rate-limit pause (30 s), one automatic
re-login per cycle on an authentication answer, abort after 5 empty cycles in a row (exit code 1,
Task Scheduler restarts it up to 20 times). It only calls market-data endpoints; the project's
test fails if order-related code ever appears.

## Where the data goes (under `data\`)
| Path | Content |
|---|---|
| `bronze\fyers_chain\trade_date=DATE\cycle_HHMMSS.jsonl.gz` | every raw answer of a cycle, compressed |
| `silver\option_chain\trade_date=DATE\cycle_HHMMSS.parquet` | clean rows, one file per cycle |
| `silver\live_health\trade_date=DATE\calls.csv` / `cycles.csv` | every call and every cycle (gaps are visible here) |
| `silver\contract_master\trade_date=DATE\contracts_NSE_FO.parquet` (and `_BSE_FO`) | lot sizes, expiries, strikes |
| `bronze\fyers_symbol_master\trade_date=DATE\*.csv.gz` | the raw contract lists |
| `live_status.json`, `live.lock`, `live_done\DATE.json` | current status, single-instance lock, day-complete marker |

Estimates (to be confirmed by the first days): about 700,000 rows a day, roughly 40 MB a day of
compressed raw answers plus clean files, so about 10 GB a year.

Call budget: about 15 calls a minute for the indices, plus 40 more every fifth minute for stocks
(from the VPS a call takes about 0.16 s plus the 0.25 s politeness gap, so a full cycle is well under
a minute). All of it is configurable in `live.capture` (config.example.yaml).

## Set up on the VPS (once)
1. `git pull` in the project folder.
2. Update `config\config.yaml` (it is local and git-ignored): back it up, copy
   `config\config.example.yaml` over it, then set `paths.nifty_candles_root: ""` and
   `live.allowed_hosts: ["<this computer's name>"]` (get the name with `hostname`).
3. `.venv\Scripts\python scripts\run_all.py` must pass.
4. `.venv\Scripts\python scripts\derive_tier2.py` writes `data\reports\tier2_candidates.csv`
   (the Tier 2 stock list). Review it; edit `live.capture.tier2_limit` if you want fewer or more.
5. Test outside market hours (writes to `data\_test`, nothing real is touched):
   `.venv\Scripts\python scripts\run_live.py --test --ignore-hours --max-cycles 2`
   then `.venv\Scripts\python scripts\live_status.py --test`.
6. Register the scheduled task **from an elevated PowerShell** (Run as administrator):
   `powershell -ExecutionPolicy Bypass -File deploy\windows\install_tasks.ps1`
   Check it: `Get-ScheduledTask -TaskName FnOCollector-Live | Get-ScheduledTaskInfo`.

## Watching it
- `.venv\Scripts\python scripts\live_status.py` prints today's cycles, failures by kind, slowest
  call, rate-limit answers and a verdict. CHECK lists the problems: missing cycles, many failed
  calls, a stall (no cycle for 3+ minutes while the run says 'running'), a late start, or an early
  stop. Exit code 1 means CHECK. A short test run is judged against its own span, not a full day.
- `logs\run_live_YYYYMMDD.log` has the details.
- To force a re-run of a day already marked complete, delete `data\live_done\DATE.json`.

## Stopping and removing
Stop for the day: `Stop-ScheduledTask -TaskName FnOCollector-Live`. Remove:
`deploy\windows\uninstall_tasks.ps1` (elevated).

## Not built yet
End-of-day candle pull for live contracts (the hook exists: `after_close`), futures/depth capture,
and Telegram/email alerts (last, as requested).
