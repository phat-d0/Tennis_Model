# CLAUDE.md: Swing-Lock / Arbitrage Scanner (tennis, binary markets)

Read this first in every session. Keep it current: every agent/session that changes
the project adds a line to the **Changelog** and updates **Status** / **Decisions**.

## Goal
Find out whether profitable "locks" occur in live binary sports markets (tennis
match winners first) and alert when one appears live. **Read-only: never place
orders.** No order placement code, no trading keys with write scope.

- **True arb:** ask(A) + ask(B) + fees < $1 at the same moment → buy equal counts.
- **Swing lock:** hold A @ p1; later if p1 + ask(B) + fees < $1, buy the SAME NUMBER
  of B contracts. Locked P&L = contracts × (1 − p1 − p2) − fees.
- Fills: buy at ask, sell at bid, include fees + slippage. **Never fill at mid/last.**

## Layout
```
config.yaml                 thresholds, fees, slippage, series list
positions.example.json      template for the user's holdings (copy to positions.json, gitignored)
swinglock/
  fees.py                   FeeModel; kalshi_fee_model(fee_type, multiplier)
  locks.py                  core math: true_arb, Holding, lock_quote, max_lock_price
  schema.py                 data contract: matches + quotes tables (see below)
  config.py                 load_config(), kalshi_fees(cfg, fee_type, mult)
  positions.py              load_positions(json|csv)
  collectors/               venue API clients → raw JSON → normalized parquet
  backtest/                 Part 1: arb + swing-lock grid search on historical quotes
  scanner/                  Part 2: live polling/websocket, alerts
  dashboard/                simple live HTML/Streamlit view
docs/research/              verified API/fee/ToS notes per venue (with source URLs)
reports/                    backtest findings
tests/                      pytest; fixtures/ holds trimmed real API responses
```

## Data contract (swinglock/schema.py)
- `matches`: match_id, venue, series, tier, tournament, player_a/b, instrument_a/b,
  scheduled_start, open/close_time, winner (A/B/NA), fee_type, fee_multiplier.
- `quotes`: ts, match_id, venue, side (A/B), ask, ask_size, bid, bid_size,
  ask_source, source (orderbook|candle|ticker|manual). Prices in dollars.
- Kalshi: a match event has one market per player. Effective ask(A) =
  min(YES ask on A's market, NO ask on B's market); collectors resolve it.

## Conventions
- Prices are dollars as floats (0.427 = 42.7¢); contract counts may be fractional.
- Costs always include fees. A `Holding.from_avg()` avg price is assumed all-in.
- Fee constants live in config.yaml; per-series fee_type/fee_multiplier come from the API.
- Run tests: `python -m pytest -q`.
- Raw/processed data under data/ is gitignored; commit only small trimmed fixtures.

## Key facts (verified)
- Kalshi REST base: `https://api.elections.kalshi.com/trade-api/v2` (public market data
  needs no auth). `GET /series` returns `fee_type` ∈ {quadratic,
  quadratic_with_maker_fees} and `fee_multiplier` ∈ {1, 0.5} (checked 2026-10-24).
- Kalshi tennis match series (from `/series`, 2026-10-24): KXATPMATCH, KXWTAMATCH
  (both quadratic_with_maker_fees), KXATPCHALLENGERMATCH, KXCHALLENGERMATCH,
  KXWTACHALLENGERMATCH, KXITFMATCH, KXITFWMATCH, KXDAVISCUPMATCH, KXUNITEDCUPMATCH,
  KXLAVERCUPMATCH, KXSIXKINGSMATCH (quadratic).
- Fee formula (taker): round_up(M × 0.07 × C × P × (1−P)); maker 0.0175 where charged.
  Full details & sources: docs/research/kalshi_api.md.
- Polymarket (intl): public read APIs (Gamma discovery, CLOB `/book`, prices-history, trades),
  tennis tag id 864; each match = one market with two player tokens (not negRisk).
  `/book` levels are sorted worst-first (best = last element); `/price?side=SELL` returns the ask.
  Sports taker fee 0.05 × p × (1−p) per share. prices-history is a single (mid-like) series,
  so there's no historical bid/ask; ask-based backtests need our own recorded books.
  **US users can't trade intl.** Polymarket US is a separate CFTC venue with its own public
  read API (WS needs a signed key), taker coefficient 0.0695. Walkover settlement differs
  (US: last fair price; intl: 50-50), so check rule mismatches before calling a cross-venue gap an arb.
  Details: docs/research/other_venues.md (some facts from search summaries; re-verify before coding).
- DraftKings Predictions: **no public/partner API**. ToU (2026-08-04) bans bots/scrapers and
  limits use to personal non-commercial. It's a broker (FCM) routing to CME / Crypto.com / DKeX /
  Bitnomial. Fee ≈ flat $0.02/contract between $0.30 and $0.94. → manual logging only.

## Decisions
- 2026-10-24: Python 3.13, pandas + parquet storage, requests for REST, websockets for WS.
- 2026-10-24: Floats with ceil-epsilon for fee rounding (no Decimal); fees rounded per order.
- 2026-10-24: Lock = buy short side to equalize counts (user's sizing rule), not dollar-equal.
- 2026-10-24: Worked example (Krueger/Li) treated as all-in prices; test tolerance 1.5¢
  because the brief's $ figures are rounded (+$0.84 vs exact 27.62 × 3¢ = $0.83).
- DraftKings Predictions: research only, no scraping unless the user approves.

## Status
- [x] Core math: fees, true arb, swing-lock quote, worked-example tests
- [x] Config, positions loader, data schema
- [ ] Kalshi API research → docs/research/kalshi_api.md (in progress)
- [x] DraftKings/Polymarket research → docs/research/other_venues.md
- [ ] Kalshi collector (markets, orderbook, trades, candles) → normalized parquet
- [ ] Backtest engine + grid search + breakdowns
- [ ] Live scanner + alerts + dashboard
- [ ] Backtest report, README

## Open questions for the user
- DraftKings Predictions: no sanctioned API and ToU bans automated collection. Options: manual
  price logging (positions/quotes CSV with source=manual) or skip DK. **User to decide.**
- Polymarket: intl isn't tradeable from the US; Polymarket US is. Which venue to compare against?
- Live score/set state: Kalshi doesn't appear to publish it; needs an external source if wanted.

## Changelog
- 2026-10-24: Project scaffold, core math + tests (12 passing), config, schema, CLAUDE.md.
  Environment network policy updated by user so Kalshi/Polymarket APIs are reachable.
- 2026-10-24: Venue research done (DK: no sanctioned access; Polymarket intl + US read APIs public).
