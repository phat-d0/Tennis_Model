# Backtest findings: do tennis arbs and swing locks exist after fees?

**Status: PRELIMINARY.** Kalshi 1-minute candles, no order-book depth, each leg carried forward
≤ 1,800 s. Research set: **13,019 matches** over 6 months (group 0 = ATP/WTA 4,686; group 1 =
ATP Challenger + WTA 125 8,333). Run locally by the Data role with `python -m swinglock.backtest.run`;
this report holds aggregates only (Kalshi data stays private). ATP/WTA numbers are copied from
`docs/WORK_PLAN.md` "Findings so far" (2026-10-24); Challenger numbers are from Data's group-1 read
(2026-10-25), relayed by the Lead.

## The answer
**No.** On 6 months of Kalshi tennis match markets (13,019 matches: ATP/WTA and Challenger/WTA 125),
neither true arbs nor swing locks show an edge after fees and the ask spread. The walk-forward gate
fails on sign in every fold of both groups.
- **True arbs** (buy both players at once for under $1 after fees) show up 98 times in 40 matches,
  almost all for one candle. They're tiny ($2.49 in total on 1-contract fills), and the biggest ones
  look like stale or carried quotes, not offers you could actually fill. 98 is an upper bound; the
  stricter count (both legs' prices changed within 60 s) leaves 35 episodes worth $1.32 in total.
- **Swing locks** (buy one player cheap, lock later by buying the other) lose money under every
  entry/lock rule tested: about −$0.30 per 10-contract trade in sample. Chosen on past months and
  tested on the next, they lose in **all 6 of 6 months** (−$0.32/trade, 95% CI −$0.37 to −$0.28;
  −$0.47 at 1¢ slippage).
- Restricting entries to in-play only, or to the first hour of play, doesn't change that (still 0 of 6).
- **Challenger + WTA 125 (6 months, 8,333 matches)** looks the same or slightly worse: every swing rule
  negative, walk-forward **0 of 6** folds positive (−$0.39/trade OOS, CI −$0.42 to −$0.35; −$0.53 at
  1¢). Its biggest after-fee "arbs" are a data glitch (crossed historical candles on one day); cleaned
  arb counts are pending.
- The gate fails on the **sign** of the result, not just on sample size. The loss per contract,
  ~3–4¢, is roughly the ask spread plus the taker fee, which is what trading a fairly priced market
  costs.

## Data used (group 0: ATP/WTA; §1–4 use this set, §5 is group 1)
| Item | Value |
|---|---|
| Venue / series | Kalshi KXATPMATCH, KXWTAMATCH ("group 0") |
| Matches | 4,686 (market close 2026-04-24 → 2026-10-24) |
| Fair-price settlements (match never started) | 161, settled at Kalshi's fair price via `settle_a/settle_b` |
| Quote source | 1-minute candles (YES bid/ask close per market), each leg carried forward ≤ 1,800 s; **no depth** |
| Aligned observations | 5.09 M (as-of join, max staleness 60 s); 12% live (after scheduled start) |
| Fees | Kalshi taker 0.07 × C × P × (1−P), rounded up per order to $0.01; multiplier 1 |
| Fills | buy at the ask (+ slippage, 0¢ and 1¢), never mid or last |

## 1. True arb: ask(A) + ask(B) + fees < $1 at the same moment
| Metric | Value |
|---|---|
| Observations with combined ask < $1 **before** fees | 2.46% (99¢: 109,629; 98¢: 13,821; ≤ 95¢: 127) |
| After-fee arb episodes, 0¢ slippage | **98 in 40 matches** (upper bound, see below) |
| After-fee arb episodes, 1¢ slippage | 26 in 18 matches |
| Typical duration | median one candle (≤ 1 minute observed) |
| Sum of one-fill profits | $2.49 (1 contract each; depth unknown) |
| Largest | NAKBAE 21¢ (stale pre-match quote); PELMAN 13¢ (used a carried leg); CHOVAN 13¢ (zero volume) |

**Read:** a combined price of 99¢ is common, but after two taker fees (each ≥ 1¢, rounded up per
order) almost none clear $1. The few that do are single candles, mostly pre-match in thin books,
and the largest ones came from a stale or carried quote. **98 is an upper bound**: the 1,800 s
carry can pair a stale leg with a fresh one. Not reported yet: the split by pre-match vs live and by tier.

**Stricter count** (`backtest.arb_max_leg_age_s`: an observation counts only if both legs' asks
changed within N seconds):

| Setting | Episodes at 0¢ | 1-contract profit at 0¢ | Episodes at 1¢ |
|---|---|---|---|
| Off (default) | 98 in 40 matches | $2.49 | 26 in 18 matches |
| 300 s | 40 | n/r | 19 in 15 matches ($0.77) |
| 60 s | 35 in 26 matches | $1.32 | 19 in 15 matches ($0.77) |

All remaining episodes are single candles with unknown depth. The filter removes carried-leg cases
(PELMAN) but not wide stale offers that tick by 1¢ (NAKBAE 21¢, CHOVAN 13¢: zero volume, 3 days
pre-match). About $1 of one-contract profit in 6 months of ATP/WTA is not a tradeable edge.

## 2. Swing-lock grid (in sample: a hypothesis, not a result)
Rule: buy 10 contracts of the first side whose ask ≤ X; lock when entry all-in + other ask + fee ≤ Y;
otherwise hold to settlement. X ∈ {0.20 … 0.60}, Y ∈ {0.90 … 0.99}, mode "first".

| Metric | Best rule in sample (X = 0.20, Y = 0.90) |
|---|---|
| Trades | 4,509 |
| Lock rate | 48.8% |
| Total P&L at 0¢ / 1¢ | −$1,374 / −$2,023 |
| P&L per trade at 0¢ | −$0.30 |

**Every rule in the grid is negative.** From the earlier 2,000-match read (same method), locked
trades averaged +$1.11 and unlocked −$1.86. That split is selection (the trades that happened to
swing), not an edge. Entry diagnostics on that read: losses don't come from near-decided matches
(only 1–3% of entries are below 10¢). Entries at or above 10¢ lose at every X, and lose more as X
rises (−$0.33/trade at X = 0.20 → −$1.09 at X = 0.50).

## 3. Walk-forward gate (the headline)
Rule chosen each month on earlier months only (expanding window; best total P&L at 1¢ slippage
with ≥ 10 training trades; training trades must have settled before the test month), then run
unchanged on the next month.

**Verdict: FAIL, 0 of 6 folds positive (May–Oct 2026).**

| Variant | Folds positive | OOS trades | Mean P&L/trade 0¢ (95% CI) | Mean P&L/trade 1¢ (95% CI) |
|---|---|---|---|---|
| Default (all entries) | 0 / 6 | 4,432 | −$0.32 (−0.37 to −0.28) | −$0.47 (−0.52 to −0.43) |
| `entry_phase: live` (in-play only) | 0 / 6 | n/r | −$0.27 | −$0.43 |
| First hour of play (`min/max_minutes_from_start` 0–60) | 0 / 6 | 3,108 | −$0.27 | −$0.42 |

(n/r = not reported in the run summary.) CIs come from a bootstrap that resamples whole matches.

| Gate check | Required | Default variant |
|---|---|---|
| Folds | ≥ 4 | 6 ✔ |
| Positive folds at 1¢ | ≥ 5 of 6 (⌈0.75 × 6⌉) | 0 ✘ |
| Total OOS P&L > 0 at 0¢ and 1¢ | yes | no ✘ |
| OOS trades | ≥ 30 | 4,432 ✔ |
| No-lookahead test | passes | ✔ (`tests/test_backtest*.py`) |

## 4. Breakdowns
| Dimension | Finding |
|---|---|
| Phase | In-play-only entries: still 0/6 folds, −$0.27/trade OOS (0¢). The earlier 2,000-match read had live entries losing more in total than pre-match ones (−$455 vs −$150 at X = 0.20/Y = 0.92). |
| Entry price | < 10¢ entries are 1–3% and slightly positive; ≥ 10¢ entries lose at every X (2,000-match read). |
| Favorite vs underdog | not reported yet |
| Tier | Challenger + WTA 125 (§5) loses a little more per trade than ATP/WTA (OOS −$0.39 vs −$0.32 at 0¢); ATP vs WTA split not reported yet; ITF not run yet |
| Score state | needs the recorder's score history (no history before recording started) |

## 5. Challenger + WTA 125 (group 1, 6 months)
Same method on KXATPCHALLENGERMATCH + KXWTACHALLENGERMATCH: **8,333 matches** (ATP Challenger 6,667,
WTA 125: 1,666), market close 2026-04-24 → 2026-10-24; 150 fair-price settlements; 3.56 M aligned
observations (pre-match 2.44 M, live 1.12 M). PRELIMINARY: 1-minute candles, no depth, carry 1,800 s.
This replaces the interim 2-month read.

**True arb** (arb rows below are **pending cleanup**, see the note):

| Metric | Value |
|---|---|
| Combined ask < $1 before fees | 2.11% of observations (99¢: 63,507; 98¢: 9,329; 97¢: 1,702; 96¢: 185; ≤ 95¢: 166) |
| After-fee arb episodes, 0¢ | 112 in 59 matches, $4.30 total 1-contract profit, best 34¢ |
| After-fee arb episodes, 1¢ | 47 in 30 matches, $2.53 |
| Leg-age 60 s, 0¢ | 50 in 40 matches, $2.09 |

**Data glitch:** the top hits (SAKMUL 34¢, ZAKBOU 26¢, MONAND 25¢) come from **crossed historical
candles** (ask < bid). There are 84 such candles out of 13.8 M two-sided candles, in 5 markets, all on
2026-05-13 between 11:00 and 15:00 UTC; post-cutoff candles have none. They are not real offers. Data
is adding a normalizer guard, and these arb numbers will be replaced by the cleaned counts. Even
uncleaned, $4.30 over 6 months on 1-contract fills is not a tradeable edge.

**Swing lock** (default grid, mode "first"):

| Metric | Value |
|---|---|
| Best rule in sample | X = 0.20 / Y = 0.90: 8,156 trades, 46.8% locked, −$3,031 at 0¢, −$4,242 at 1¢ |
| Walk-forward (default) | **FAIL, 0 of 6 folds**; OOS 7,748 trades, mean −$0.39/trade (CI −0.42 to −0.35) at 0¢, −$0.53 (CI −0.57 to −0.50) at 1¢ |
| `entry_phase: live` | FAIL 0/6; OOS −$0.32 at 0¢ (CI −0.35 to −0.28), −$0.47 at 1¢ |
| First hour of play (window 0–60 min) | FAIL 0/6; OOS 5,355 trades, −$0.30 at 0¢ (CI −0.35 to −0.26), −$0.45 at 1¢ |

Same picture as ATP/WTA: the loss per trade is about the spread plus the taker fee, and no variant
gets a single positive fold.

## 6. Caveats (read next to every number)
- **Candles, not order books.** 1-minute closes of YES bid/ask per market, with no depth. Fills
  assume the sampled ask in full size (optimistic); moves inside a minute are missed (pessimistic
  for short-lived arbs and locks). The carried quote can lag the live book by up to 60 s.
- **Carry.** Each leg's last candle is carried forward up to 1,800 s. Candles are written on quote
  changes, so carrying is usually right (140/144 live checks matched), but it can pair a stale leg
  with a fresh one, which inflates the true-arb count.
- **Fills:** buy at ask + slippage, Kalshi taker fee rounded up per order; no queue position,
  latency, partial fills or market impact. Maker (resting-order) strategies were not tested.
- **Settlement time** is each match's last aligned quote (proxy for capital and drawdown timing).
- **Retirements:** a retirement after the first ball settles the retiring player's market to No;
  matches that never started are settled at Kalshi's fair price (161 ATP/WTA, 150 Challenger here).
- **Crossed candles:** 84 historical Challenger candles on 2026-05-13 have ask < bid. They inflate the
  group-1 arb counts until Data's normalizer guard lands. They probably matter little for the swing
  results (one afternoon in 6 months), but that is unverified until the cleaned re-run.
- **Fee constants** (0.07 / 0.0175) still await the owner's confirmation at kalshi.com/fee-schedule.
- **Scope:** ATP/WTA and Challenger/WTA 125, 6 months each (2026-04-24 → 10-24). Older months, ITF
  and real order-book depth are not covered yet.
- Kalshi data is for the owner's private research only; this report must not be published.

## Next steps
1. Cleaned group-1 arb counts once the crossed-candle guard is in (replaces the §5 arb rows).
2. Re-run on recorded order books (real depth, 10 s snapshots) once the VPS recorder has history.
3. ITF and older months as the backfill completes.
4. Score-state and favorite/underdog splits; a maker-order variant only if the owner wants it
   (it needs queue assumptions the data can't verify).
