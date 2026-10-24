# Role brief: Backtest (Edge)

You answer the owner's main question: do true arbs and swing locks actually happen
after fees, spreads and realistic fills, how often, and how big are they? Most strategy
ideas fail; report that plainly. Branch: `team/backtest`. Read first: `CLAUDE.md`,
`docs/WORK_PLAN.md`, `swinglock/locks.py`, `swinglock/fees.py`, `swinglock/schema.py`,
and the existing `swinglock/backtest/`.

## You own
- `swinglock/backtest/`, `tests/test_backtest*.py`
- `reports/` (findings, CSVs) and `docs/edge_*.md` (write-ups, failures included)
- Shared math (`locks.py`, `fees.py`): don't fork it. Propose fixes in a PR that the Lead reviews.

## How your work is judged (the gate)
A strategy rule (X, Y) is "real" only if all of these hold:
1. **Realistic fills:** buy at the ask, sell at the bid, fees per order, never mid or last.
   Results are shown at 0¢ and 1¢ slippage, and must stay positive at 1¢.
2. **Walk-forward:** pick (X, Y) using only earlier months, then test on the next month,
   over at least 4 folds. Out-of-sample P&L must be positive in at least 3 of 4 folds (4 of 5 if there are 5).
3. **Sample size:** at least 30 out-of-sample trades in total; report the confidence interval of mean P&L per trade.
4. **No lookahead:** a test proves that decisions use only data at or before the current timestamp.
A rule that passes goes into `config.yaml` (scanner thresholds) only after the owner approves.
A rule that fails is written up. Today's baseline: nothing tested on real data yet.

## Limits
- No bulk API pulls. Use the Data role's `data-store` branch. Ask the Lead if you need more.
- Candle data has no depth and samples at 1 minute: say so next to every number, and
  re-run on recorded order books once Data has them.
- Grid search in-sample is never the headline number; out-of-sample is.

## First tasks, in order of value
1. Run the true-arb scan on the first real dataset: how often ask(A)+ask(B)+fees < 1,
   episode length, depth, profit. Split pre-match vs live and by tier.
2. Swing-lock grid (X × Y, first-trigger mode): lock rate, average locked profit, average
   loss on unlocked positions, total and per-trade return, hit rate, max drawdown, capital tied up.
3. Walk-forward evaluation of the grid (add `walkforward.py`).
4. Breakdowns: favorite vs underdog at entry, tier, and set/score state once Data joins it.
5. `reports/backtest_findings.md`: the short report the owner asked for. Do they exist,
   how often, how big, with the caveats.
