# CLAUDE.md: Swing-Lock / Arbitrage Scanner (tennis, binary markets)

Read this first in every session, then `docs/WORK_PLAN.md`, then your role brief in
`docs/team/`. This file holds the durable rules and facts; `WORK_PLAN.md` holds status.

## Goal
Find out whether profitable "locks" occur in live binary sports markets (tennis
match winners first) and alert when one appears live.

- **True arb:** ask(A) + ask(B) + fees < $1 at the same moment → buy equal counts.
- **Swing lock:** hold A @ p1; later if p1 + ask(B) + fees < $1, buy the SAME NUMBER
  of B contracts. Locked P&L = contracts × (1 − p1 − p2) − fees.
- **Second project (2026-10-25): early-round upsets, ATP + WTA.** Can a model of upset
  probability beat DraftKings' odds on the underdog? Code in `upsets/`, plan and status in
  `docs/upsets_plan.md`. The Lead builds it for now. Same rules apply: research only, no bet
  placement, DraftKings odds only via The Odds API. Run by the Upsets role since 2026-10-25.

## Owner's standing rules
1. **Read-only. No automated order placement**: no order code, no write-scope keys, not
   behind a flag.
2. Fills are realistic: buy at the ask, sell at the bid, fees per order, plus slippage.
   **Never fill at mid or last.**
3. DraftKings: no scraping of DraftKings itself (its ToU bans it). DraftKings **Sportsbook**
   prices come only through **The Odds API** (since 2026-10-26 the owner's **shared paid plan**, also used by their
   soccer and baseball apps; **never take the balance below the 5,000 reserve**). Only the Data and Upsets roles
   spend credits, within the budget in WORK_PLAN, and log every spend.
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
| **Lead / Reviewer** | Coordinates, reviews and merges every PR, keeps one master plan (priority order + owner rules), watches the API budget, reports to the owner | Owner rules, Team rules and the Master plan order in `CLAUDE.md` / `docs/WORK_PLAN.md` (each role records its own lines, rule 7), `docs/team/*`, shared core (`fees.py`, `locks.py`, `schema.py`, `config.py`, `positions.py`, `config.yaml`, `pyproject.toml`) | `team/lead` |
| **Data** | Kalshi, then The Odds API and Polymarket US collectors, normalizers, order-book recorder, historical backfill. **Only role that bulk-pulls history or spends Odds API credits** | `swinglock/collectors/`, `tests/fixtures/`, `docs/research/kalshi_api.md`, `docs/data_*.md`, branch `data-store` | `team/data` |
| **Backtest** | True-arb scan, swing-lock grid, walk-forward gate, findings report | `swinglock/backtest/`, `reports/`, `docs/edge_*.md` | `team/backtest` |
| **Scanner** | Live scan loop, alerts, positions → lock quotes, `state.json`, VPS deploy (Docker/systemd) | `swinglock/scanner/`, `deploy/`, `docs/scanner_*.md` | `team/scanner` |
| **Dashboard** | Live HTML view of `state.json` | `swinglock/dashboard/`, `docs/ui_*.md` | `team/ui` |
| **Upsets** | Early-round upset study, model, walk-forward, findings, and the public page's odds builder. **May spend Odds API credits only within the budget in WORK_PLAN** | `upsets/`, `tests/test_upsets.py`, `docs/upsets_*.md`, `reports/upsets_*.md` | `team/upsets` |

Each role also owns its own `tests/test_<area>*.py`.

### Rules for every role (Lead included)
1. **Never push to `main`.** Work on your branch and open a PR into `main` when a piece is
   finished and tested. One topic per PR, small enough to review.
2. **Stay in your files.** Changes to shared code are minimal and called out in the PR; the
   Lead sequences merges.
3. **Before a PR:** `python -m pytest -q` passes; backtest claims pass the gate (below);
   dashboard PRs attach 390×844 and 1280×800 screenshots in light and dark mode, with no page errors.
4. **API budgets:** Kalshi: Data stays under ½ of the read limit, Scanner under ¼; everyone
   else reuses data from the `data-store` branch. Back off on 429. The Odds API: credits are limited
   (shared paid plan, 5,000 reserve); only Data and Upsets spend them, within the budget in
   `docs/WORK_PLAN.md`, never below the floor, and logs each spend (date, endpoint, credits,
   balance after) in `docs/data_inventory.md`. The key comes from the env var `ODDS_API_KEY`; never commit it.
5. **Results go in `docs/` or `reports/`** with numbers, bad ones included.
6. **Update your branch by merging `main` in, never by rebasing.**
7. **Memory rule (owner 2026-10-28): every role records its own work.**
   - **In the same PR as the work,** add your own lines to `CLAUDE.md`:
     - a Changelog entry: date, what changed, PR number, the key numbers and tests passing;
     - any new *verified* Key fact or Decision. Mark owner decisions "(owner)".
   - **Update your role's block** in the Master plan at the top of `docs/WORK_PLAN.md`, and your own status
     lines further down.
   - **Append or edit your own lines only;** never rewrite another role's.
   - **Owner rules, team rules and plan order stay with the Lead.** The Owner's standing rules, these Team
     rules and the Master plan's priority order change only on an owner decision, which the Lead records.
     If the owner gives you a decision or a new request directly, record it and tell the Lead the same day
     (`send_message` to the Lead session in `docs/team/lead.md`), so there is one master plan.
   - **Start of every session:** merge or pull `main`, then read `CLAUDE.md` and the Master plan before
     working.
   - **Before a PR:** merge `main` in. On a conflict in these two files, keep both sides' lines.
     Changelog entries stay in date order.

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
upsets/                     early-round upset study: sackmann (results loader) · seeds (base rates) ·
                            elo · features · model · backtest · kalshi_preview · odds_api (DK) (Upsets)
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
  scheduled_start, open/close_time, winner (A/B/NA), settle_a/settle_b (dollars paid per contract:
  1/0, or the fair price for a not-started match; NaN if unsettled), fee_type, fee_multiplier.
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
Since phat-d0/Tennis_Model#116 also: `min_arb_profit_per_contract` (the alert threshold) and `paper` (paper-trading summary:
`since`, `rules`, `by_rule`, `trades`); the nightly `data/paper/lookback.json` sits beside it. Shapes: docs/scanner_paper.md.

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
- Kalshi per-set markets: `KXATPSETWINNER` / `KXWTASETWINNER` (quadratic, mult 1), event `…-N`, one market per
  player. `close_time` ≈ the set end (median −1 min vs the match's quotes; a few administrative batch closes).
  Only the sets before the decider are listed (bo3: sets 1–2; bo5: set 3, set 4 if reached). There are no
  Challenger/WTA 125/ITF set series (checked 2026-10-26).
- Kalshi tennis structure: a match = one event (`mutually_exclusive: true`,
  `collateral_return_type: MECNET`) with two markets, one per player (YES on `...-FAR` = Faria wins).
  Orderbook returns **bids only** (ascending; best = last). YES ask = 1 − best NO bid;
  NO ask = 1 − best YES bid. ask(A) = min(YES ask on A, NO ask on B). YES_A+YES_B and NO_A+NO_B
  both pay exactly $1. `GET /markets/orderbooks` fetches both legs in one call.
- `GET /events?with_milestones=true` returns a top-level `milestones` list mapped to events by
  `primary_event_tickers` (start dates without per-event calls). Scanner A/B convention: A = the
  market ticker that sorts first.
- Live score: `GET /live_data/batch` (public; up to 100 milestone_ids per call). Points are literal
  0/15/30/40; `server`/`advantage`/`winner` are competitor UUIDs, mapped to A/B via each market's
  `custom_strike.tennis_competitor`; status not_started → started → live → closed. The recorder logs a
  change-only `score/` table (phat-d0/Tennis_Model#21), which is our only source of score-state history.
- Tournament name: `event.product_metadata.competition`. Tour/round/best_of/scheduled start:
  `GET /milestones?related_event_ticker=`. Live score: `GET /live_data/milestone/{id}` (current
  snapshot only, no history).
- Markets settled before `GET /historical/cutoff` (2026-08-25 as of 2026-10-24) are only in
  `/historical/*`; historical candles drop the `_dollars`/`_fp` field suffixes. Not-started
  matches settle at a "fair price", not 0/1 (**the two legs' fair prices sum to exactly $1**: 39/39
  checked, so a held lock still pays $1; 3.9% of recent ATP/WTA matches); a retirement after the
  first ball settles the retiring player's market to No.
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
- Polymarket intl for the page (checked live 2026-10-26, Upsets): gamma `/events?tag_id=864&active=true&closed=false`
  (~7 pages of 100) lists one event per match, titled "City: A vs B", `seriesSlug` atp / wta / itf / *-doubles, with
  **no tier field**. The match-winner market is `sportsMarketType: "moneyline"` (outcomes = the two players, in token
  order); filter on `acceptingOrders`, since played events can stay `active`. CLOB `POST /books` takes many tokens per
  call and **answers 403 without a User-Agent**.
- The Odds API (the-odds-api.com): `draftkings` is the DraftKings **Sportsbook** (region `us`), not
  DK Predictions; region `us_ex` lists Kalshi, Polymarket, Novig, ProphetX, BetOpenly. Tennis sport
  keys and credit costs: docs/research/odds_api.md. **Tennis coverage is tour-level only** (one key
  per tournament, e.g. `tennis_atp_us_open`; 47 keys; no Challenger/ITF and few 250s). `/odds` costs
  markets × regions credits; `/sports` and `/events` are free. DraftKings voids walkovers and
  retirements before set 1 is complete. A sportsbook leg is a
  bet, not a contract: equal-payout sizing is stake = N / decimal_odds, and retirement/void rules
  differ from Kalshi's, so a "lock" across them isn't risk-free when a player retires.
- The Odds API historical snapshots include **in-play** events with DraftKings and Pinnacle quoted (Upsets 2026-10-28,
  from our 6,166 cached snapshots: 28,446 in-play event rows, DK quoted on 23,362, Pinnacle on 21,299; median quote age
  0.8 min). The snapshot interval is 10 min in 2020–22 and 5 min from 2023; one snapshot = 10 credits for h2h with ≤ 10
  bookmakers and covers every event of its key. The docs host isn't reachable from cloud sessions, so this rests on our
  own data (docs/research/odds_api.md §4).
- DraftKings Predictions: **no public/partner API**. ToU (2026-08-04) bans bots/scrapers and
  limits use to personal non-commercial. It's a broker (FCM) routing to CME / Crypto.com / DKeX /
  Bitnomial. Fee ≈ flat $0.02/contract between $0.30 and $0.94. → manual logging only.

## Environment gotchas
- VPS deploy (`deploy/`, docs/scanner_deploy.md): one Docker image; `scanner` + `dashboard` by
  default (dashboard published on 127.0.0.1:8000 only, so it's reached over an SSH tunnel), `recorder`
  behind `--profile recorder`, optional Caddy HTTPS + basic auth behind `--profile public`. Secrets in
  `deploy/.env` (gitignored); holdings in `data/positions.json` (gitignored). **Scanner and recorder
  share the VPS IP and therefore Kalshi's unauthenticated rate limit**. Measured 2026-10-26 (phat-d0/Tennis_Model#109):
  at 252 matches the scanner ran ~1 req/s before its new `scanner.max_rps` cap, and the recorder ~0.45 req/s.
  Together that was 0.95 req/s, with ~1 × 429/min. ITF was dropped and both are capped at 0.5 req/s; at 104 matches the
  pair runs 0.84 req/s with 0 × 429. **Never run a backfill on the same IP as scanner + recorder**: in a trial,
  recorder + backfill together set off a run of 429s.
- Recorded order books (~100 MB/day before compaction) stay on the VPS disk under
  `data/recorded/kalshi/`. They don't go to `data-store`, which is too big for git; Backtest gets
  extracts on request.
- A fresh cloud container may lack pyarrow/pytest: run `pip install -e . pytest` first.
- Cloud sessions are ephemeral: commit and push work before stopping. A long-running
  recorder or scanner can't live in a cloud session; it needs the owner's machine or a server.
- The environment's network policy (Limited, Allowed domains) must list: api.elections.kalshi.com,
  external-api.kalshi.com, docs.kalshi.com, gamma-api.polymarket.com, clob.polymarket.com,
  data-api.polymarket.com, gateway.polymarket.us, api.the-odds-api.com, www.tennis-data.co.uk. On
  2026-10-25 an edit replaced the list and silently cut Kalshi/Polymarket/Odds API; re-check hosts after
  any policy change (proxy `CONNECT 403` = policy denial). tennis-data.co.uk itself returns a Cloudflare
  403 to cloud IPs, so its files are downloaded by the owner. WebFetch can't reach docs.kalshi.com,
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
- 2026-10-24: Not-started matches stay in the backtest: positions settle at `settle_a/settle_b`
  via `Holding.pnl_settled`, not dropped (dropping them would bias unlocked P&L).
- 2026-10-24: Swing entry filters `min_entry_ask` / `max_minutes_from_start` are gate-valid;
  `min_minutes_to_close` uses the match end (lookahead), so it's diagnostic only and walk-forward
  refuses to PASS with it on (phat-d0/Tennis_Model#29).
- 2026-10-24 (Lead): Backfill scope = recent ATP+WTA (6 months) + recent Challenger (group 1); group 2
  (~48.8k older/ITF matches, ~6–7 days at the archive's effective ~0.2 req/s) is **not run**: results are
  uniform, and less bulk collection is lighter on the Kalshi Data ToU. Can run later on a separate
  machine (never the scanner/recorder IP) if the owner asks. No API keys (no read-only scope exists).
- 2026-10-24: Walk-forward: monthly folds by each match's first observation; expanding window;
  select on total P&L at 1¢ slippage with ≥ 10 training trades; training trades must settle before
  the test month; positive-folds check at the worst slippage, and total OOS P&L > 0 at every
  slippage; CI = match-clustered bootstrap. Per-trade CSVs in `reports/` are gitignored (Kalshi
  data is private); only markdown write-ups are committed.
- 2026-10-26 (Lead, after #108): the public page and its Portfolio use the **power de-vig** everywhere (fair chance,
  line rule, expected value, CLV), as every study does (phat-d0/Tennis_Model#112).
- 2026-10-26: Challenger / WTA 125 tier on the page = Sackmann level-C names ("Brest CH", "Queretaro 125"; cities that
  also host a tour-level event of that tour dropped) plus the curated `EXTRA` list in `upsets/polymarket.py`. Unknown
  events are left out and logged, never guessed (phat-d0/Tennis_Model#111).
- 2026-10-28 (Backtest): on Kalshi's paired markets bid(A) = 1 − ask(B) by construction (the normalizer builds both
  from the same two market quotes) and the taker fee is symmetric, so a take-profit at T is the swing lock at
  Y = 1 − T. The cash-out study's new content is Δ vs hold on selection-neutral entries (docs/edge_cashout.md).
  Level exits apply only to entries below L (take-profit only). Set end = a Kalshi set-winner close_time ±3 min
  (ATP/WTA, descriptive). An exit bid's age = the other side's ask age.

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
- 2026-10-24: Order-book recorder merged (phat-d0/Tennis_Model#17): open matches every 600 s,
  `/markets/orderbooks` every 10 s (50 matches per call), quotes + top-5 depth to daily parquet.
  Live trial 10:34 UTC: 90 open matches, combined ask min $0.99 / median $1.01, nothing below fees.
  91 tests passing.
- 2026-10-24: Network-outage handling (phat-d0/Tennis_Model#19): network failures → KalshiError(0);
  the backfill pauses 120 s and retries the match (gives up after ~30 min), the recorder skips one
  snapshot. Full backfill work order: 4,670 recent ATP+WTA → 8,340 recent Challenger → 48,785 others
  (61,795 total). 93 tests passing.
- 2026-10-24: Live-score design (phat-d0/Tennis_Model#20) and recording (phat-d0/Tennis_Model#21)
  merged; `recorder.score_poll_s: 60`. 98 tests passing.
- 2026-10-24: Data checkpoint (phat-d0/Tennis_Model#23): 1,000 recent matches (WTA 577, ATP 423;
  closes 2026-09-06 → 10-24), 1.80 M quote rows, 0.37% NaN asks. Schema: `settle_a/settle_b` added;
  `Holding.pnl_settled`. 99 tests passing.
- 2026-10-24: `settle_a/settle_b` populated by the normalizer (phat-d0/Tennis_Model#25); 100 tests.
- 2026-10-24: Swing backtest settles fair-price matches via `pnl_settled` (phat-d0/Tennis_Model#26);
  103 tests passing.
- 2026-10-24: PRELIMINARY backtest on 2,000 recent ATP/WTA matches (candles, no depth): no edge
  after fees. 25 one-candle true-arb episodes (likely stale quotes); every swing-lock rule negative
  in sample; walk-forward FAIL (3 folds, 0 positive). Details: docs/WORK_PLAN.md "Findings so far".
- 2026-10-24: Entry diagnostics + filters merged (phat-d0/Tennis_Model#29); 107 tests passing.
- 2026-10-24: Entry-diagnostic re-runs: losses aren't from near-decided entries; ≥10¢ entries lose
  ~spread + fee at every X; both gate-valid filters still FAIL. See WORK_PLAN "Findings so far".
- 2026-10-24: Entry window (`min/max_minutes_from_start`) + `entry_phase` filters (phat-d0/Tennis_Model#32);
  108 tests passing.
- 2026-10-24: Group-0 read (4,686 ATP/WTA matches, 6 months): no edge. Swing WF FAIL 0/6 folds (OOS
  −$0.32/trade at 0¢); live-only and first-hour windows also 0/6. After-fee true arbs (≤ 98 episodes)
  are stale/carried quotes. Inventory merged (phat-d0/Tennis_Model#35).
- 2026-10-24: Findings report v1 (`reports/backtest_findings.md`) + `arb_max_leg_age_s` merged
  (phat-d0/Tennis_Model#37); 111 tests passing.
- 2026-10-24: Leg-age arb counts on group 0: 35 episodes / $1.32 at 60 s (0¢); 19 / $0.77 at 1¢.
  Remaining top hits are wide stale offers. Conclusion unchanged.
- 2026-10-24: INTERIM Challenger read (3,000 matches, Aug 24 → Oct 24): no edge; after-fee arbs
  $0.71 total (1 contract); swing −$0.31 to −$0.38/trade OOS, WF FAIL 0/2. Group 1 ETA ~08:00 UTC 10-25.
- 2026-10-24: Data container reclaimed twice (19:56, 20:34); a keep-alive background task fixed it.
  Group 2 descoped (see Decisions).
- 2026-10-25: Second project started: early-round upsets (`upsets/`, docs/upsets_plan.md). The
  pipeline and an Odds API client with a credit floor are built; 122 tests pass, but nothing has run
  on real data yet. Blocked: the network policy denies www.tennis-data.co.uk, and `ODDS_API_KEY` is unset.
- 2026-10-25: Backfill group 1 done (8,333 Challenger matches; inventory phat-d0/Tennis_Model#44). Full
  Challenger read: no edge. After-fee arbs $4.30 (1 contract) and top hits are crossed historical candles
  (84 candles, 5 markets, 2026-05-13); swing WF FAIL 0/6, OOS −$0.39/trade at 0¢. Research set = 13,019
  matches. A normalizer guard for crossed candles has been approved.
- 2026-10-25: Crossed-candle guard merged (phat-d0/Tennis_Model#46); 123 tests passing. Cleaned
  Challenger arbs: $2.89 at 0¢ (1 contract) / $1.25 at 1¢; ATP/WTA unchanged ($2.49 / $1.21). All of it
  is stale or glitched quotes. Kalshi history work is paused until the VPS recorder runs.
- 2026-10-25: Owner added `ODDS_API_KEY` (free plan: ~500 credits/month, no historical odds) and allowed
  tennis-data.co.uk. Upsets role session started to run the study on real data. DraftKings history isn't
  available on the free plan, so Bet365/Pinnacle closing odds stand in for DraftKings.
- 2026-10-25 (owner): the Odds API key is used only by this project. Lead budget: ≤ 400 credits/month,
  floor 50. tennis-data.co.uk is Cloudflare-blocked from cloud IPs, so the owner downloads those files by hand.
- 2026-10-25: Upset preview on Kalshi prices (`upsets/kalshi_preview.py`, phat-d0/Tennis_Model#54, #55;
  `reports/upsets_kalshi_preview.md`): betting early-round underdogs against a ≥ 75¢ favourite lost
  −15.7% (ATP+WTA, 688 bets) and −16.7% (Challenger+WTA 125, 1,151 bets). Underdogs are overpriced, not
  underpriced. 128 tests passing.
- 2026-10-25: Results source: Sackmann's repos now 404; the owner forked the mirror `phat-d0/tennis-sackmann-archive`
  (ATP/WTA 1968 → May 2026, seeds/ranks/rounds, no odds; CC BY-NC-SA). Public, so it's an anonymous git
  clone. tennis-data.co.uk is dropped (Cloudflare blocks cloud IPs).
- 2026-10-25: Upsets phase A merged (phat-d0/Tennis_Model#58; `reports/upsets_findings.md`,
  `reports/upsets_seed_base_rates.md`); 140 tests. 2010–2025, rounds 1–2, seed vs unseeded: seeds lose 29.7%
  (ATP) / 30.1% (WTA), ~2 pp more than Elo expects, mostly vs qualifiers. 42% / 46% of seeds are out by round 2.
  No odds in this data, so no edge claim. Lead re-check matched ATP within 0.2 pp.
- 2026-10-25: Upsets phase B code merged (phat-d0/Tennis_Model#60): Elo (Sackmann + Kalshi results) vs Kalshi
  closing asks, early-round underdogs, monthly walk-forward. Review caught a round-order lookahead; fixed
  (`round_monotone`). 149 tests. Data run pending.
- 2026-10-26: Upsets phase B result (phat-d0/Tennis_Model#63): gate FAIL. OOS 108 bets −15.2% (CI −38% to +7%);
  the market beats Elo on log loss (0.5845 vs 0.6157) and Elo over-rates dogs. In-span unjoined Kalshi rows are
  now no-read. `pip install -e .` fixed for a local data/ dir (phat-d0/Tennis_Model#62). 150 tests passing.
- 2026-10-26: DK history planner/study merged (phat-d0/Tennis_Model#67; dry run ≤ 13,073 credits, waiting on the
  owner's 20K upgrade). Kalshi set-winner collector merged (phat-d0/Tennis_Model#68): ATP/WTA only (no Challenger
  set series); set close_time = set end; Kalshi lists only the sets before the decider. Penultimate-set study
  merged (phat-d0/Tennis_Model#70): the player who levels wins the decider 53.0% (ATP bo3) / 54.5% (bo5) / 53.2%
  (WTA), i.e. momentum ≈ +3 pp per set (symmetric test). Kalshi decider price test running. 171 tests.
- 2026-10-26: Kalshi decider price test: the penultimate-set winner wins 54.8% but costs 53.8% + fee, so
  ROI −0.7% at 0¢ / −2.4% at 1¢ (1,423 bets). Priced in; no edge.
- 2026-10-26: Match-path timeline study merged (phat-d0/Tennis_Model#73, #74, #75); 193 tests. Original favourite wins
  66–72%; ~50% of matches have an in-play favourite flip; set-end prices are calibrated, so no edge at the ask + fee.
  Example timelines/charts go to the owner privately (Kalshi data never committed).
- 2026-10-26: Bet tracker published as a private claude.ai page ("Tennis Bet Ledger", link in WORK_PLAN): manual bet log
  with P&L/ROI/CLV. Its data lives in the page's own store, never in git.
- 2026-10-26 (owner): `ODDS_API_KEY` is now the shared paid plan (≈ 10.9k left). Reserve 5,000. DK history for 250/500s
  approved (≈ 5.4k budget); live recorder capped at 481. Planner extended to all 48 tennis keys
  (phat-d0/Tennis_Model#79, #81).
- 2026-10-26: DK 250/500 study (phat-d0/Tennis_Model#83, #86; `reports/upsets_dk_small.md`, PRELIMINARY): every early-round
  dog −18.7% at DK (417 bets, CI −32% to −6%), −15.6% at Pinnacle; DK margin 4.84% vs Pinnacle 2.82%; Elo WF FAIL (77 OOS,
  −20.5%). 1,646 credits, balance 9,258. Results for Jun–Oct 2026 came from Kalshi settlements (Data), aggregates only.
- 2026-10-26: CI on every push/PR (`.github/workflows/ci.yml`, pandas 3.1 caught a list-truthiness bug). Public Tennis Odds page
  planned (docs/site_plan.md, phat-d0/Tennis_Model#84); page UI merged (phat-d0/Tennis_Model#85); builder + publish workflow pending.
  The page and its build never touch Kalshi data; the builder's `status` must never contain the API key or a URL.
- 2026-10-26 (owner): Odds API plan upgraded to **5M credits/month** (shared with soccer ≈ 5k/month and baseball). 5,000 floor
  kept as a safety net; budgets are now per-job caps in WORK_PLAN. Slams + 1000s DK history approved.
- 2026-10-26 (owner): VPS = Hetzner (Ashburn) with **Tailscale-only** access: one-paste `deploy/cloud-init.yaml` +
  `deploy/bootstrap.sh`, recorder on, no public ports (phat-d0/Tennis_Model#109). ITF series dropped from scanner, recorder
  and backfill defaults. The page model is now tuned Elo + serve/return (#106). Line-shopping drawdown = luck on a thin
  edge (#108); the Portfolio switches to the power de-vig. Challengers come from Polymarket intl, owner OK'd its terms
  (#105, #107). Server live 2026-10-27 (owner set-up done).
- 2026-10-26: Job B, Elo upgrades vs Pinnacle (phat-d0/Tennis_Model#103, `reports/upsets_elo_plus.md`): no edge. On the same
  5,686 matches, log loss is Pinnacle 0.5552, DK 0.5572, current Elo 0.5859, and the best variant (+fatigue+serve) 0.5755.
  Betting the edge at DK walk-forward loses 11.5–14.6% in every variant (CLV −9% to −10.5%). A QF-as-qualifying lookahead in
  the fatigue feature was caught and fixed. 244 tests.
- 2026-10-26: Page model = tuned Elo + serve/return (owner-approved; phat-d0/Tennis_Model#106). Portfolio model backtest
  3,097 bets, −12.4% vs −5.9% expected. Line-shopping drawdown (#108, `reports/upsets_line_shop_drawdown.md`): the run-up was
  +51u above expected (z +1.4), the drawdown −52u (z −1.5), and overall realized = expected (+30u). 246 tests.
- 2026-10-26: Polymarket Challenger / WTA 125 block in `odds.json` (phat-d0/Tennis_Model#111, `upsets/polymarket.py`): 12
  requests per build, no key, 0 credits. Live: 108 matches across 8 events, 69 thin, model chance for 85. A NaN-surface bug
  was fixed. 260 tests.
- 2026-10-26: Power de-vig on the page and Portfolio (phat-d0/Tennis_Model#112). Backtest: line 205 bets +9.2% vs +8.0%
  expected (was 328, +9.2% vs +9.3% proportional); model −12.7% vs −10.8%; dogs −10.4% vs −12.0%. Private Tennis Backtest
  Explorer (claude.ai artifact, owner-only; link in WORK_PLAN): every bet for 21 strategies. 252 tests.
- 2026-10-27 (owner): no manual positions; the server paper-trades pre-registered swing-lock rules live and replays them nightly
  over recorded books (in progress, Scanner/Dashboard).
- 2026-10-27: Paper engine merged (phat-d0/Tennis_Model#116): 4 frozen rules in `swinglock/scanner/paper.py` (`RULES`,
  pre-registered in docs/scanner_paper.md, expected −3 to −5¢/contract); live ledger + nightly lookback (`swinglock-lookback.timer`,
  `python -m swinglock.scanner.lookback`) under gitignored `data/paper/`; state.json gains `paper` and `min_arb_profit_per_contract`.
  Start-up entries are excluded from headline numbers. 273 tests passing. Incident: Scanner's dry-run ledger was committed to
  `team/scanner` (ae08bf5, public); the file is removed and the branch is to be deleted. Always stage explicit paths.
- 2026-10-27: Dashboard Paper tab merged (phat-d0/Tennis_Model#118, #119 adds `contracts` to by_rule): per-contract P&L,
  start-up split, lookback panel; served `/lookback.json` (204 until the first nightly run). 281 tests passing.
- 2026-10-27: Dashboard (Dashboard role): "Arbs open" counts only arbs with profit/contract ≥ `min_arb_profit_per_contract`
  (from state.json, else 0.005); smaller ones get a muted "break-even" tag; tier labels come from `series` (ATP Challenger /
  WTA 125 instead of "challenger") (phat-d0/Tennis_Model#115). Paper contract test made exact against Scanner's own output
  (phat-d0/Tennis_Model#121). Live Paper tab checked on the owner's screenshot at 17:34 UTC start: 9 headline trades
  (8 open, 1 locked), start-up block separate, renders as designed. 281 tests passing.
- 2026-10-28 (owner): memory rule changed. Every role now records its own Changelog/facts/decisions in CLAUDE.md and its
  own row of WORK_PLAN's new **Master plan** (Team rule 7); the Lead keeps the plan's priority order and the owner rules.
  Cash-out study pre-registered (phat-d0/Tennis_Model#123, docs/edge_cashout.md): take-profit Δ vs hold on
  selection-neutral entries, plus the owner's DOG50 (dog < 20¢, cash out at 50¢); expected FAIL.
- 2026-10-28 (owner: "add cash-out as a new portfolio to track live paper trade"): Scanner adds a **cash-out group** to the
  paper engine (phat-d0/Tennis_Model#132). C0-dog20-hold (control), C1-dog20-sell50 (DOG50), C2-dog30-sell50, plus the owner's
  same-day "50-50 or even winning" C3-dog20-sell60 and C4-dog20-sell70, all pre-registered in docs/scanner_paper.md before any
  cash-out result. Semantics = `backtest/cashout.py` (E1/E2 entries, sell all at the bid when the net bid ≥ L with size); the
  lookback calls `simulate_cashout` with each rule's level (70¢ is on #130's dog exit-level curve), and the live engine equals it
  for all five rules. Expected Δ C1 vs C0 −1 to −3¢/contract. Additive contract: `group`, per-rule `since`, `exit` event, status `exited`.
  Live dry run (C0–C2): 60 matches, C0/C1 12 and C2 24 start-up entries, 20 requests in 36 s. 316 tests pass + 2 Dashboard
  contract tests that need its update.
- 2026-10-28: Portfolio ledger restore (phat-d0/Tennis_Model#129, `upsets/site.py` `restore`, Lead-approved). The paper ledger
  and the month's page spend lived only in the Actions cache. Each build now merges the live page's `portfolio.json` (by
  trade id; the cache's copy wins) and takes this month's `used_this_month` from its `odds.json`, keeping the larger value.
  A cold cache plus an unreadable page stops the build, so nothing deploys; a 404 starts an empty ledger with a loud log
  line. Nothing is committed. 290 tests (pandas 2 and 3.1).
- 2026-10-28 (owner): "add seed losing early as a portfolio". Pre-registered in `reports/upsets_seed_portfolio.md`
  (phat-d0/Tennis_Model#131): in R1/R2, back the unseeded player vs a seed at DK, with sub-rules all / qualifier-LL / other.
  Gate: ≥ 30 bets, P&L > 0, ≥ 3 of the last 4 seasons positive. Expected negative. The Explorer's seeded-favourite slice
  (2,894 bets, ≈ −11%) was already seen, and the doc says so. Live seeds will come from Wikipedia (MediaWiki API, CC BY-SA;
  Lead's choice) and R1/R2 from a labelled proxy. No code yet; 0 credits.
- 2026-10-28: "Seed loses early" backtest (phat-d0/Tennis_Model#134, `upsets/seed_portfolio.py`, `reports/upsets_seed_portfolio.md`):
  **gate FAIL for all 3 pre-registered sub-rules.** All: 3,123 bets, −10.3% at DK vs −14.2% expected at Pinnacle-fair.
  Qualifiers/LL: 538 bets, −8.2% (3 of 4 recent seasons positive, but −44u in total). Unseeded DK favourites: 269 bets,
  −1.7%. Seeds 1–4: −30%. 0 credits; identical output under pandas 3.1; 311 tests.
- 2026-10-28: "Seed loses early" live Portfolio strategy (phat-d0/Tennis_Model#137): two new rows, "seed" (label "backtest:
  −10.3%, not proven") and "seed_q" (the qualifier sub-line). Seeds and qualifiers come from Wikipedia's draw articles
  (`upsets/wiki_seeds.py`: MediaWiki API, descriptive User-Agent, ≤ 2 titles per event per build, cached once parsed). The
  parse is strict (4/8/16/32 linked seeds, else skipped and logged). Rounds 1–2 use a proxy: the seed's first or second
  listed match in that event. Backtest rows from Sackmann seeds: seed 3,100 bets −10.4%, seed_q 535 −9.7%. The parser is
  tested on a **synthetic** fixture, since en.wikipedia.org isn't reachable from cloud sessions. 0 credits. 320 tests.
- 2026-10-28: Pre-match Elo rank export for MISMATCH50 (phat-d0/Tennis_Model#141, `upsets/elo_ranks.py`, CLI
  `python -m upsets.elo_ranks --data <dir> [--data <dir>] --sackmann <archive> --out <parquet>`). Output: match_id and
  integer rank_a, rank_b (A/B as in matches.parquet; + elo, n, matched, pool) for Kalshi ATP/WTA tour + Challenger/WTA 125
  matches. It uses phase B's timeline (guards intact) and ranks among each tour's active players (≥ 10 rated matches, played
  in the last 365 days). **No lookahead:** a player's own Elo uses only his earlier matches; the pool only counts matches
  that started ≥ 6 h before the match's day began. A test flips later results and checks the ranks don't move.
  Unmatched names are left blank. Synthetic check on the real archive: ~99.6% of names matched, 38 s per 3,000 matches,
  Sinner #1, Alcaraz #2. Data runs it; nothing committed. 341 tests (pandas 2 and 3.1).
- 2026-10-28: Live Elo rank table for the VPS paper engine (phat-d0/Tennis_Model#144): `upsets.elo_ranks.current()` and CLI
  `python -m upsets.elo_ranks current --sackmann <archive> [--results <matches.parquet>] --out data/paper/elo_ranks.json`
  (atomic write). Per tour: active players by rank, with key (name_key), name, sackmann_id, elo, n and last_played,
  plus generated_at, sackmann_through and results_through. Loading from 2010 peaks at 887 MB RSS and takes 17 s
  (1990: 1,346 MB, 31 s); top-300 ranks differ from the 1990 load by a median of 2–4 places. Scanner owns the nightly job
  (Lead, pending the MISMATCH50 backtest). 120-day staleness skip pre-registered in the PR. 342 tests.
- 2026-10-28: Elo rank export follow-ups. #142 put the lagged pool (6 h replay), integer ranks and the flip test on main
  (#141 had merged before them). phat-d0/Tennis_Model#145 adds `reason_a`/`reason_b` for MISMATCH50-U (owner: account for unranked players):
  null when ranked, else `unmatched` (name not found), `few_matches` (< min_n rated matches; elo/n keep the provisional
  rating) or `inactive` (empty active pool on the match day; a player's own activity isn't required for a rank, so this
  is rare). rank_a/rank_b unchanged. The CLI summary prints the reason counts. 7 rank tests; 344 tests (pandas 2 and 3.1).
- 2026-10-28: Wikipedia seeds back off on HTTP 429 (phat-d0/Tennis_Model#154). en.wikipedia.org is now allowed, but the
  MediaWiki API answers 429 "too many requests" to the cloud sessions' shared IP (4 calls from Upsets, 1 from the Lead), so
  the real-draw fixture is still synthetic. `wiki_seeds` never retries a 429: it writes `wiki_backoff.json` (Retry-After,
  at least 10 min, at most 1 day) and skips every Wikipedia call until then, the rest of that build included. The seeds
  log says "no scored tournaments in view" when there is nothing to look up. 348 tests (pandas 2 and 3.1).
- 2026-10-28 (owner: "make sure all these are for the app too, not just the Kalshi bets"): plan for DK in-play versions of
  DOG50, the exit-level curve, MISMATCH50 and the new FAVDIP (favourite 60–80% / ≥ 80% at DK's close, bought at 50% in play
  vs at the start). Pre-registered in `reports/upsets_dk_inplay.md` (phat-d0/Tennis_Model#157); a cash-out at DK = hedge to
  equal payout. Credit dry run `python -m upsets.dk_inplay plan`: 2023–May 2026 (4,673 matches) costs 200k–239k credits at
  10 min and 398k–476k at 5 min. Proposed cap 270k (10 min + 5-min refinement before triggers); live poll ≈ 5–7k/month at
  10 min. **Nothing pulled; 0 credits.** Owner approved a 300,000-credit cap (Lead, same day): pilot ≤ 2,000 first, live
  tracking plan-only until the backtest is in. 3 new tests; 351 tests (pandas 2 and 3.1).
- 2026-10-28: DK in-play **pilot** (phat-d0/Tennis_Model#PRNUM; Lead-approved plan: 2023–May 2026, 10 min + 5-min refinement,
  cap 270,000 within the owner's 300k). `python -m upsets.dk_inplay pull` walks each key's snapshots in time order and stops
  a match after 3 snapshots without its event. Pilot: ATP Qatar 2025, 24 matches, 175 snapshots, **1,750 credits** (job log),
  vs 1,870 planned. DK is quoted on 236 and Pinnacle on 235 in-play rows; DK quote age median 1.1 min, 90% ≤ 5 min. The pilot
  found 2 bugs, fixed and replayed from cache: DK moves commence_time, so events are now matched by player names (apostrophes
  ignored); never-found matches stop too. After the fix 23/24 resolve and finish is detected for all 23 (median 140 min after
  commence); the walk needs 168 snapshots (≈ 90% of plan), so the full pull projects to ≈ 215k + refinement. In-play
  snapshots are cached apart (`data/raw/odds_api/inplay/`): mixed into the close cache they changed dk_history's closes.
  No outcomes read. Full pull waits on the Lead. 363 tests (pandas 2 and 3.1).
- 2026-10-28 (Backtest): cash-out study code merged (phat-d0/Tennis_Model#125): `swinglock/backtest/cashout.py`, CLI
  `python -m swinglock.backtest.cashout --data <dir> [--sets <dir>/sets.parquet]`. Dated amendment (before any run):
  Level exits (12 gate rules), DOG50 fixed-rule gate on absolute P&L, DOG30 descriptive, set-end split (descriptive),
  stale-bid share; pandas 3.1 Period fix in walk-forward. Output is aggregates only. Not yet run on data (Data runs it
  on groups 0 and 1). 305 tests passing (pandas 3.0.5 and 3.1.0).
- 2026-10-28 (Backtest): cash-out amendment 2 (owner: "cash out a heavy dog at 50-50 or better"): a dog exit-level
  curve (L 0.40–0.90 + hold; P&L, ROI, Δ, SD, P10, stale-bid share, for < 20¢ and < 30¢) and the DOGL walk-forward on L
  (hold always eligible; ≥ 30 OOS positions). Pre-registered expectation: every L loses, holding is cheapest, FAIL. Not run yet.
  308 tests passing (pandas 3.0.5 and 3.1.0).
- 2026-10-28 (Backtest): **cash-out study result** (`reports/backtest_cashout.md`; Data's run on 4,695 ATP/WTA + 8,349
  Challenger/WTA 125 matches, candles). **Every gate FAILs** (E1, E2, DOG50, DOGL in both groups), as pre-registered.
  Dogs < 20¢: every exit level 40–90¢ is within ±1¢/contract of holding; DOG50 ROI −10.7% / −21.7% at 0¢ (−18.8% /
  −28.7% at 1¢). Selling lowers SD only by capping the upside; P10 (lost stake) is unchanged. In-play take-profits cost
  −2¢ to −5¢ per triggered contract and cut SD a lot. Set end vs mid-set: no difference. E1 entries are mostly
  opening-book asks (82–87% at ≥ 80¢). Identity bid(A) = 1 − ask(B): max gap 0 over 17.3 M rows.
- 2026-10-28 (Backtest): cash-out amendment 3, MISMATCH50 (owner: "#20 vs #200 goes to 50-50 often"). Buy the worse-ranked
  player (pre-match Elo rank proxy, ratio ≥ 4×, better ≤ 100) at E1/E2, sell at net bid ≥ 50¢. Reports reach-50 vs the
  price-implied rate, P&L/ROI/Δ/SD/P10 by tier and rank-ratio bucket, and the DOG50 overlap; same fixed-rule gate.
  CLI `--ranks` (match_id, rank_a, rank_b). Expected FAIL. Not run yet (waits on Upsets' rank export). 335 tests passing
  (pandas 3.0.5 and 3.1.0).
- 2026-10-28 (Backtest): cash-out amendment 4, MISMATCH50-U (owner: "include unranked players"). Buy the unranked player
  (NaN pre-match Elo rank; assumed below the active pool, labelled) vs a player ranked ≤ 100, at E1/E2, sell at net bid
  ≥ 50¢. Reported apart from MISMATCH50, by unranked reason (`reason_a`/`reason_b`: few matches / inactive / unmatched)
  with an entry-price distribution per reason; same fixed-rule gate. Expected FAIL. Not run yet.
  341 tests passing (pandas 3.0.5 and 3.1.0).
- 2026-10-28 (Backtest): **MISMATCH50 result** (`reports/backtest_cashout.md` §6; Data's run at c018be0, sections
  sha256-checked): **FAIL** in both groups (0/7 months). The worse-ranked player reaches 50¢ less often than the price
  implies, in every rank-ratio bucket (ATP/WTA 34.1% vs 38.4% at 1¢). In-play ROI −16.0% (ATP/WTA, 946) / −9.4%
  (Challenger, 125) at 1¢. **E1 is invalid everywhere**: the first pre-match row is a listing-time placeholder book
  (median ask_a + ask_b $1.84 / $1.88), now said so in the report. Amendment 5 adds E1r (first pre row with
  ask_a + ask_b ≤ $1.05) for every E1 use, post hoc: verdicts reported but not counted; re-run with MISMATCH50-U.
  Unranked reason `inactive` is "not observed (by construction)" (Upsets #145).
  346 tests passing (pandas 3.0.5 and 3.1.0).
- 2026-10-28 (Backtest): **MISMATCH50-U and E1r results** (`reports/backtest_cashout.md` §7–§8; Data's single run on main
  ad76187, 4 sections sha256-checked). MISMATCH50-U **FAIL** in both groups (ATP/WTA 0/6 months, −$250.93 at 1¢, 73 positions,
  8 sales; Challenger 0/5, −$103.29, 28, 1 sale). "Unranked" ≠ underdog: median entry ask 60–66¢ except Challenger
  few-matches (14¢), and 50–63% of entries cost over 50¢. Reason `inactive` not observed (by construction). E1r (post hoc,
  not counted): formed pre-match book for 98.5% / 99.5% of matches; take-profit WF, DOG50, MISMATCH50 and U all FAIL in both
  groups; every take-profit Δ is negative (−2¢ to −6¢ per sale ATP/WTA at 0¢). No conclusion changes. Report only; 346 tests.
- 2026-10-28 (Backtest): **fallen-favourite study pre-registered and built** (owner, via the Lead; docs/edge_favdip.md,
  `swinglock/backtest/favdip.py`, CLI `python -m swinglock.backtest.favdip --data <dir> [--sets <dir>/sets.parquet]`).
  Favourite = higher ask at the last formed pre-match row (ask_a + ask_b ≤ $1.05), bands 60–80 / 80–97 (50–60 context).
  START (buy then) vs DIP50 (first formed live row with its ask ≤ 50¢; DIP45/40 descriptive), held to settlement; DIP50
  gated per band as a fixed monthly rule. Expected: START ≈ −2% to +1%, DIP50 −3% to −6%, FAIL. Aggregates only; not run
  yet (Data runs it). phat-d0/Tennis_Model#156; 9 new tests, 357 passing (pandas 3.0.5 and 3.1.0).
- 2026-10-28 (Backtest): **fallen-favourite result** (`reports/backtest_favdip.md`; Data's run on main 98fa42c, both summaries
  sha256-checked). **No: buying the favourite at a 50¢ dip does not beat buying it at the start; all 4 DIP50 gates FAIL.**
  ROI at 1¢, START vs DIP50: 60–80¢ ATP −6.3% vs −15.0%, WTA −5.0% vs −7.9%, Challenger −4.5% vs −6.1%; 80–97¢ ATP −1.8% vs
  −12.1%, Challenger −1.1% vs −3.4%. A 50¢ fallen favourite wins less often than its all-in price in 5 of 6 gated cells
  (ATP 60–80¢ 42.0% vs 48.4¢). WTA 80–97¢ DIP50 +11.2% (132 entries, CI −6% to +28%) is the post-hoc outlier, not a finding.
  About half of 60–80¢ and a quarter of 80–97¢ favourites dip to 50¢. Report only.
- 2026-10-28 (Data): cash-out study run locally on main e41c055 (with #130); 0 Kalshi requests, 308 tests passing.
  g0 (4,695 ATP/WTA) and g12 (8,349 Challenger/WTA 125): every gate FAILs. DOG50 at 1¢: g0 −$226.07 (ROI −18.8%, 2/7 months +),
  g12 −$641.46 (−28.7%, 0/7); DOGL g0 1/6, g12 0/6 folds +; E1/E2 FAIL on both. bid(A) = 1 − ask(B) exactly (max gap 0).
  Aggregates sent to Backtest verbatim with sha256 per section; outputs stay in gitignored `data/reports/`.
- 2026-10-28 (Data): MISMATCH50, MISMATCH50-U and E1r runs (main c018be0 then ad76187; ranks from `upsets.elo_ranks`, 13,042 matches,
  both ranked 80.2–97.9% by series; unranked: few_matches 1,052, unmatched 705). Two earlier runs were stopped and deleted unread
  (a rank lookahead fix #142, then #148). **All FAIL.** MISMATCH50 at 1¢: g0 −$6,522.58 (ROI −63.6%, 1,916 entries), g12 −$679.17
  (−56.1%, 251); E2 only g0 −16.0%, g12 −9.4%; the worse-ranked player reaches 50¢ less often than the price implies (g0 34.1% vs 38.4%).
  U: g0 73 entries / 8 triggers, ROI −54.7%; g12 28 / 1, −73.3%; unranked players are often priced as favourites (median ask 0.60–0.66).
  **Found:** the first `pre` row is the listing-time placeholder book (median ask_a + ask_b $1.84 g0 / $1.88 g12), so E1 measured
  the empty book; Backtest's post-hoc E1r (first pre row with combined ask ≤ $1.05, not counted) also FAILs everywhere.
  346 tests passing; 0 Kalshi requests; aggregates sent verbatim with sha256.
- 2026-10-28 (Data): fallen-favourite run (`swinglock.backtest.favdip`, main 98fa42c, #156) on g0 + g12; 357 tests, 0 Kalshi requests.
  **Every DIP50 gate FAILs.** ROI at 1¢, START vs DIP50: 60–80 ATP −6.3% vs −15.0%, WTA −5.0% vs −7.9%, Challenger −4.5% vs −6.1%;
  80–97 ATP −1.8% vs −12.1%, Challenger −1.1% vs −3.4%, WTA −0.7% vs +11.2% (132, CI −6% to +28%, 1 of 12 cells: noise).
  g0 80–97 total P&L +$14.89 at 1¢ but only 3/7 months positive. Fallen favourites win about what they cost (g12 60–80: 46.6% vs
  46.8% ask). Dip50 share: 56–59% (60–80), 22–24% (80–97). Set 1 before/after: no difference.
- 2026-10-28 (Dashboard): Paper tab shows the cash-out portfolio C0–C4 (owner request; phat-d0/Tennis_Model#136 with Scanner's
  #132): its own section "Cash-out portfolio (pre-registered 2026-10-28)" with open/exited/final, exit rate, final P&L
  (settled + sold), P&L per contract, **Δ vs C0 per contract on paired entries** (same match, side and E1/E2, both final) and
  the **spread of outcomes** (SD of P&L per contract, with the range); exits show as "sold @ bid"; start-up entries use each
  rule's own `since`; the lookback gets a cash-out table (Δ vs C0 at 0¢/1¢) and its own chart. Contract tests run Scanner's
  swing and cash-out code: 20/20 dashboard tests pass on #132's head (74528a3); 311 passed + 2 skipped on main.
- 2026-10-28 (Dashboard): public page labels Upsets' new Portfolio strategies ("Seed loses early", "Seed loses early
  (qualifiers)", phat-d0/Tennis_Model#137) and credits their seed source in the footer: "Seeds and qualifiers for the 'Seed
  loses early' strategies: Wikipedia (CC BY-SA)". Service-worker cache v5. 14 site tests passing.
- 2026-10-28 (Dashboard): Paper tab in the soccer app's folder layout (owner request): home lists the portfolios (Swing-lock
  P1–P4, Cash-out C0–C4) with their P&L; a portfolio shows its strategies as rows (live P&L, per contract, Δ vs C0, a
  "Lookback:" line) plus its summary table, trades and lookback; a strategy has Live paper / Backtest. Everything on the old
  page stays reachable. The browser check walks every level; it now writes its result before exiting (a large result was
  cut at 64 KB). 323 tests passing.
- 2026-10-28 (Dashboard): public page Portfolio tab in the soccer app's folder layout (owner request; phat-d0/Tennis_Model#150):
  home lists 4 portfolios (Elo model, DK vs Pinnacle, Underdogs, Seed loses early), Seed loses early holds 2 strategies
  (all / qualifiers), the strategy page keeps "not proven", the rule and Live paper / Backtest. A second tap on the tab
  goes home. Nothing removed; no Kalshi data. Service-worker cache v6. 14 site tests passing.
- 2026-10-28 (Scanner): paper C rules checked against Kalshi's placeholder listing books (combined ask ≈ $1.84): no rule
  opens on them, but **E1 is effectively consumed by the placeholder listing book; live C entries are E2 apart from the
  start-up batch**. P1–P4 unaffected. No rule change (Lead); dated note in docs/scanner_paper.md.
- 2026-10-28 (owner): mismatch idea ("#20 vs #200 often goes 50-50") tested as MISMATCH50 / -U (#140–#148, #152): FAIL; the
  worse-ranked player reached 50¢ less often than its price implied (34% vs 38% ATP/WTA). E1 (first pre-match look) found to be
  Kalshi's placeholder listing book (combined ask ≈ $1.84); E1r robustness (post hoc) changes nothing. Owner's soccer-style folder
  layout for the dashboard Paper tab (#149) and the page Portfolio (#150). Live MISMATCH50 not built (Lead, after the FAIL).
- 2026-10-28 (owner): DK in-play studies approved with a **300,000-credit cap** (Odds API historical snapshots; pilot ≤ 2,000 first;
  floor 5,000). Fallen-favourite study requested (Kalshi now, DK after). Owner allowed en.wikipedia.org (Wikimedia answers 429 to cloud IPs).
- 2026-10-27: Paper trading live on the server from 17:34 UTC. Owner deleted `team/scanner`; no ref holds ae08bf5 now (an orphaned
  commit can still be fetched by full SHA until GitHub's GC; GitHub Support can purge it).
- 2026-10-26: **Tennis Odds page live** at https://phat-d0.github.io/Tennis_Model/ (GitHub Pages, `.github/workflows/publish.yml`,
  every 3 h, ≤ 3,000 credits/month; phat-d0/Tennis_Model#85, #89–#92). Name matching moved to `upsets/names.py` (token-sorted
  keys + aliases). The cloud container can't reach github.io (network policy), so check runs via the Actions log.
