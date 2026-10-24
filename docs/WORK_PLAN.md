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

## Live configuration
- Scanner thresholds: placeholders in `config.yaml` (`min_arb_profit_per_contract` 0.5¢,
  `min_lock_profit` $0.05). None backed by a backtest yet.
- Slippage: 0¢ default; backtests also report 1¢.

## Open items (being watched)
- **Where the live scanner and order-book recorder run.** Cloud sessions are reclaimed when
  idle, so a 24/7 process needs the owner's machine or a small server. Owner to decide.
- **DraftKings:** manual price logging, or drop it? Owner to decide.
- **Polymarket venue for the cross-venue check:** Polymarket US (tradeable for a US user) vs intl
  (data only). Recommendation: Polymarket US.
- Historical depth: Kalshi candles have no depth and sample at 1 minute. Order-book history only
  starts when the recorder runs, so record early.

## Next steps (in order)
1. Data: Kalshi client + normalizer + backfill → `data-store`.
2. Backtest: arb scan + swing grid on the backfill; then walk-forward gate; then findings report.
3. Scanner: discovery + scan loop + alerts + positions + `state.json`.
4. Dashboard: page from a sample `state.json`, then wired to the scanner.
5. Data: order-book recorder; live score/state join; Polymarket collectors.
6. Lead: README covering how to run each part.

## How to continue in a new session
Read `CLAUDE.md`, this file, and your brief in `docs/team/`. Check open PRs into `main` and the
`team/*` branches. The Lead's session ID and the role session IDs are in `docs/team/lead.md`.
