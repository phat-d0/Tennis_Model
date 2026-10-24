# CLAUDE.md: Swing-Lock / Arbitrage Scanner (tennis, binary markets)

Read this first in every session, then `docs/WORK_PLAN.md`, then your role brief in
`docs/team/`. This file holds the durable rules and facts; `WORK_PLAN.md` holds status.

## Goal
Find out whether profitable "locks" occur in live binary sports markets (tennis
match winners first) and alert when one appears live.

- **True arb:** ask(A) + ask(B) + fees < $1 at the same moment → buy equal counts.
- **Swing lock:** hold A @ p1; later if p1 + ask(B) + fees < $1, buy the SAME NUMBER
  of B contracts. Locked P&L = contracts × (1 − p1 − p2) − fees.

## Owner's standing rules
1. **Read-only. No automated order placement**: no order code, no write-scope keys, not
   behind a flag.
2. Fills are realistic: buy at the ask, sell at the bid, fees per order, plus slippage.
   **Never fill at mid or last.**
3. DraftKings: no scraping of DraftKings itself (its ToU bans it). DraftKings **Sportsbook**
   prices come only through **The Odds API** (the owner's paid key, shared with their soccer and
   baseball apps). Only the Data role spends credits, within the owner's budget, and logs every spend.
4. **Kalshi data is for the owner's personal, private research** (owner decision 2026-10-24, made
   knowing the Kalshi Data ToU): low request rates, never redistributed or published, only tiny
   test fixtures in git. Datasets go on the `data-store` branch **only while the repo is
   private**; the Lead confirms visibility before the first data push.
5. Confirm API endpoints, rate limits and fees from official docs. Don't assume them.
6. Document every update here (Changelog) and in `docs/WORK_PLAN.md` so nothing gets lost.
7. Report results plainly, bad ones included.

## Team
Each role runs in its own Claude Code cloud session on its own branch, tagged `tennis-team`.
Session IDs are in `docs/team/lead.md`.

| Role | Job | Owns | Branch |
|---|---|---|---|
| **Lead / Reviewer** | Coordinates, reviews and merges every PR, keeps the memory docs current, watches the API budget, reports to the owner | `CLAUDE.md`, `docs/WORK_PLAN.md`, `docs/team/*`, shared core (`fees.py`, `locks.py`, `schema.py`, `config.py`, `positions.py`, `config.yaml`, `pyproject.toml`) | `team/lead` |
| **Data** | Kalshi, then The Odds API and Polymarket US collectors, normalizers, order-book recorder, historical backfill. **Only role that bulk-pulls history or spends Odds API credits** | `swinglock/collectors/`, `tests/fixtures/`, `docs/research/kalshi_api.md`, `docs/data_*.md`, branch `data-store` | `team/data` |
| **Backtest** | True-arb scan, swing-lock grid, walk-forward gate, findings report | `swinglock/backtest/`, `reports/`, `docs/edge_*.md` | `team/backtest` |
| **Scanner** | Live scan loop, alerts, positions → lock quotes, `state.json`, VPS deploy (Docker/systemd) | `swinglock/scanner/`, `deploy/`, `docs/scanner_*.md` | `team/scanner` |
| **Dashboard** | Live HTML view of `state.json` | `swinglock/dashboard/`, `docs/ui_*.md` | `team/ui` |

Each role also owns its own `tests/test_<area>*.py`.

### Rules for every role (Lead included)
1. **Never push to `main`.** Work on your branch and open a PR into `main` when a piece is
   finished and tested. One topic per PR, small enough to review.
2. **Stay in your files.** Changes to shared code are minimal and called out in the PR; the
   Lead sequences merges.
3. **Before a PR:** `python -m pytest -q` passes; backtest claims pass the gate (below);
   dashboard PRs attach 390×844 and 1280×800 screenshots in light and dark mode, with no page errors.
4. **API budgets:** Kalshi: Data stays under ½ of the read limit, Scanner under ¼; everyone
   else reuses data from the `data-store` branch. Back off on 429. The Odds API: credits are paid
   and shared with the owner's other apps; only Data spends them, within the budget in
   `docs/WORK_PLAN.md`, never below the floor, and logs each spend (date, endpoint, credits,
   balance after) in `docs/data_inventory.md`. The key comes from the env var `ODDS_API_KEY`; never commit it.
5. **Results go in `docs/` or `reports/`** with numbers, bad ones included.
6. **Update your branch by merging `main` in, never by rebasing.**
7. **Memory rule:** only the Lead edits `CLAUDE.md` and `docs/WORK_PLAN.md`. Others put
   proposed changes (new facts, decisions, status) in their PR description; the Lead folds
   them in, in the same merge round.

### The gate (when a backtest result counts)
A strategy rule (entry X, lock Y) is "real" only if: fills are at ask/bid with fees, and it stays
positive at 1¢ slippage; walk-forward out-of-sample P&L (choose X, Y on earlier months, test on
the next one) is positive in ≥ 3 of 4 folds; there are ≥ 30 out-of-sample trades; and a no-lookahead
test passes. Changing the scanner's alert thresholds to a tested rule needs the owner's go-ahead.

## Layout
```
config.yaml                 thresholds, fees, slippage, series list
positions.example.json      template for the owner's holdings (copy to positions.json, gitignored)
swinglock/
  fees.py                   FeeModel; kalshi_fee_model(fee_type, multiplier)
  locks.py                  core math: true_arb, Holding, lock_quote, max_lock_price, buy_cost
  schema.py                 data contract: matches + quotes tables
  config.py                 load_config(), kalshi_fees(cfg, fee_type, mult)
  positions.py              load_positions(json|csv)
  collectors/               venue API clients → raw JSON → normalized parquet   (Data)
  backtest/                 align (as-of A/B join, phase) · arb (episodes) · swing (sim) ·
                            metrics · grid · run CLI → reports/                 (Backtest)
  scanner/                  live loop, alerts, state.json                       (Scanner)
  dashboard/                live HTML view of state.json                        (Dashboard)
docs/WORK_PLAN.md           status, open items, next steps
docs/team/                  role briefs + lead.md (session IDs)
docs/research/              verified API/fee/ToS notes per venue (with source URLs)
reports/                    backtest findings
tests/                      pytest; fixtures/ holds trimmed real API responses
```

## Data contracts
**Historical/normalized data** (`swinglock/schema.py`, parquet under `data/processed/<venue>/`,
published on the `data-store` branch):
- `matches`: match_id, venue, series, tier, tournament, player_a/b, instrument_a/b,
  scheduled_start, open/close_time, winner (A/B/NA), fee_type, fee_multiplier.
- `quotes`: ts, match_id, venue, side (A/B), ask, ask_size, bid, bid_size, ask_source,
  source (orderbook|candle|ticker|manual). Prices in dollars.
- Kalshi: a match event has one market per player. Effective ask(A) =
  min(YES ask on A's market, NO ask on B's market); collectors resolve it.

**Live state** (`data/live/state.json`, written atomically by Scanner, read by Dashboard;
`combined_with_fees` = cost per matched contract incl. fees at the arb size; "live" opportunity
= `arb_profit > 0` or `lock.locked_pnl > 0`):
```json
{"generated_at": "ISO-8601 UTC", "poll_seconds": 5, "venue": "kalshi",
 "matches": [{"match_id": "", "series": "", "tier": "", "player_a": "", "player_b": "",
   "phase": "pre|live|unknown", "quote_ts": "", "ask_a": 0.0, "ask_b": 0.0,
   "size_a": 0.0, "size_b": 0.0, "bid_a": 0.0, "bid_b": 0.0, "combined": 0.0,
   "combined_with_fees": 0.0, "arb_contracts": 0.0, "arb_profit": 0.0}],
 "positions": [{"match_id": "", "player_a": "", "player_b": "", "contracts_a": 0.0,
   "avg_a": 0.0, "contracts_b": 0.0, "avg_b": 0.0, "pnl_if_a": 0.0, "pnl_if_b": 0.0,
   "lock": {"side_to_buy": "A|B", "contracts_to_buy": 0.0, "ask": 0.0, "cost": 0.0,
            "locked_pnl": 0.0, "depth_ok": true}}],
 "alerts": [{"ts": "", "type": "arb|lock|cross_venue", "match_id": "", "message": "",
   "contracts": 0.0, "cost": 0.0, "locked_pnl": 0.0}]}
```
`lock` is null for a balanced holding; prices are null when a side has no ask. Alerts keep
the newest 200. Format changes go through the Lead (Scanner proposes, Dashboard follows).

## Conventions
- Prices are dollars as floats (0.427 = 42.7¢); contract counts may be fractional.
- Costs always include fees. A `Holding.from_avg()` avg price is assumed all-in.
- Fee constants live in config.yaml; per-series fee_type/fee_multiplier come from the API.
- Run tests: `python -m pytest -q`. Python 3.13; deps in pyproject.toml.
- Raw/processed data under `data/` is gitignored on code branches; commit only small fixtures.

## Key facts (verified)
- Kalshi REST base: `https://external-api.kalshi.com/trade-api/v2` (recommended;
  `api.elections.kalshi.com` also works). Public market data needs no auth. `GET /series` gives
  per-series `fee_type` (quadratic, quadratic_with_maker_fees, quadratic_with_combo_maker_fees,
  flat) and `fee_multiplier`. Every tennis series has multiplier 1 (checked 2026-10-24).
- Active Kalshi tennis match series: KXATPMATCH, KXWTAMATCH (quadratic_with_maker_fees since
  2025-11-15), KXATPCHALLENGERMATCH, KXWTACHALLENGERMATCH, KXITFMATCH, KXITFWMATCH (quadratic).
  Team-event series also exist (KXDAVISCUPMATCH, KXUNITEDCUPMATCH, KXLAVERCUPMATCH, KXSIXKINGSMATCH).
  KXCHALLENGERMATCH is empty, since Challenger matches are under KXATPCHALLENGERMATCH.
- Fee formula (taker): round_up(M × 0.07 × C × P × (1−P)); maker 0.0175 where charged
  (maker = ¼ taker confirmed in docs; the 0.07/0.0175 constants are from the fee-schedule PDF
  via search snippets, so the owner should confirm at kalshi.com/fee-schedule). Fees are rounded up
  to $0.000001, then balances align to $0.0001 (direct members) or $0.01 (FCM), with a per-order
  rebate accumulator. No settlement fee. Full details: docs/research/kalshi_api.md.
- Kalshi tennis structure: a match = one event (`mutually_exclusive: true`,
  `collateral_return_type: MECNET`) with two markets, one per player (YES on `...-FAR` = Faria wins).
  Orderbook returns **bids only** (ascending; best = last). YES ask = 1 − best NO bid;
  NO ask = 1 − best YES bid. ask(A) = min(YES ask on A, NO ask on B). YES_A+YES_B and NO_A+NO_B
  both pay exactly $1. `GET /markets/orderbooks` fetches both legs in one call.
- `GET /events?with_milestones=true` returns a top-level `milestones` list mapped to events by
  `primary_event_tickers` (start dates without per-event calls). Scanner A/B convention: A = the
  market ticker that sorts first.
- Tournament name: `event.product_metadata.competition`. Tour/round/best_of/scheduled start:
  `GET /milestones?related_event_ticker=`. Live score: `GET /live_data/milestone/{id}` (current
  snapshot only, no history).
- Markets settled before `GET /historical/cutoff` (2026-08-25 as of 2026-10-24) are only in
  `/historical/*`; historical candles drop the `_dollars`/`_fp` field suffixes. Not-started
  matches settle at a "fair price", not 0/1; a retirement after the first ball settles the
  retiring player's market to No.
- Kalshi 1-min candles are **sparse** (minutes with no change are omitted; VanAssche–Musetti had
  786 candles over 1,745 min). **Verified 2026-10-24 (phat-d0/Tennis_Model#11): candles are written
  on quote changes, not only on trades** (26,786 zero-volume candles with a changed bid/ask; live
  check: carried state matched the live best bid/ask in 140/144 leg-snapshots, misses = intra-minute
  moves). So carrying each leg's last close forward is valid. It's capped at `data.max_carry_s`
  (1800 s) only to guard against data gaps. Within a minute, the carried quote can lag up to 60 s.
- Batch candles `GET /markets/candlesticks`: the 10,000 cap counts **requested** candles (tickers ×
  window minutes), not returned ones; over the cap gives HTTP 400 (checked live). A match is listed
  ~24 h, so one call covers ~3 same-day matches. Pre-cutoff (historical) markets need one call each.
- Before 2025-11-15, KXATPMATCH/KXWTAMATCH matches are tagged fee_type `quadratic` (an assumption,
  since the fee history only records the new value). Taker fees are the same either way.
- Auth: REST market data is public; **every WebSocket connection needs a signed API key**.
  Unauthenticated REST hit a 429 after ~8 rapid calls (backfill at a 0.5 s gap: 11×429 in 178
  requests; at a 1.0 s gap: a burst of 16×429 at the start, then clean), so throttle hard (seen again on a single
  scanner pass on 2026-10-24; the scanner backs off and spaces requests ≥ 1 s).
- **Kalshi Data Terms of Use** (kalshi-public-docs PDF) restrict "Kalshi Data" to personal
  non-commercial use and prohibit compiling databases, bulk script retrieval, redistribution,
  and ML/AI use. Status of our collection: see Owner's standing rules / WORK_PLAN open items.
- Polymarket (intl): public read APIs (Gamma discovery, CLOB `/book`, prices-history, trades),
  tennis tag id 864; each match = one market with two player tokens (not negRisk).
  `/book` levels are sorted worst-first (best = last element); `/price?side=SELL` returns the ask.
  Sports taker fee 0.05 × p × (1−p) per share. prices-history is a single (mid-like) series,
  so there's no historical bid/ask; ask-based backtests need our own recorded books.
  **US users can't trade intl.** Polymarket US is a separate CFTC venue with its own public
  read API (WS needs a signed key), taker coefficient 0.0695. Walkover settlement differs
  (US: last fair price; intl: 50-50), so check rule mismatches before calling a cross-venue gap an arb.
  Details: docs/research/other_venues.md (some facts from search summaries; re-verify before coding).
- The Odds API (the-odds-api.com): `draftkings` is the DraftKings **Sportsbook** (region `us`), not
  DK Predictions; region `us_ex` lists Kalshi, Polymarket, Novig, ProphetX, BetOpenly. Tennis sport
  keys and credit costs: docs/research/odds_api.md. **Tennis coverage is tour-level only** (one key
  per tournament, e.g. `tennis_atp_us_open`; 47 keys; no Challenger/ITF and few 250s). `/odds` costs
  markets × regions credits; `/sports` and `/events` are free. DraftKings voids walkovers and
  retirements before set 1 is complete. A sportsbook leg is a
  bet, not a contract: equal-payout sizing is stake = N / decimal_odds, and retirement/void rules
  differ from Kalshi's, so a "lock" across them isn't risk-free when a player retires.
- DraftKings Predictions: **no public/partner API**. ToU (2026-08-04) bans bots/scrapers and
  limits use to personal non-commercial. It's a broker (FCM) routing to CME / Crypto.com / DKeX /
  Bitnomial. Fee ≈ flat $0.02/contract between $0.30 and $0.94. → manual logging only.

## Environment gotchas
- VPS deploy (`deploy/`, docs/scanner_deploy.md): one Docker image; `scanner` + `dashboard` by
  default (dashboard published on 127.0.0.1:8000 only, so it's reached over an SSH tunnel), `recorder`
  behind `--profile recorder`, optional Caddy HTTPS + basic auth behind `--profile public`. Secrets in
  `deploy/.env` (gitignored); holdings in `data/positions.json` (gitignored). **Scanner and recorder
  share the VPS IP and therefore Kalshi's unauthenticated rate limit**: the scanner uses ~0.22 req/s,
  so size the recorder within Data's ½ share.
- Cloud sessions are ephemeral: commit and push work before stopping. A long-running
  recorder or scanner can't live in a cloud session; it needs the owner's machine or a server.
- The environment's network policy must allow api.elections.kalshi.com, docs.kalshi.com and
  the Polymarket hosts (set by the owner on 2026-10-24). WebFetch can't reach docs.kalshi.com,
  so use curl (docs pages are available as `.md`).

## Decisions
- 2026-10-24: Python 3.13, pandas + parquet storage, requests for REST, websockets for WS.
- 2026-10-24: Floats with ceil-epsilon for fee rounding (no Decimal); fees rounded per order.
- 2026-10-24: Lock = buy short side to equalize counts (owner's sizing rule), not dollar-equal.
- 2026-10-24: Worked example (Krueger/Li) treated as all-in prices; test tolerance 1.5¢
  because the brief's $ figures are rounded (+$0.84 vs exact 27.62 × 3¢ = $0.83).
- 2026-10-24 (owner): Kalshi data OK for personal, private use; repo to be made private; live
  scanner + recorder will run on a small cloud server (VPS); cross-venue via The Odds API
  (DraftKings Sportsbook) + Polymarket US.
- 2026-10-24: Team structure per the owner's playbook: Lead + Data, Backtest, Scanner, Dashboard.
- 2026-10-24: Backtest: as-of join with 60s max staleness (`backtest.max_staleness_s`);
  settlement time = last aligned quote; default swing mode = first side to trigger; arb profit =
  one fill at the best observation's depth (1 contract if depth unknown, so fees are cent-heavy).
- 2026-10-24: Walk-forward: monthly folds by each match's first observation; expanding window;
  select on total P&L at 1¢ slippage with ≥ 10 training trades; training trades must settle before
  the test month; positive-folds check at the worst slippage, and total OOS P&L > 0 at every
  slippage; CI = match-clustered bootstrap. Per-trade CSVs in `reports/` are gitignored (Kalshi
  data is private); only markdown write-ups are committed.

## Changelog
- 2026-10-24: Project scaffold, core math + tests (12 passing), config, schema, CLAUDE.md.
  Environment network policy updated by owner so Kalshi/Polymarket APIs are reachable.
- 2026-10-24: Venue research done (DK: no sanctioned access; Polymarket intl + US read APIs public).
- 2026-10-24: Kalshi API research done (docs/research/kalshi_api.md, 13 fixtures).
- 2026-10-24: Backtest module v1 (align, arb, swing, metrics, grid, CLI); 28 tests passing.
- 2026-10-24: Team set up (CLAUDE.md Team section, WORK_PLAN.md, role briefs, team/* branches),
  merged in phat-d0/Tennis_Model#1; Data, Backtest, Scanner, Dashboard sessions started.
- 2026-10-24: Walk-forward gate merged (phat-d0/Tennis_Model#2); 37 tests passing.
- 2026-10-24: Scanner v1 (phat-d0/Tennis_Model#3) and Dashboard v1 (phat-d0/Tennis_Model#5) merged;
  58 tests passing. Run: `python -m swinglock.scanner [--once]`,
  `python -m swinglock.dashboard --state data/live/state.json` (or `--sample`).
- 2026-10-24: Dashboard filters merged (phat-d0/Tennis_Model#8); 61 tests passing.
- 2026-10-24: Kalshi client, normalizer and resumable backfill merged (phat-d0/Tennis_Model#9);
  81 tests passing. Run: `python -m swinglock.collectors.backfill`. Full backfill running in the Data
  session at 1 req/s (settled events: ATP 5,029, WTA 5,034, Challenger 10,232 + 2,214, ITF next).
- 2026-10-24: Candle carry-forward verified + capped (phat-d0/Tennis_Model#11); cap set to 1800 s
  (300 s would discard valid unchanged quotes); 82 tests passing.
- 2026-10-24: VPS deploy merged (phat-d0/Tennis_Model#13): Docker compose + systemd + logrotate;
  tested in the dev container (scanner ~25 MB, dashboard ~16 MB); Caddy, recorder and a real
  reboot are untested.
- 2026-10-24: Backfill work order (recent 183 days ATP+WTA → recent Challenger → rest) + batched
  candles for post-cutoff markets (phat-d0/Tennis_Model#15); 86 tests passing. Recent ATP+WTA slice
  (~4–5k matches) ETA ~2.5–3 h from 10:20 UTC.
