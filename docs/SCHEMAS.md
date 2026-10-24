# Schemas and data notes (schema_version 1)

## fo_eod: end-of-day F&O contracts

One row per contract per trade day. File: `data/silver/fo_eod/trade_date=YYYY-MM-DD/part-0.parquet`.
Natural key: `trade_date, instrument_type, underlying, expiry_date, strike, option_type`.

| Column | Type | Meaning |
|---|---|---|
| trade_date | date | Trading day |
| instrument_type | string | `FUTIDX`, `FUTSTK`, `OPTIDX`, `OPTSTK`, `FUTIVX` (new-format codes IDF/STF/IDO/STO are mapped) |
| underlying | string | NSE symbol, e.g. `NIFTY`, `BANKNIFTY`, `RELIANCE` |
| expiry_date | date | Contract expiry |
| strike | float | Option strike; null for futures |
| option_type | string | `CE` or `PE`; null for futures |
| open, high, low, close | float | Day prices of the contract |
| last_price | float | Last traded price (new format only) |
| prev_close | float | Previous close (new format only) |
| underlying_price | float | Underlying's price at close (new format only) |
| settle_price | float | NSE settlement price (derived by NSE; not a traded price for contracts that did not trade) |
| volume_contracts | int | Contracts (lots) traded |
| turnover_inr | float | Turnover in **rupees** |
| trades | int | Number of trades (new format only) |
| open_interest_qty | int | Open interest in **units** (shares / index units), not lots |
| chg_in_oi_qty | int | Change in open interest in units (can be negative) |
| lot_size | int | Lot size (new format only; null for old rows, not guessed) |
| source_format | string | `old` or `new` |
| source_file | string | Original file name |
| ingested_at | timestamp (IST) | When this row was produced |
| schema_version | int | 1 |

To convert open interest to lots: `open_interest_qty / lot_size` (needs a lot size; old rows have none).

### Units and format facts (verified on 2024-07-03 to 07-05, where both formats exist)
- Both formats list the same 33,000-odd contracts on those days, with identical prices, volume and OI.
- Old files report turnover in **lakh rupees to two decimals**, so normalised turnover is exact only
  to about Rs 1,000. New files report rupees.
- Old format applies until early July 2024 (last day checked: 2024-07-05); new format from 2024-07-03 on.
  On the overlap days the old file is the primary source, the new file is kept in bronze and compared.

### Known data quirks (these are the exchange's, not bugs)
- **Zero OHLC with volume.** Some far-month contracts that traded (often as spread trades) show
  open/high/low = 0.00 while close and settle are valid. Use close/settle; check name
  `ZERO_OHLC_WITH_VOLUME` (info).
- **Close equals settlement on thin futures.** For thinly traded stock futures NSE's `close` is
  the settlement price and can lie outside the day's low/high (2,004 rows over the full history;
  check `SETTLEMENT_CLOSE_OUTSIDE_RANGE`, info).
- **Universe size changes.** The number of F&O underlyings per day ranged from 138 (2020) to 232.
- **Known source gap.** NSE has no file for 2021-03-30 (see `BACKFILL_RESULT.md`).
- **No-volume rows.** Contracts that did not trade still appear, with prices at zero or at the
  settlement price. Filter `volume_contracts > 0` for traded prices.
- **Unadjusted prices.** Strikes and prices are not adjusted for splits, bonuses or other
  corporate actions. An adjustment table is needed before using these prices over long periods.
- **Special sessions.** Weekend (Muhurat) sessions have files; the calendar includes weekend days
  on which the platform's Nifty candles show a session.
- **Survivorship.** Each day's file lists the F&O universe of that day, so the historical F&O
  universe can be reconstructed from the data. It is not adjusted for symbol changes.

## Other tables (planned)
Participant-wise OI and volume, F&O ban lists, index close, equity bhavcopy with delivery
quantity, contract master and expiry calendar, live option-chain snapshots. See
`plan_details/COLLECTOR_PLAN.md` section 6.

## Catalogue (`data/bronze/catalogue.sqlite`, table `raw_files`)
One row per (dataset, trade_date, format): status `ok` or `not_found`, URL, HTTP status, fetch
time, size, SHA-256 and path. A `not_found` row means NSE answered 404 (holiday or no file) and is
not asked again unless `--recheck-missing` is used.

## Manifest (`data/manifests/fo_eod_manifest.csv`)
Per day: rows, underlyings, future/option rows, sum of open interest, sum of turnover, sum of
close, source format and the file's SHA-256. `check_manifest.py` recomputes the file hashes.
