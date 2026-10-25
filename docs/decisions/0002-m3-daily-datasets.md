# 0002: M3 daily datasets: choices made (2026-10-25)

Datasets: participant-wise open interest, participant-wise volume, F&O ban list, index close.

1. **One generic framework** (`datasets/`, `jobs/backfill_daily.py`, `quality/daily_report.py`,
   `store/dataset_manifest.py`) instead of four copies of the F&O job. A dataset is a URL rule, a
   parser, a schema and a check. Adding M4's equity files later means adding one definition.
2. **Plain text downloads.** The client learned `fetch_file(url, kind)`: a 200 answer that is empty
   or an HTML page is an error, never a holiday (same safety as for zip files).
3. **Tidy participant tables** (one row per client type and category) so the data can be filtered
   and summed without reshaping.
4. **Empty table for a no-ban day**, so "nobody banned" is distinguishable from "no file".
5. **Date is read from inside each file** and must equal the requested date; a mismatch is a parse
   error for that day.
6. **Integrity checks tuned on real data.** The first version required participant rows to add up to
   TOTAL exactly; real data (2026-10-23) was off by 1 contract on two categories because NSE rounds
   each row. Tolerance is 2 contracts; anything larger is an error.
7. **Report limits.** Black wraps code at 100 columns; docstrings and long strings may go to 115
   (ruff `max-line-length`), to avoid reflowing explanatory text.
8. **Where it runs.** The full backfill (about 2,300 days x 4 datasets at 1.5 s per request, roughly
   4 to 5 hours) is meant to run on the always-on VPS, which holds the production data folder.

## Facts established (probe 2026-10-25)
- All four datasets exist for every sampled year from 2017 to 2026; holidays and weekends are 404.
- Ban-file first line: `Securities in Ban For Trade Date DD-MON-YYYY:` then either `NIL` or numbered lines.
- Participant file title has odd doubled quotes in recent years, so the date is read from the raw
  first line, not through the CSV parser.
- Index-close rows: 74 (2017-10-24), 118 (2024-07), 167 (2026-10-23).
