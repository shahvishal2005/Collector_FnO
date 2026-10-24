# Fyers day-0 probe: findings (2026-10-24, Saturday, market closed)

Raw answers: `data/probe/20261024_202513/` (git-ignored). Script: `scripts/probe_fyers.py`.
All calls were read-only market-data calls. **Caveat:** the market was closed, so numbers show the
last session (Friday 2026-10-23) and the very low latencies may not hold during trading hours.

## Answers to the pilot questions

| # | Question | Finding |
|---|---|---|
| 1 | Option-chain fields | One call returns, per option: `symbol, option_type, strike_price, ltp, ltpch, ltpchp, bid, ask, oi, oich, oichp, prev_oi, volume, fyToken`. The first row is the index itself (spot, `fp` = future price). The answer also has `callOi`, `putOi` (totals) and `indiavixData` (India VIX). **No implied volatility. No bid/ask quantities** (those come from the depth endpoint). |
| 1b | Size of a call | `strikecount=50` gave 203 rows (101 strikes x CE/PE + index), about 70 KB of JSON. `strikecount=3` gave 15 rows. One call covers **one expiry** (the nearest by default). |
| 1c | Expiries | The answer lists all expiries with a flag (`M` monthly, `W` weekly): Nifty 18, Sensex 19, Midcap Nifty 3 (monthly only). A later expiry is requested by passing its **epoch** (text) as `timestamp`; a date string is rejected ("Please provide valid expiry"). |
| 2 | Rate limits | 29 calls at 0.4 s spacing and 10 sequential calls: no rate-limit answer (no 429); latency 0.01 to 0.06 s per call. Sustained-rate limits are **not yet tested** (needs a trading-hours run). |
| 3 | History for option contracts | Works for live contracts: 1-minute candles with **7 values per candle: time, open, high, low, close, volume, open interest**. A 4-trading-day request returned 1,540 candles (385 per day, 09:15 to 15:39). **Expired contracts are not served**: both the expired future and option I tried returned code -300 "Invalid symbol". So per-contract candles must be pulled before expiry. |
| 4 | Symbols | Monthly: `NSE:NIFTY26OCT22450PE`, `NSE:NIFTY26OCTFUT`. Weekly: `NSE:NIFTY26N0322500PE` (year, one-letter month code, day). Use the symbols the chain returns; do not construct them. Public symbol masters give lot sizes: `https://public.fyers.in/sym_details/NSE_FO.csv` (88,159 lines) and `BSE_FO.csv` (7,905 lines). |
| 5 | Sensex / Midcap Nifty | Both work through the same endpoint: `BSE:SENSEX-INDEX` (19 expiries) and `NSE:MIDCPNIFTY-INDEX` (3 monthly expiries). |
| 6 | Tokens | A second automatic login **did not invalidate the first token**: both validated afterwards. The collector and the research platform can use the same Fyers app credentials. Token lifetime is still assumed to be one day. |
| 7 | Fidelity vs NSE bhavcopy (2026-10-23) | See below. |
| 8 | Reliability | Not measurable on a closed-market day; the pilot days will measure it. |

### Depth endpoint
Five bid and five ask levels with price, volume and order count, plus total buy/sell quantity,
last traded quantity and time, average traded price, circuit limits, open interest and previous OI.

## Fidelity against NSE's official end-of-day file (Nifty and Bank Nifty, 27-Oct-2026 expiry, 202 contracts each)

| Check | Nifty | Bank Nifty |
|---|---|---|
| API volume equals bhavcopy volume x lot size | 100% | 100% |
| API `prev_oi + oich == oi` (internal consistency) | 100% | 100% |
| Open interest exactly equal | 71.8% | 93.1% |
| Open interest within 1% | 92.1% | 97.5% |
| API change in OI equals bhavcopy change in OI | 62.9% | 93.1% |
| `ltp` equals bhavcopy `close` | 27% | 29% |

Reading: volumes line up perfectly (API volume is in **units**, bhavcopy volume is in **lots**).
Open interest is close but not always identical; differences are small and probably come from when
each source finalises OI. `ltp` (last traded price) and the bhavcopy `close` are defined
differently, so they are expected to differ.

**Open flag.** For one sample contract (`NSE:NIFTY26OCT22450PE`) the last 1-minute candle's OI
(3,630,965 at 15:39) differed by about 5% from the chain's OI (3,469,765) and NSE's official figure
(3,463,915). So **minute-candle OI at the end of day should not be treated as the official close**.
The chain snapshot near the close and the bhavcopy are closer. This needs a check on many contracts
during the pilot before relying on candle OI.

## Consequences for the collector design
1. A snapshot cycle for one underlying is **one chain call per expiry** (about 70 KB for 50 strikes
   each side). Capturing nearest + next weekly + monthly for five indices is roughly 15 calls a cycle.
2. IV and bid/ask quantities are not in the chain. IV can be computed later from price, spot, time
   and rate; depth is a separate call and should be used sparingly (top contracts only).
3. The nightly per-contract candle pull (with OI) is valuable and must run **before expiry** for
   every live contract we care about, because expired contracts cannot be fetched.
4. Prefer the chain's own symbols; a contract master from the symbol-master CSV adds lot sizes.
5. Store volume in the API's units and convert with lot size when comparing to bhavcopy.
6. One login can be shared by processes; still, keep a single writer for each dataset.

## Still unknown (to answer in the live pilot)
- Sustained rate limits during trading hours, and behaviour when exceeded.
- Real latency under load; whether chains update every second or less often.
- How close minute-candle OI and chain OI are to official OI across many contracts.
- Token lifetime in practice and the best time for the daily login.
- Behaviour around expiry day (contracts disappearing, weekly rollover).
