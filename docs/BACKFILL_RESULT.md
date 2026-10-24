# F&O bhavcopy backfill: result (completed 2026-10-24)

Command: `python scripts/backfill_fo.py` (range 2017-10-24 to 2026-10-23, 1.5 s between requests).
Run time: about 1 hour 55 minutes including two download stalls that recovered on retry.

## Headline
| Item | Value |
|---|---|
| Trading days stored | **2,225** (2017-10-24 to 2026-10-23) |
| Contract rows | 100,108,382 (98,838,703 are options) |
| Source formats used | 1,655 days old format, 570 days new format; 3 overlap days compared |
| Disk | raw files 1.6 GB, clean Parquet 1.3 GB |
| Parse errors / network failures that stopped the run | 0 / 0 |
| Quality issues | **0 errors, 1 warning**, 2 kinds of info notes |
| Manifest check | `OK: all silver files match the manifest` |
| Old vs new format on 2024-07-03..05 | identical (33,216 contracts per day) |

## Coverage against the research platform's Nifty trading days
- **1 missing day: 2021-03-30.** The Nifty candles show a session, but NSE's archive answers 404
  for that day's file on both archive hosts (29 Mar 2021 was a holiday; 31 Mar exists). This is a
  gap at the source, recorded here. If the day matters, another source is needed.
- **127 days with no file** are weekdays that were holidays (404), consistent with the calendar.
- **11 "extra" days** have a file but no Nifty candles. Eight of them are days the research
  platform deliberately removed from its clean data (2018-02-08, 2019-12-06, 2020-03-13,
  2020-03-23, 2021-02-24, 2021-08-05, 2021-11-04, 2025-10-21: special sessions, circuit-breaker
  days, an NSE outage). The other three (2018-11-07, 2022-10-24, 2024-11-01) are Diwali Muhurat
  sessions. So the F&O files cover these sessions even though the candles do not.

## What the data showed (and how the checks were set)
- **F&O universe size varied from 138 to 232 underlyings a day** (median about 143 in 2020, about
  215 in 2026). The first check floor of 150 wrongly flagged 293 days, so the floor was lowered to
  100 (a guard against truncated files); sudden changes are caught by the row-count jump check.
- **Stock-futures `close` equals the settlement price** on every one of the 2,004 rows where the
  close fell outside the day's low/high (thin trading, many with 5 contracts or fewer; median
  distance 0.26% of price, largest 11%). This is how NSE reports those contracts. It is recorded
  as info (`SETTLEMENT_CLOSE_OUTSIDE_RANGE`), not as an error.
- **1,009 rows on 562 days have open/high/low = 0 with volume** (spread-type trades): info
  (`ZERO_OHLC_WITH_VOLUME`). Use close or settlement for those rows.
- **One real warning:** 2018-10-29, one contract with a close outside its range and a close that
  differs from settlement. One row; left as is for the record.

## Robustness fix made after this run
Two downloads stalled for several minutes (a response trickled in slowly, then the connection
broke). The client now reads in chunks with a total limit per file (`nse.total_timeout_seconds`,
default 120 s), so a stalled file is abandoned and retried quickly. Covered by a test.

## Not covered by this backfill
Participant-wise OI, F&O ban lists, index closes, equity bhavcopy with delivery quantity and
corporate-action adjustments are separate milestones (M3 and M4 in `plan_details/COLLECTOR_PLAN.md`).
Prices here are unadjusted for splits and bonuses.
