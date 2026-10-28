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

**Expected result, pre-registered so the test can fail.** None of these rules passed the gate. Out of
sample, the backtest lost about 3–4¢ per contract at 0¢ slippage and 4–5¢ at 1¢:
- ATP/WTA: −$0.32 / −$0.47 per 10-contract trade.
- Challenger + WTA 125: −$0.39 / −$0.53 per 10-contract trade.

At 100 contracts that is **roughly −$3 to −$5 per trade**, before the depth-gate effect (below).
**Compare per contract**, not per trade. A rule clearly above zero over **≥ 30 settled trades** would be
the surprise worth reporting; a few weeks of losses would just confirm the backtest.

Backtest (2026-10-27) checked these rules against its swing sim. The semantics match, and `backtest_cfg`
sets every filter the sim reads. It suggested an optional swap of P4 for X 0.30 / Y 0.94 in the first
hour of play (0–60 min), a walk-forward-tested variant. Pre-match-only P4 was kept as the contrast to
P3; the Lead can make that swap before results exist.

**Rules are frozen.** Adding or changing one needs a new dated entry in this section, written before
its results exist. Never re-tune on paper results. The definitions live in one place,
`swinglock/scanner/paper.py` (`RULES`); `tests/test_scanner_paper.py` fails if this table and the
code disagree.

### Cash-out group (owner request 2026-10-28)
**Pre-registered 2026-10-28, before any cash-out backtest result existed** (Backtest's study,
`swinglock/backtest/cashout.py` + docs/edge_cashout.md, had not run on data yet). The owner asked to
track cash-outs as a live paper portfolio. P1–P4 above stay frozen and unchanged.

| Rule | Entry: ask < | Exit: sell all at the bid when net bid ≥ | Role |
|---|---|---|---|
| `C0-dog20-hold` | 0.20 | hold | Control: C1's entries, never sold, held to settlement |
| `C1-dog20-sell50` | 0.20 | 0.50 | The owner's DOG50 |
| `C2-dog30-sell50` | 0.30 | 0.50 | DOG50 with a wider entry band |
| `C3-dog20-sell60` | 0.20 | 0.60 | Cash out once the dog is past 50-50 (owner, same day) |
| `C4-dog20-sell70` | 0.20 | 0.70 | Cash out once the dog is clearly winning (owner, same day) |

C3 and C4 were added the same day at the owner's request ("at 50-50 or even winning"), also before
any result existed. Semantics are exactly `cashout.py`'s (`_positions`; level rule L, `DOG_RULE` for C1):
- **Entries E1 and E2.** At a match's **first observation before the scheduled start (E1)** and its
  **first observation after it (E2)**, each player whose ask is below the rule's limit is bought. Both
  asks must be present. Size is min(100, size at the ask), filled at the ask + slippage with the taker
  fee. A match can give one E1 and one E2 trade per rule. This follows cashout.py ("E1/E2: both players
  at the first pre / live observation"). It is **not** "the first moment any side drops under 20¢":
  this way the forward test measures exactly what the study gates, and the parity test can compare
  the two engines directly.
- **Exit (C1, C2):** at the first later observation where
  `net bid = (bid − slippage) − fee(bid − slippage, n) / n ≥ 0.50` and the bid size covers all n
  contracts, the position is sold whole at the bid (the sell fee is rounded up per order). It only
  applies while the entry all-in is under 50¢, which is always true here.
- **Otherwise held to settlement:** 1/0, or the fair price for a match that never started.
- **The measured quantity is Δ = rule − C0 per contract, on the same entries,** for C1, C3 and C4. C2 is
  compared with C0's matching entries below 20¢, plus its own P&L. The spread of outcomes is reported too.
- The lookback calls `cashout.simulate_cashout` with each rule's level, or the hold rule for C0. Every
  level here (50, 60 and 70¢) is on cashout's dog exit-level curve (`DOG_LEVELS`, phat-d0/Tennis_Model#130),
  and a test checks the live engine equals it for all five rules.

**Expected result, pre-registered so the test can fail.** Under a martingale, a dog bought at p0
reaches 50¢ with probability ≈ 2·p0, so the take-profit is break-even before costs. Costs make it
negative:
- a spread and a taker fee on both the buy and the sale;
- the dog overpricing already measured (Kalshi early-round dogs lost 15.7%).

So C1 and C2 should be negative, and **Δ (C1 vs C0) should be about −1 to −3¢ per contract**. C3 and
C4 trigger less often, on fewer and later rallies. Their Δ should also be negative and of similar size per
contract, with fewer exits and a wider spread. A clearly
positive Δ over ≥ 30 settled C1 trades would be the surprise worth reporting. Changing anything here
needs a new dated entry, written before the results exist.

**Start-up entries.** The C rules have their own start-up moment: the first poll after the deploy
that adds them. It is recorded as that rule's `since` (in `paper.rules`). Their start-up entries
(entry_ts == the rule's `since`) are reported apart, under the same reading rule as P1–P4.

## How it runs
**Live forward test:** `swinglock/scanner/paper.py`, called by the scanner loop every poll.
- At each poll, each rule either opens a trade on a match (once per rule and match, ever) or checks
  its open trade for a lock.
- An observation needs both sides to have an ask, like the backtest's aligned rows.
- When a match leaves the open list, its trades are settled from `GET /markets` (one request per 50
  matches, at most once per discovery cycle of 5 min).
- **Ledger:** `data/paper/ledger.jsonl`, append-only. Each line is one event (`open`, `lock`, `exit` or
  `settle`) with the full trade snapshot. On restart the scanner replays it, so it never re-enters.
  `exit` (cash-out rules, sold at the bid) is final; exited trades aren't settled again.
- `data/paper/paper_state.json` holds each rule's `since` and the matches whose E1/E2 observation has
  passed, so a restart never takes an E1 or E2 again. P1–P4 trades that predate the file keep the
  book's first poll as their `since`.
- **Independent of `positions.json`.**

**Nightly lookback:** `python -m swinglock.scanner.lookback`, run by a systemd timer at about 04:00 UTC.
- Runs the **same `RULES`** through the **backtest's simulator** (`swing.simulate`, via
  `PaperRule.backtest_cfg`) over the recorder's order books (`data/recorded/kalshi/quotes`, 10 s
  snapshots with real best-level size), at 0¢ and 1¢ slippage.
- Runs the **same `CASH_RULES`** through `cashout.cash_paths` + `simulate_cashout` (rule `L=50c`; the
  control takes the same rows' hold P&L). Matches are tracked as processed per group
  (`processed`, `processed_cashout` in `lookback_state.json`). So the first run after the deploy also
  simulates the C rules on matches the swing lookback had already done.
- It's incremental: each night it adds only the matches settled since the last run, and reads only
  the day files around them. Per-match trades are kept in `data/paper/lookback_trades.parquet`, and
  the aggregates go to `data/paper/lookback.json`.
- Results come from the shared `data/paper/settlements.json`, or `GET /markets` (one request per 50
  matches; only for matches whose start was over 6 h ago).
- Everything stays on the server. Nothing goes into git.

**The two runs see different data.** Live sees scanner polls (about 6 s apart at 100 matches); the
lookback sees recorder snapshots (10 s), so their trade lists won't match one for one. The decision
code is shared, and `test_live_engine_matches_backtest_swing_sim` (swing) and
`test_live_cash_engine_matches_backtest_cashout_sim` (cash-out) show that on the same observations
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
               "lock_rate": null, "pnl_settled": 0.0, "pnl_locked_unsettled": 0.0, "contracts": 0.0, "capital": 0.0}],
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
- `contracts` (in `by_rule`, here and in lookback.json) is the total entered, before lock buys. P&L per
  contract = `pnl` / `contracts`, which is the pre-registered comparison. Added 2026-10-27 at Dashboard's request.

**Cash-out additions (2026-10-28, additive; nothing renamed or removed):**
- Every `rules` entry has `group` (`"swing"` or `"cashout"`) and `since` (that rule's first poll; its
  start-up entries have entry_ts == since). Cash-out rules describe themselves as
  `{"id", "max_ask", "level" (null = hold), "contracts", "entries": ["E1", "E2"], "group", "since"}`.
- Every `by_rule` row (state.json and lookback.json) has `group`. For cash-out rows, `locked` counts
  **exits**, and `settled` counts trades with a final P&L (settled or exited). `pnl_settled` includes the
  exited trades' sale P&L; `pnl_locked_unsettled` is 0.
- Trades gain `group`, `entry_type` (`"E1"|"E2"`, null for swing), `exit_ts`, `exit_bid` and `exit_value`
  (cash after the sell fee). `status` gains `"exited"`, which is final: `pnl` = exit_value − entry_cost,
  and `pnl_if_a` = `pnl_if_b` = `pnl`.
- lookback.json gains `matches_processed_cashout`.

**`data/paper/lookback.json`** (the dashboard reads it next to state.json):
```json
{"generated_at": "", "source": "", "data_from": "", "data_to": "",
 "matches_recorded": 0, "matches_processed": 0, "matches_with_trades": 0,
 "matches_new_this_run": 0, "matches_awaiting_result": 0, "settlement_requests": 0,
 "rules": [ …same as state.json paper.rules… ],
 "by_rule": [{"rule": "", "slippage": 0.0, "trades": 0, "locked": 0, "lock_rate": null, "pnl": 0.0,
              "pnl_per_trade": null, "win_rate": null, "pnl_locked": 0.0, "pnl_unlocked": 0.0, "contracts": 0.0,
              "capital": 0.0}],
 "by_day": [{"day": "YYYY-MM-DD", "rule": "", "trades": 0, "locked": 0, "pnl": 0.0}]}
```
- `by_rule` has one row per rule per slippage (0.0 and 0.01).
- `by_day` is at 0¢ slippage, keyed by settlement day.

## Reading results honestly
- **Compare live and lookback on aggregates, not trade by trade.** The live engine sees one snapshot per
  scanner poll. The lookback sees the recorder's ~10 s books through align's as-of join (the union of
  A/B times, 60 s staleness). Different observation grids can give a different entry or lock moment.
  The equivalence test only proves the logic on a shared grid.
- **Depth gate.** A lock needs the top-of-book size at a single price level to cover the whole position,
  with no walking the book. At 100 contracts this blocks locks that the candle backtest took, because
  its depth was unknown and the gate always passed. Expect a **lower lock rate than the findings
  report** (48.8% for P1). The gate is conservative and identical in both engines.
- **Size vs research.** The research used 10 contracts. At 100 contracts the fee rounding per order costs
  slightly less per contract. When entry depth is small (1–5 contracts), the 1¢ minimum fee per order
  costs more per contract.
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
