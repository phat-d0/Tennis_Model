# Paper trading (forward test) and nightly lookback

Read-only. Paper positions are hypothetical: nothing is ever sent to Kalshi except the same public
GETs the scanner already makes, plus `GET /markets?tickers=` to learn results. No order code exists.

## Pre-registration

**Pre-registered 2026-10-27, before any live paper result existed.** These rules come from the
backtest's swing grid (`swinglock/backtest/grid.py`; X ∈ 0.20…0.60, Y ∈ 0.90…0.99, mode "first").
In that grid **every rule lost money** after fees, and the walk-forward failed 0 of 6 folds
(`reports/backtest_findings.md`). This forward test therefore checks a negative result on real order
books with real depth. It is not a bet that these rules make money.

| Rule | X (entry: ask ≤) | Y (lock: all-in ≤) | Entry phase | Why it's here |
|---|---|---|---|---|
| `P1-x20-y90` | 0.20 | 0.90 | any | The grid's best rule in sample (ATP/WTA and Challenger): −$0.30 per 10-contract trade, 48.8% locked |
| `P2-x40-y95` | 0.40 | 0.95 | any | A mid-band entry with an easier lock; diagnostics said losses grow with X, so this checks that on books |
| `P3-x30-y94-live` | 0.30 | 0.94 | live | In-play only: the walk-forward's `entry_phase: live` variant (−$0.27/trade OOS) |
| `P4-x30-y94-pre` | 0.30 | 0.94 | pre | The same X/Y before the start, to compare with P3 |

Common to all four:
- **Mode "first":** one entry per match, on whichever side first has ask ≤ X. If both sides qualify
  at the same moment, the cheaper one is taken.
- **No other entry filters:** `min_entry_ask` and the minutes-from-start window are off, as in the
  default grid. The lookahead-only `min_minutes_to_close` is always off.
- **Size:** 100 contracts, capped by the size resting at the ask at that moment.
- **Fills** at the ask with Kalshi taker fees (`round_up(0.07 × C × P × (1−P))` per order, per-series
  `fee_type`/multiplier) plus `execution.slippage` (0¢ live; the lookback also reports 1¢). Never
  mid or last.
- **Lock:** the first later observation where `entry all-in per contract + ask(other) + fee per
  contract ≤ Y` **and** the other side's resting size covers the whole position. The fill buys the
  other side to equal counts (`locks.lock_quote`), so locked P&L = contracts − total cost.
- **Unlocked positions** settle at the result: 1/0, or Kalshi's fair price (summing to $1) for a match
  that never started (`Holding.pnl_settled`).
- **Scope:** the scanner's series (ATP, WTA, ATP Challenger, WTA 125; ITF was dropped 2026-10-26).

**Rules are frozen.** Adding or changing one needs a new dated entry in this section, written before
its results exist. Never re-tune on paper results. The definitions live in one place,
`swinglock/scanner/paper.py` (`RULES`); `tests/test_scanner_paper.py` fails if this table and the
code disagree.

## How it runs
**Live forward test:** `swinglock/scanner/paper.py`, called by the scanner loop every poll.
- At each poll, each rule either opens a trade on a match (once per rule and match, ever) or checks
  its open trade for a lock.
- An observation needs both sides to have an ask, like the backtest's aligned rows.
- When a match leaves the open list, its trades are settled from `GET /markets` (one request per 50
  matches, at most once per discovery cycle of 5 min).
- **Ledger:** `data/paper/ledger.jsonl`, append-only. Each line is one event (`open`, `lock` or
  `settle`) with the full trade snapshot. On restart the scanner replays it, so it never re-enters.
- **Independent of `positions.json`.**

**Nightly lookback:** `python -m swinglock.scanner.lookback`, run by a systemd timer at about 04:00 UTC.
- Runs the **same `RULES`** through the **backtest's simulator** (`swing.simulate`, via
  `PaperRule.backtest_cfg`) over the recorder's order books (`data/recorded/kalshi/quotes`, 10 s
  snapshots with real best-level size), at 0¢ and 1¢ slippage.
- It's incremental: each night it adds only the matches settled since the last run, and reads only
  the day files around them. Per-match trades are kept in `data/paper/lookback_trades.parquet`, and
  the aggregates go to `data/paper/lookback.json`.
- Results come from the shared `data/paper/settlements.json`, or `GET /markets` (one request per 50
  matches; only for matches whose start was over 6 h ago).
- Everything stays on the server. Nothing goes into git.

**The two runs see different data.** Live sees scanner polls (about 6 s apart at 100 matches); the
lookback sees recorder snapshots (10 s), so their trade lists won't match one for one. The decision
code is shared, and `test_live_engine_matches_backtest_swing_sim` shows that on the same observations
both give identical trades. The recorder labels A as the player listed first in the event ticker,
and the scanner as the ticker that sorts first. That only renames sides; it can't change a rule's
result.

## Output shapes (proposed contract, Lead to approve)
**`state.json`** gets two new top-level keys; the other keys are unchanged:
- `min_arb_profit_per_contract` (number): the scanner's arb alert threshold, so the dashboard counts
  an arb as open by the same test as the alert. Requested by Dashboard.
- `paper`: absent when the scanner runs with `--no-paper`.
```json
"paper": {
  "since": "ISO-8601 UTC of the first paper entry, or null",
  "rules": [{"id": "P1-x20-y90", "x": 0.2, "y": 0.9, "entry_phase": "any", "min_entry_ask": null,
             "min_minutes_from_start": null, "max_minutes_from_start": null, "contracts": 100.0,
             "mode": "first"}],
  "by_rule": [{"rule": "P1-x20-y90", "trades": 0, "open": 0, "locked": 0, "settled": 0,
               "lock_rate": null, "pnl_settled": 0.0, "pnl_locked_unsettled": 0.0, "capital": 0.0}],
  "trades": [{"trade_id": "P1-x20-y90:KXATPMATCH-…", "rule": "P1-x20-y90", "match_id": "", "series": "",
              "tier": "", "player_a": "", "player_b": "", "side": "A|B", "status": "open|locked|settled",
              "entry_ts": "", "entry_phase": "pre|live|unknown", "entry_ask": 0.0, "entry_source": "yes:<ticker>",
              "contracts": 0.0, "entry_cost": 0.0, "lock_ts": null, "lock_ask": null, "lock_source": null,
              "lock_contracts": 0.0, "lock_cost": 0.0, "settle_ts": null, "settle_a": null, "settle_b": null,
              "pnl": null, "pnl_if_a": 0.0, "pnl_if_b": 0.0}]
}
```
- `trades` lists open and locked trades first (newest entry first), then settled ones (newest
  settlement first), 200 at most.
- `pnl` is null while open, the locked P&L once locked, and the final P&L once settled.
- `pnl_if_a` / `pnl_if_b` are the settlement P&L if A / B wins. `capital` is dollars spent (entry + lock).
- `lock_rate` counts locked trades (settled or not) over all trades.

**`data/paper/lookback.json`** (the dashboard reads it next to state.json):
```json
{"generated_at": "", "source": "", "data_from": "", "data_to": "",
 "matches_recorded": 0, "matches_processed": 0, "matches_with_trades": 0,
 "matches_new_this_run": 0, "matches_awaiting_result": 0, "settlement_requests": 0,
 "rules": [ …same as state.json paper.rules… ],
 "by_rule": [{"rule": "", "slippage": 0.0, "trades": 0, "locked": 0, "lock_rate": null, "pnl": 0.0,
              "pnl_per_trade": null, "win_rate": null, "pnl_locked": 0.0, "pnl_unlocked": 0.0, "capital": 0.0}],
 "by_day": [{"day": "YYYY-MM-DD", "rule": "", "trades": 0, "locked": 0, "pnl": 0.0}]}
```
- `by_rule` has one row per rule per slippage (0.0 and 0.01).
- `by_day` is at 0¢ slippage, keyed by settlement day.

## Reading results honestly
- **Start-up entries.** "First observation" means the first one the scanner sees. When paper trading
  starts, or after a long outage, every match already listed is entered at its current price, not at
  the moment it first crossed X. In the dry run (2026-10-27, 108 open matches), 168 trades opened in
  the first poll: P1 34, P2 81, P3 11, P4 42. Matches listed afterwards behave like the backtest.
- **Thin books.** Size is min(100, size at the ask), so a trade can be tiny when only a fraction of a
  contract is resting. In the dry run, 4 of 168 entries were under 0.5 contracts. This is the
  backtest's rule; the P&L tables weight trades by dollars, so tiny trades barely count.
- Paper fills assume the whole size fills at the displayed ask the moment it's seen. There's no queue,
  latency or market impact, so results are optimistic about fills.
- A few weeks of paper trades are a small sample. A rule "works" only if it passes the gate in
  CLAUDE.md, and changing alert thresholds needs the owner's go-ahead.
