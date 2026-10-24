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
| 6 | Team set up | 4 role sessions started 2026-10-24 on `team/*` branches (IDs in `docs/team/lead.md`) | phat-d0/Tennis_Model#1 |

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
- **VPS:** the owner chose a small cloud server for the scanner + recorder. Scanner prepares the
  Docker/systemd setup; the owner provisions the server.
- **Fee constants:** the owner should confirm the KXATPMATCH / KXWTAMATCH rows at
  kalshi.com/fee-schedule (the site blocks scripts), and say whether the account is direct or via
  an FCM (this sets fee-rounding precision).
- Historical depth: Kalshi candles have no depth and sample at 1 minute. Order-book history only
  starts when the recorder runs, so record early.

## Next steps (in order)
1. Data: Kalshi client + normalizer + backfill → `data-store`.
2. Backtest: arb scan + swing grid on the backfill; then walk-forward gate; then findings report.
3. Data: order-book recorder; live score/state join; The Odds API (DraftKings Sportsbook tennis
   h2h) + Polymarket US collectors for the cross-venue check.
4. Scanner: VPS deploy (`deploy/`: scanner, recorder, dashboard as services), then cross-venue
   alerts. A WebSocket upgrade needs a read-scope Kalshi API key from the owner.
5. Lead: consolidate the scanner's GET-only client (`swinglock/scanner/client.py`) with Data's
   collector client once it lands.
6. Lead: README covering how to run each part.

## How to continue in a new session
Read `CLAUDE.md`, this file, and your brief in `docs/team/`. Check open PRs into `main` and the
`team/*` branches. The Lead's session ID and the role session IDs are in `docs/team/lead.md`.
