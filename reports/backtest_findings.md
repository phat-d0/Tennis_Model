# Backtest findings: do tennis arbs and swing locks exist after fees?

**Status: skeleton. No real data has been run yet.** Every `TBD` below is filled from
`python -m swinglock.backtest.run --data data/processed/kalshi --out reports/` once the Data
role publishes the backfill on `data-store`. Only out-of-sample walk-forward numbers count as
results. In-sample grid numbers are hypotheses.

## Answer in one paragraph
TBD. Say plainly: do true arbs occur (how often, how big, how long), and does any swing-lock
rule (X, Y) pass the gate? If nothing passes, say that first.

## Data used
| Item | Value |
|---|---|
| Venue / series | TBD (e.g. Kalshi KXATPMATCH, KXWTAMATCH, ...) |
| Date range (UTC) | TBD |
| Matches (settled A/B) | TBD |
| Quote source | TBD: candle (1-min, no depth) / orderbook (recorded) |
| Aligned observations | TBD (as-of join, max staleness 60s) |
| Fees | Kalshi taker, round up per order to $0.01; per-series fee_type/multiplier |
| Run | commit TBD, `config.yaml` as of TBD |

## 1. True arb: ask(A) + ask(B) + fees < $1 at the same moment
Source: `arb_episodes.csv`, `arb_by_match.csv`.

| Metric | All | Pre-match | Live |
|---|---|---|---|
| Matches with ≥1 arb episode | TBD | TBD | TBD |
| % of observations in arb | TBD | TBD | TBD |
| Episodes | TBD | TBD | TBD |
| Median / p90 duration (s, lower bound) | TBD | TBD | TBD |
| Median best edge per contract after fees | TBD | TBD | TBD |
| Median matched depth (contracts) | TBD | TBD | TBD |
| Sum of one-fill profits ($) | TBD | TBD | TBD |
| … at 1¢ slippage | TBD | TBD | TBD |

By tier (ATP / WTA / Challenger / ITF): TBD.

Reading: with candle data, arbs shorter than a minute are invisible and depth is unknown, so
dollar profit is for 1 contract (the most fee-heavy case).

## 2. Swing-lock grid (in sample: a hypothesis, not a result)
Source: `grid_metrics.csv`, `grid_trades.csv`. Mode `first` (one entry per match on whichever
side triggers first) unless stated. X = entry ask ≤ X; Y = lock when all-in entry + lock ask + fee ≤ Y.

| Metric | Best (X, Y) in sample | Median over grid |
|---|---|---|
| Trades | TBD | TBD |
| Lock rate | TBD | TBD |
| Avg locked P&L ($) | TBD | TBD |
| Avg loss on unlocked positions ($) | TBD | TBD |
| Total P&L ($) / per trade | TBD | TBD |
| Return on capital per trade | TBD | TBD |
| Hit rate | TBD | TBD |
| Max drawdown ($) | TBD | TBD |
| Peak / average capital tied up ($) | TBD | TBD |

Heatmap or table of total P&L over X × Y: TBD (is the best cell isolated, i.e. likely noise,
or part of a smooth region?).

## 3. Walk-forward gate (the headline)
Source: `walkforward_gate.csv`, `walkforward_folds.csv`, `walkforward_trades.csv`.
Rule (mode, X, Y) chosen on earlier months only (expanding window, training trades must have
settled before the test month; objective: total P&L at 1¢ slippage; at least 10 training trades),
then run unchanged on the next month.

**Verdict: TBD (PASS / FAIL + failed checks)**

| Fold | Test month | Chosen (X, Y) | OOS trades | OOS P&L 0¢ | OOS P&L 1¢ | Lock rate |
|---|---|---|---|---|---|---|
| 1 | TBD | TBD | TBD | TBD | TBD | TBD |
| 2 | TBD | TBD | TBD | TBD | TBD | TBD |
| 3 | TBD | TBD | TBD | TBD | TBD | TBD |
| 4 | TBD | TBD | TBD | TBD | TBD | TBD |

| Gate check | Required | Actual |
|---|---|---|
| Folds | ≥ 4 | TBD |
| Positive folds at 1¢ | ≥ 3 of 4 (4 of 5) | TBD |
| Total OOS P&L at 0¢ / 1¢ | > 0 / > 0 | TBD / TBD |
| OOS trades | ≥ 30 | TBD |
| Mean P&L per trade, 95% CI (match bootstrap) | report | TBD [TBD, TBD] |
| No-lookahead test | passes | `tests/test_backtest*.py` (TBD: CI run link) |

Does the chosen rule stay stable across folds? TBD.

## 4. Breakdowns (out-of-sample trades of the walk-forward rule)
Source: `breakdowns.csv` (in sample) and `walkforward_trades.csv` (out of sample).

| Dimension | Value | Trades | Lock rate | P&L / trade | Hit rate |
|---|---|---|---|---|---|
| Phase at entry | pre | TBD | TBD | TBD | TBD |
| Phase at entry | live | TBD | TBD | TBD | TBD |
| Role at entry | favorite (ask > 0.5) | TBD | TBD | TBD | TBD |
| Role at entry | underdog | TBD | TBD | TBD | TBD |
| Tier | ATP / WTA / Challenger / ITF | TBD | TBD | TBD | TBD |
| Score state | (once Data joins live score) | TBD | TBD | TBD | TBD |

## 5. Caveats (read next to every number)
- **Candle data:** 1-minute sampled asks with no depth. Fills are assumed at the sampled ask in
  full size (optimistic); moves between samples are missed (pessimistic for short locks/arbs).
  Re-run on recorded order books when the recorder has enough history.
- **Fills:** buy at ask + slippage, Kalshi taker fee rounded up per order; no queue position,
  latency, partial fills or market impact.
- **Settlement time** is each match's last aligned quote (proxy for capital and drawdown timing).
- **Retirements / walkovers:** a not-started match settles at a "fair price" and a retirement
  settles the retiring player's market to No; check how many trades these affect.
- **Selection:** the in-sample grid is never the headline; walk-forward picks rules on past months only.
- **Fee constants** (0.07 / 0.0175) still await the owner's confirmation at kalshi.com/fee-schedule;
  rounding assumes a direct (cent-rounded) account.
- **Sample size:** few months means few folds; a FAIL for "not enough folds" says nothing either way.
- Kalshi data is for the owner's private research only; this report must not be published.

## Next steps
TBD (e.g. re-run on order-book data; add score-state breakdown; cross-venue check).
