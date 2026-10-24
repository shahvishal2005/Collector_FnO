# Live capture pilot: design (not yet built)

Status: design for milestone M5. **Day-0 probe done on 2026-10-24: see `PROBE_FINDINGS.md`**
for answers to most of the questions below (the rest need a trading-hours run). Runs on the **laptop** for 3 to 5 trading days. The production
collector (M6) runs on the VPS with the same code, different config.

## Goal
Learn, with real measurements, what the Fyers API gives us for option chains, open interest and
futures, how fast we can poll it, and how often we lose data, before building the production
collector. The pilot is read-only: it uses market-data calls only and never touches orders.

## Scope (all configurable)
| Tier | Underlyings | Content | Frequency to test |
|---|---|---|---|
| 1 | Nifty 50, Bank Nifty, Fin Nifty, Midcap Nifty, Sensex | Option chain around the money for the nearest expiries, futures quote with OI, India VIX | 1, 2 and 5 minutes (compare) |
| 2 (pilot) | About 10 stocks from the Tier 2 ranking (`scripts/derive_tier2.py`) | Option chain around the money for the nearest expiry | 5 minutes |
| EOD | Live contracts of Tier 1 | 1-minute day candles per contract, with OI if the API returns it | After 15:30, once |

Strikes captured: a window around the money (for example the nearest 20 strikes each side),
configurable; the pilot also tests whether the endpoint returns the full chain in one call.

## What the pilot must answer
1. **Option-chain endpoint:** which fields come back (LTP, bid, ask, quantities, volume, OI, change
   in OI, IV), how many strikes and expiries per call, and how one call counts toward the rate limit.
2. **Rate limits:** requests per second / minute / day, what happens on exceeding them, and the
   cycle interval each tier can sustain.
3. **History for option contracts:** does the history API return 1-minute candles for live option
   contracts, with OI? Is anything served after expiry? (The research platform found expired
   futures are not served.)
4. **Symbols:** Fyers' symbol format for index/stock options (expiry, strike, CE/PE) and where the
   contract master comes from; mapping to NSE's bhavcopy contracts.
5. **Sensex / BSE:** whether Sensex options are available through the same endpoints, and their
   symbol format.
6. **Login and tokens:** does a second login (VPS vs laptop, or collector vs research platform)
   invalidate the first token? What is the token lifetime?
7. **Fidelity:** compare end-of-day snapshot OI with NSE's bhavcopy open interest for the same day
   (they should match closely for Tier 1).
8. **Reliability:** snapshots expected vs captured per day, gaps and their causes (network, API,
   laptop sleep, rate limits), latency per call.

## Pilot method
Day 0 (about one hour, market closed or open): an exploratory script makes a handful of read-only
calls and saves the raw responses, so the field list and symbol formats are known before the
scheduler is written. Nothing else is built until this is read.

Days 1 to 5: the scheduler runs during 09:15 to 15:30 IST on the laptop with sleep disabled,
captures into bronze (raw responses, compressed) and silver (normalised option-chain rows per
`COLLECTOR_PLAN.md` 6.7), and writes a per-cycle health record (intended time, actual time,
duration, success or error, rows, rate-limit signals).

Day 5 or 6: a findings note answering the eight questions with numbers, a resource budget (calls
per cycle, megabytes per day), the recommended intervals per tier, and a go/no-go for the VPS.

## Safety and conduct
- Market-data endpoints only. The no-order test stays in force.
- Credentials only in this project's own `.env` (never committed, never printed, never sent to an
  AI assistant). The owner creates it; the code reads the same variable names as the research
  platform (`fyers_id`, `client_id`, `secret_key`, `redirect_uri`, `TOTP_key`, `pin`).
- Never run the pilot and the production collector at the same time (shared rate limit, token
  conflicts, duplicate data).
- Respect Fyers' terms and rate limits; back off on errors rather than retrying fast.
- Laptop: plugged in, never sleep during market hours, stable network. Sleep or Wi-Fi loss is
  recorded as a gap, which is itself a pilot result.

## Pilot acceptance
- Raw responses and normalised rows exist for each day, each with a health record.
- The eight questions are answered in writing.
- At least one day's end-of-day OI compared with NSE bhavcopy, with the differences explained.
- A decision on intervals, strike windows and tiers for the production collector.

## Build list for M5 (after M2 results are reviewed)
1. Port the Fyers login module from the research platform (automatic TOTP login, daily token store).
2. Exploratory read-only probe script (day 0).
3. Option-chain and futures-quote clients, with raw capture.
4. Normaliser for `option_chain_snapshot` and `futures_quote_snapshot`.
5. Scheduler with IST market-hours awareness and holiday handling (uses the expiry/trading calendar).
6. Health records, daily completeness report, bhavcopy comparison.
7. Alerts (Telegram and email) come last, as requested.
