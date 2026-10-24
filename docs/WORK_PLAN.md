# Work plan

Status for the swing-lock / arbitrage project. Only the Lead edits this file; roles propose
updates in their PR descriptions. Durable rules and facts are in `CLAUDE.md`.

## Done
| # | What | Result | Where |
|---|---|---|---|
| 1 | Core math | Fee model (per-series fee_type/multiplier), true arb, swing-lock quote, max lock price; worked example reproduced (lock +$0.83 vs brief's rounded +$0.84; unmatched +$7.74 / −$8.44) | `swinglock/fees.py`, `locks.py`, `tests/test_locks.py` |
| 2 | Config, positions loader, data schema | — | `config.yaml`, `swinglock/{config,positions,schema}.py` |
| 3 | DraftKings + Polymarket research | DK: no sanctioned API, ToU bans bots. Polymarket intl: public APIs, but US users can't trade there. Polymarket US: own read API | `docs/research/other_venues.md` |
| 4 | Backtest engine v1 (synthetic-data tests only) | Align, arb scan, swing sim, metrics, grid, CLI. Not yet run on real data | `swinglock/backtest/` |
| 5 | Kalshi API research | see doc | `docs/research/kalshi_api.md` |
| 7 | Walk-forward gate + findings skeleton | `walkforward.py` (monthly folds, purged expanding window, match-clustered bootstrap CI); 37 tests, synthetic only, not run on real data | `swinglock/backtest/walkforward.py`, `reports/backtest_findings.md`, phat-d0/Tennis_Model#2 |
| 8 | Scanner v1 | REST polling, discovery (95–96 open matches across 6 series), effective ask/bid with depth, arb + lock alerts with dedup/re-alert, `state.json`, read-only test. Live pass 2026-10-24 09:14 UTC: best combined ask $1.00, no arb. ~0.22 req/s steady state | `swinglock/scanner/`, `docs/scanner_live.md`, phat-d0/Tennis_Model#3 |
| 9 | Dashboard v1 | Stdlib server + static page (no CDN), alerts / markets / positions, stale + offline banners; Lead-verified at 390×844 and 1280×800 light/dark on real scanner output, no errors or overflow | `swinglock/dashboard/`, phat-d0/Tennis_Model#5 |
| 10 | Dashboard filters | Search, phase filter, "No market" group; 61 tests | phat-d0/Tennis_Model#8 |
| 11 | Kalshi collector + backfill | Read-only client (throttle, 429 backoff, gz raw cache → resumable), normalizer (effective ask/bid, no trade/mid), historical split handled; trial 3 ATP matches → 4,888 quote rows, winners correct. Odds API research (0 credits) | `swinglock/collectors/`, `docs/data_*.md`, `docs/research/odds_api.md`, phat-d0/Tennis_Model#9 |
| 12 | Candle carry-forward check | Valid: candles are written on quote changes (live check 140/144 matches); `data.max_carry_s` cap = 1800 s | phat-d0/Tennis_Model#11 |
| 13 | VPS deploy | Docker compose (scanner + dashboard; recorder and Caddy as profiles), systemd, logrotate; owner setup ~20 min | `deploy/`, `docs/scanner_deploy.md`, phat-d0/Tennis_Model#13 |
| 14 | Backfill work order + batch candles | Recent ATP+WTA first; shared candle calls for post-cutoff markets (~3 matches/call; cap = requested candles) | phat-d0/Tennis_Model#15 |
| 15 | Order-book recorder | 10 s snapshots of all open match books (top-5 depth), daily parquet; trial: 90 matches, min combined $0.99, nothing below fees | `swinglock/collectors/recorder.py`, phat-d0/Tennis_Model#17 |
| 16 | Network-outage handling | Backfill pauses and retries instead of saving quote-less matches | phat-d0/Tennis_Model#19 |
| 17 | Live score recording | Recorder logs set/game/point state every 60 s via `/live_data/batch`, A/B mapped, change-only | `docs/data_live_score.md`, phat-d0/Tennis_Model#20, #21 |
| 18 | Backfill checkpoint | 1,000 recent ATP/WTA matches, 1.80 M quote rows; 3.9% not started (fair prices sum to $1) | `docs/data_inventory.md`, phat-d0/Tennis_Model#23 |
| 19 | Fair-price settlement end to end | Normalizer fills settle_a/b (#25); backtest settles not-started matches at fair prices instead of dropping them (#26) | phat-d0/Tennis_Model#24, #25, #26 |
| 20 | Findings report v1 + leg-age arb filter | `reports/backtest_findings.md` answers the owner's question (no edge on 6 months ATP/WTA); `arb_max_leg_age_s` for a stale-leg-free arb count | phat-d0/Tennis_Model#37 |
| 6 | Team set up | 4 role sessions started 2026-10-24 on `team/*` branches (IDs in `docs/team/lead.md`) | phat-d0/Tennis_Model#1 |

## Findings so far (PRELIMINARY: 1-min candles, no depth; run locally by Data, aggregates only)
**2026-10-24, group 0 = 6 months of ATP+WTA (4,686 matches, closes 2026-04-24 → 10-24; 5.09 M aligned
observations, 12% live; 161 fair-price settlements included via settle_a/b):**
- **True arb:** combined < $1 before fees in 2.46% of observations (0.99: 109,629; 0.98: 13,821;
  ≤ 0.95: 127). After fees: 98 episodes in 40 matches at 0¢ (26 in 18 at 1¢), median one candle, sum of
  1-contract profits $2.49, depth unknown. The top ones are stale pre-match quotes (NAKBAE 21¢; PELMAN
  13¢ used a *carried* leg; CHOVAN 13¢ with zero volume). **98 is an upper bound**: the 1800 s carry cap
  can pair a stale leg with a fresh one. Read: no executable true arb.
- **Stricter arb count (`arb_max_leg_age_s`, both legs' asks changed within N s):** 0¢: 98 → 40
  episodes (300 s) → 35 in 26 matches (60 s), $1.32 total 1-contract profit; 1¢: 19 in 15 matches
  ($0.77) at either setting. All single-candle, depth unknown. It removes carried-leg cases (PELMAN)
  but not wide stale offers that tick by 1¢ (NAKBAE 21¢, CHOVAN 13¢: zero volume, 3 days pre-match).
  Conclusion unchanged: ~$1 of one-contract profit in 6 months of ATP/WTA is not a tradeable edge.
- **Swing grid:** every rule negative. Best X=0.20/Y=0.90: 4,509 trades, 48.8% locked, −$1,374 at 0¢
  (−$0.30/trade), −$2,023 at 1¢.
- **Walk-forward: FAIL, 0 of 6 folds positive** (May–Oct). OOS 4,432 trades: mean −$0.32/trade
  (95% CI −0.37 to −0.28) at 0¢, −$0.47 (CI −0.52 to −0.43) at 1¢.
- `entry_phase: live`: WF FAIL 0/6, OOS mean −$0.27 (0¢) / −$0.43 (1¢).
  First hour of play only (window 0–60 min): WF FAIL 0/6, OOS mean −$0.27 / −$0.42; 3,108 OOS trades.
- **INTERIM Challenger (3,000 matches: ATP Challenger 2,298 + WTA 125 702; closes 2026-08-24 → 10-24;
  1.25 M aligned obs, 29% live; 51 fair-price settlements):** combined < $1 before fees in 1.97% of obs.
  After fees: 31 episodes in 15 matches at 0¢ ($0.71 total 1-contract profit, best 6¢ live); 17 at 1¢
  ($0.23); leg-age 60 s: 18 episodes, all live, $0.34. No 20¢ stale outliers like ATP/WTA. Swing grid:
  every rule negative (best first/0.20/0.96: 2,934 trades, 58% locked, −$1,067 at 0¢). Walk-forward FAIL
  0/2 folds (default −$0.38/trade, live-only −$0.32, first hour −$0.31 at 0¢). Same picture as ATP/WTA.
- **Answer so far:** on 6 months of ATP/WTA candles (and an interim 2 months of Challenger), neither true arbs nor swing locks have an edge
  after fees and the ask spread. The gate fails on sign, not just sample size.

**Earlier read (superseded by the group-0 read above):**
**2026-10-24, 2,000 recent ATP/WTA matches (closes 2026-08-03 → 10-24; 2.10 M aligned observations, 12% live):**
- **True arb:** combined ask < $1 before fees in 2.0% of observations (almost all at 99¢; 0.98: 4,072;
  ≤ 0.95: 30). **After fees: 25 one-candle episodes in 14 matches** (11 at 1¢ slippage), depth unknown.
  The biggest (21¢, NAKBAE, 3 days pre-match, zero volume) was a stale offer in a thin book. Read:
  no tradeable true arb in recent ATP/WTA candles; the after-fee hits look like stale-quote artefacts.
- **Swing-lock grid (in sample): every rule loses.** Best: X=0.20, Y=0.92 → 1,910 trades, 51.6% locked,
  −$605 total (−$0.41/trade) at 0¢; −$900 at 1¢. Locked trades average +$1.11, unlocked −$1.86.
  Live entries lose more than pre-match ones (−$455 vs −$150).
- **Walk-forward gate: FAIL**: 3 folds (need 4), 0/3 positive; OOS −$361 at 0¢ (mean −$0.36/trade,
  95% CI −0.45 to −0.27), −$537 at 1¢.
- **Entry diagnostics (#29 re-runs, same 2,000 matches, Y=0.92):** losses are *not* from near-decided
  entries: only 1–3% of entries are < 10¢ (and those are slightly positive). Entries ≥ 10¢ lose at
  every X, more as X rises (P&L/trade −$0.33 at X=0.20 → −$1.09 at X=0.50; higher X enters earlier,
  mostly pre-match). `min_entry_ask 0.10`: slightly worse (−$623, WF FAIL). `max_minutes_from_start 60`:
  same −$0.36/trade (fewer trades; WF FAIL). Note: that filter caps entries *after* the start and
  still allows pre-match ones.
- **Interpretation (Lead):** the ~3–4¢/contract loss ≈ ask spread + taker fee, which is what fairly
  priced markets cost you. The +$1.11 locked vs −$1.86 unlocked split is selection (trades that
  happened to swing), not an edge. A swing lock = two taker round-trips; it only pays if prices
  are predictable, and nothing so far says they are.
- Not yet covered: older months, Challenger/ITF, real depth (needs the recorder), score-state splits,
  fair-price settlements (this checkpoint predates `settle_a/b`).

## Live configuration
- Scanner thresholds: placeholders in `config.yaml` (`min_arb_profit_per_contract` 0.5¢,
  `min_lock_profit` $0.05). None backed by a backtest yet.
- Slippage: 0¢ default; backtests also report 1¢.

## Open items (being watched)
- **Repo visibility:** the owner is making `phat-d0/Tennis_Model` private. No data goes on
  `data-store` until the Lead confirms it's private.
- **The Odds API budget:** the owner's key is shared with their soccer and baseball apps. We need the
  monthly credit budget, a floor, and the key added as `ODDS_API_KEY` in the cloud environment's
  secrets. Until then, Data does docs research only (free endpoints like `/sports` don't cost credits).
- **VPS:** ready to deploy, recorder included (`--profile recorder`). The owner provisions a
  1 vCPU / 1 GB Ubuntu server (≥ 20 GB disk for ~100 MB/day of recorded books) and follows
  `docs/scanner_deploy.md` (~20 min). **Every day without the recorder is order-book history lost.**
- **Fee constants:** the owner should confirm the KXATPMATCH / KXWTAMATCH rows at
  kalshi.com/fee-schedule (the site blocks scripts), and say whether the account is direct or via
  an FCM (this sets fee-rounding precision).
- **Odds API coverage is tour-level only** (no Challenger/ITF), so the DraftKings cross-venue check
  only applies to big ATP/WTA events.
- **Backfill durability:** it runs in the Data session's ephemeral container and can't be pushed
  until the repo is private. The raw cache makes reruns resumable.
- Historical depth: Kalshi candles have no depth and sample at 1 minute. Order-book history only
  starts when the recorder runs, so record early.

## Next steps (in order)
0. Data: finish group 1 (recent Challenger, ~4,600/8,339 at 23:26 UTC; ~12 h at the archive's ~0.2 req/s),
   then full Challenger read. Group 2 (older/ITF) descoped; see CLAUDE.md Decisions.
1. Data: backfill the most recent ~6 months of ATP + WTA first (batch candles for post-cutoff
   markets), then Challenger/ITF/older; re-normalize with the carry cap; publish to `data-store`
   once the repo is private. Restarted 10:20 UTC in the new order; recent ATP+WTA slice (~4–5k
   matches) ETA ~13:00–13:30 UTC.
2. Backtest: arb scan + swing grid on the backfill; then walk-forward gate; then findings report.
3. Data: The Odds API (DraftKings Sportsbook tennis
   h2h) + Polymarket US collectors for the cross-venue check.
4. Scanner: cross-venue alerts once Data's Odds API / Polymarket US collectors exist. A
   WebSocket upgrade needs a read-scope Kalshi API key from the owner.
5. Lead: consolidate the scanner's GET-only client (`swinglock/scanner/client.py`) with Data's
   collector client once it lands.
6. Lead: README covering how to run each part.

## How to continue in a new session
Read `CLAUDE.md`, this file, and your brief in `docs/team/`. Check open PRs into `main` and the
`team/*` branches. The Lead's session ID and the role session IDs are in `docs/team/lead.md`.
