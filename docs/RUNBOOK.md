# Runbook

## Normal run
`python scripts\backfill_fo.py` downloads every missing day from `backfill.start_date` to
yesterday, then rebuilds the manifest and the report. It can be stopped (Ctrl+C) and restarted at
any time: finished days are skipped.

Expected duration for the full 2017-10 to today range: about 1.5 hours at the default throttle.
The laptop must not sleep during the run (Settings > Power: never sleep while plugged in).

## Reading the result
1. `data/reports/fo_eod_report.md`: headline numbers and coverage by year.
2. `data/reports/fo_eod_issues.csv`: every finding, by day and check.
3. `data/reports/fo_eod_missing_extra_days.csv`: trading days with no file / files on non-trading days.
4. `data/reports/fo_overlap_compare.csv`: old vs new format on the overlap days (should be identical).
5. `python scripts\check_manifest.py` should print `OK`.

Severity: **error** = must be understood before using the day; **warn** = look at it; **info** =
a known exchange quirk, recorded for transparency.

## When things go wrong
| Symptom | Meaning | Action |
|---|---|---|
| `aborting after N consecutive errors` | Network down, or NSE is blocking or rate limiting | Wait, then re-run; if it repeats, raise `nse.min_interval_seconds` |
| `HTTP 200 but not a zip file` | NSE sent a block or error page | Same as above; never treated as a holiday |
| Parse error for one day | Format changed or file damaged | Open the file in `data/bronze/nse_fo/<year>/`; fix the parser; re-run with `--reprocess` |
| Missing days in the report | Holiday not in Nifty candles, or NSE lacks the file | Re-run with `--recheck-missing`; keep a note of days NSE truly lacks |
| Manifest check fails | A silver file changed after the manifest was written | Rebuild with `python scripts\report_fo.py` only if the change was intended |

## Rebuild the clean tables without the network
`python scripts\backfill_fo.py --reprocess`. Raw files in `data/bronze` are the source of truth.

## Backups
Back up `data/bronze` and `data/silver` and `data/manifests` offsite after the first full run and
then weekly. The NSE archive can be re-downloaded, but the catalogue and manifests record exactly
what was used. (Fyers' own history floor moves daily, so the research platform's raw candles are
the item that truly cannot be re-created; that is a separate project.)

## Quality gate
Run `python scripts\run_all.py` after every change: ruff, black, mypy (strict) and pytest must pass.
