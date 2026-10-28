# Cash-out (take-profit) study: findings

**Status: PRELIMINARY.** Kalshi 1-minute candles, no order-book depth, each leg carried forward ≤ 1,800 s.
Pre-registered in `docs/edge_cashout.md` (2026-10-28, plus two dated amendments, all before any run).
Run by the Data role on 2026-10-28 from `main` e41c055 with `python -m swinglock.backtest.cashout`, on
both research groups. This report holds aggregates only, copied from the run summaries; every section
was transferred with its sha256 and checked.

## The answer (the owner's question)
- **Which exit level:** none beats holding. For a dog bought under 20¢, every exit level from 40¢ to
  90¢ ends within about ±1¢ per contract of simply holding. The dog bet itself loses whatever you
  choose: ROI −11% (ATP/WTA) and −22% (Challenger/WTA 125) at 0¢ slippage, −19% and −29% at 1¢.
  Choosing the level on past months (DOGL) failed in both groups.
- **What it costs:** for dogs, roughly nothing versus holding (Δ between −0.4¢ and +0.8¢ per contract).
  For an ordinary in-play position, every take-profit that fires costs about 2–5¢ per contract (the
  spread plus a second taker fee). A +10¢ target costs −2.0¢ to −2.5¢ per triggered contract at 0¢, and
  −3.1¢ to −3.7¢ at 1¢.
- **What risk it removes:** it narrows the spread of outcomes, but for dogs only by capping the upside.
  Selling a dog at 50¢ cuts SD from 0.32 to 0.23 per contract (ATP/WTA). **The worst decile does not
  change** (P10 = the whole stake, about −19¢): roughly 80% of dogs never reach 50¢ and still lose
  everything. Only for in-play positions near even money does a small target (3–10¢) also lift the worst
  decile (P10 about −0.61 → −0.41 to −0.53).

**Verdict: every gate FAILs** (E1, E2, DOG50, DOGL; both groups), as pre-registered. The losses come
from the entry (dogs are overpriced; buying at the ask pays the spread and fee), not from when you
cash out.

## Data
| | ATP/WTA (group 0) | Challenger/WTA 125 (group 1) |
|---|---|---|
| Matches | 4,695 | 8,349 |
| Aligned observations | 5,090,629 | 3,563,903 |
| Months | 2026-04 → 2026-10 | 2026-04 → 2026-10 |
| Identity check bid(A) = 1 − ask(B) | 10,181,258 rows, max gap 0 | 7,127,806 rows, max gap 0 |
| Exits on a stale bid (> 60 s unchanged) | 0–0.05% of triggers | 0–0.15% of triggers |

The identity holds by construction (see the pre-registration), so a take-profit at T is the same trade
as the swing lock at Y = 1 − T.

## 1. Dogs: the cost and risk of each exit level (owner's question)
Positions: E1 + E2 sides bought below 20¢ (E2, the first in-play price, is about 95% of them). Exit: the first
later row where the net bid (bid − slippage − taker fee) is at or above the level; otherwise held to
settlement. P&L, Δ and the CIs (95%, resampling whole matches) are in cents per contract. SD and P10
are per contract, in dollars.

**ATP/WTA (group 0), 0¢ slippage** (817 dog positions)

| Exit at net bid ≥ | Trigger rate | P&L ¢/contract (95% CI) | ROI | Δ vs hold ¢/contract (95% CI) | SD $/contract | P10 $/contract |
|---|---|---|---|---|---|---|
| 40c | 27% | -1.7 (-3.1 to -0.3) | -12.4% | +0.1 (-1.7 to +1.9) | 0.194 | -0.191 |
| 45c | 24% | -1.5 (-3.1 to +0.1) | -11.1% | +0.2 (-1.5 to +2.1) | 0.211 | -0.191 |
| 50c | 22% | -1.5 (-3.1 to +0.2) | -10.7% | +0.3 (-1.3 to +2.0) | 0.225 | -0.191 |
| 55c | 20% | -1.2 (-2.9 to +0.6) | -8.9% | +0.5 (-1.0 to +2.1) | 0.241 | -0.191 |
| 60c | 18% | -1.2 (-3.0 to +0.7) | -9.0% | +0.5 (-0.9 to +2.0) | 0.254 | -0.191 |
| 65c | 16% | -1.8 (-3.7 to +0.2) | -13.1% | 0.0 (-1.3 to +1.3) | 0.263 | -0.191 |
| 70c | 15% | -1.6 (-3.6 to +0.5) | -11.9% | +0.1 (-1.0 to +1.4) | 0.275 | -0.191 |
| 80c | 12% | -1.1 (-3.3 to +1.1) | -8.3% | +0.6 (-0.3 to +1.7) | 0.301 | -0.191 |
| 90c | 8% | -1.0 (-3.3 to +1.4) | -7.1% | +0.8 (+0.1 to +1.7) | 0.319 | -0.191 |
| hold (never sell) | 0% | -1.8 (-4.1 to +0.6) | -12.8% | 0 (baseline) | 0.318 | -0.191 |

**ATP/WTA (group 0), 1¢ slippage** (817 dog positions)

| Exit at net bid ≥ | Trigger rate | P&L ¢/contract (95% CI) | ROI | Δ vs hold ¢/contract (95% CI) | SD $/contract | P10 $/contract |
|---|---|---|---|---|---|---|
| 40c | 26% | -2.8 (-4.3 to -1.4) | -19.3% | 0.0 (-1.8 to +1.8) | 0.195 | -0.201 |
| 45c | 23% | -2.9 (-4.4 to -1.4) | -19.8% | -0.1 (-1.8 to +1.7) | 0.209 | -0.201 |
| 50c | 21% | -2.8 (-4.3 to -1.1) | -18.8% | +0.0 (-1.5 to +1.7) | 0.224 | -0.201 |
| 55c | 19% | -2.7 (-4.4 to -1.0) | -18.6% | +0.1 (-1.4 to +1.6) | 0.237 | -0.201 |
| 60c | 18% | -2.7 (-4.4 to -0.9) | -18.4% | +0.1 (-1.3 to +1.5) | 0.251 | -0.201 |
| 65c | 16% | -3.0 (-4.8 to -1.0) | -20.2% | -0.2 (-1.4 to +1.2) | 0.262 | -0.201 |
| 70c | 15% | -2.8 (-4.8 to -0.7) | -19.0% | +0.0 (-1.1 to +1.3) | 0.274 | -0.201 |
| 80c | 12% | -2.4 (-4.5 to -0.1) | -16.2% | +0.4 (-0.5 to +1.5) | 0.298 | -0.201 |
| 90c | 7% | -2.2 (-4.4 to +0.2) | -14.8% | +0.6 (-0.1 to +1.5) | 0.317 | -0.201 |
| hold (never sell) | 0% | -2.8 (-5.2 to -0.5) | -19.1% | 0 (baseline) | 0.318 | -0.201 |

**Challenger/WTA 125 (group 1), 0¢ slippage** (1597 dog positions)

| Exit at net bid ≥ | Trigger rate | P&L ¢/contract (95% CI) | ROI | Δ vs hold ¢/contract (95% CI) | SD $/contract | P10 $/contract |
|---|---|---|---|---|---|---|
| 40c | 22% | -3.0 (-4.0 to -2.2) | -23.5% | -0.1 (-1.4 to +1.1) | 0.175 | -0.191 |
| 45c | 20% | -2.9 (-3.9 to -2.0) | -22.7% | 0.0 (-1.2 to +1.1) | 0.187 | -0.191 |
| 50c | 19% | -2.8 (-3.9 to -1.8) | -21.7% | +0.1 (-1.1 to +1.2) | 0.203 | -0.191 |
| 55c | 16% | -2.7 (-3.9 to -1.6) | -21.1% | +0.2 (-0.9 to +1.3) | 0.219 | -0.191 |
| 60c | 15% | -2.8 (-4.0 to -1.6) | -21.4% | +0.1 (-0.8 to +1.1) | 0.231 | -0.191 |
| 65c | 14% | -2.5 (-3.8 to -1.3) | -19.6% | +0.4 (-0.5 to +1.3) | 0.245 | -0.191 |
| 70c | 13% | -2.6 (-4.0 to -1.3) | -20.4% | +0.2 (-0.5 to +1.1) | 0.254 | -0.191 |
| 80c | 10% | -2.7 (-4.2 to -1.3) | -21.3% | +0.1 (-0.4 to +0.8) | 0.272 | -0.191 |
| 90c | 7% | -2.9 (-4.4 to -1.4) | -22.4% | 0.0 (-0.3 to +0.4) | 0.284 | -0.191 |
| hold (never sell) | 0% | -2.9 (-4.4 to -1.3) | -22.3% | 0 (baseline) | 0.293 | -0.191 |

**Challenger/WTA 125 (group 1), 1¢ slippage** (1597 dog positions)

| Exit at net bid ≥ | Trigger rate | P&L ¢/contract (95% CI) | ROI | Δ vs hold ¢/contract (95% CI) | SD $/contract | P10 $/contract |
|---|---|---|---|---|---|---|
| 40c | 22% | -4.3 (-5.2 to -3.5) | -30.7% | -0.4 (-1.6 to +0.9) | 0.174 | -0.201 |
| 45c | 20% | -4.2 (-5.2 to -3.2) | -29.9% | -0.2 (-1.4 to +0.9) | 0.187 | -0.201 |
| 50c | 18% | -4.0 (-5.1 to -3.0) | -28.7% | -0.1 (-1.2 to +1.1) | 0.202 | -0.201 |
| 55c | 16% | -3.9 (-5.0 to -2.8) | -28.0% | +0.0 (-1.0 to +1.1) | 0.219 | -0.201 |
| 60c | 15% | -3.9 (-5.1 to -2.7) | -27.9% | +0.0 (-0.9 to +1.0) | 0.230 | -0.201 |
| 65c | 14% | -3.7 (-5.0 to -2.4) | -26.5% | +0.2 (-0.6 to +1.1) | 0.244 | -0.201 |
| 70c | 13% | -3.8 (-5.2 to -2.5) | -27.3% | +0.1 (-0.6 to +0.9) | 0.252 | -0.201 |
| 80c | 10% | -3.9 (-5.3 to -2.4) | -27.7% | +0.1 (-0.5 to +0.7) | 0.271 | -0.201 |
| 90c | 7% | -4.0 (-5.5 to -2.5) | -28.8% | -0.1 (-0.4 to +0.3) | 0.284 | -0.201 |
| hold (never sell) | 0% | -3.9 (-5.5 to -2.4) | -28.2% | 0 (baseline) | 0.293 | -0.201 |

How to read the tables:
- **Every row loses.** The ROI spread across levels (−7% to −13% for ATP/WTA, −20% to −24% for
  Challenger at 0¢) is inside the CIs, so the exit level doesn't matter much; the entry does.
- **Δ vs hold ≈ 0 at every level**, as the martingale expectation predicts. One cell (ATP/WTA, L = 90¢,
  0¢: +0.8¢, CI +0.1 to +1.7) clears zero. It is 1 of 36 level × slippage × group cells, it does not
  hold at 1¢ (CI −0.1 to +1.5) or in Challenger (0.0¢), and when DOGL picked 90¢ out of sample it lost
  in 4 of 5 months. **Not an edge.**
- **Risk:** a lower level lowers SD (0.32 → 0.19 at 40¢, ATP/WTA) because it gives up the full $1 payout
  on the dogs that go on to win. P10 is identical at every level: the bad tail is the dogs that never
  reach the level.
- **The owner's hypothesis** ("cash out at 50-50 or better because comebacks are overpriced") would show
  as a positive Δ at L ≈ 0.5–0.6. Measured: +0.3¢ to +0.5¢ (ATP/WTA) and +0.1¢ to +0.2¢ (Challenger) at 0¢, all CIs
  across zero, and about 0¢ at 1¢. **Not supported.**
- **Dogs below 30¢** (descriptive): the same shape, and selling is slightly *worse* than holding.
  - ATP/WTA: hold ROI −8.2% / −12.6% (0¢ / 1¢) vs sell at 50¢ −11.1% / −17.1%; Δ −0.6¢ (CI −2.0 to +0.8)
    and −1.0¢ (CI −2.3 to +0.4).
  - Challenger: hold −15.1% / −19.3% vs sell at 50¢ −16.5% / −21.9%.

## 2. DOG50 (fixed rule: dog < 20¢, sell at net bid ≥ 50¢, else hold): FAIL
| | ATP/WTA | Challenger/WTA 125 |
|---|---|---|
| Positions / triggers (0¢) | 817 / 177 (21.7%) | 1,597 / 296 (18.5%) |
| Total P&L, 0¢ / 1¢ | −$119.80 / −$226.07 | −$448.37 / −$641.46 |
| ROI, 0¢ (95% CI) | −10.7% (−22.5% to +1.5%) | −21.7% (−30.0% to −13.7%) |
| ROI, 1¢ (95% CI) | −18.8% (−29.6% to −7.7%) | −28.7% (−36.4% to −21.2%) |
| Δ vs hold, ¢/contract, 0¢ | +0.3 (−1.3 to +2.0) | +0.1 (−1.1 to +1.2) |
| Months positive at 1¢ (need 6 of 7) | 2 | 0 |
| ROI by band, 0¢: < 10¢ / 10–20¢ | −23.2% / −8.8% | −39.4% / −18.2% |

Pre-registered: negative ROI, trigger rate ≈ 2·p0 (≈ 20–35%), Δ small. All three held; the trigger rate
sits at the low end (18–22%), consistent with dogs being overpriced (they reach 50¢ less often than
their price implies).

## 3. DOGL (exit level chosen on earlier months, dogs < 20¢): FAIL
| | ATP/WTA | Challenger/WTA 125 |
|---|---|---|
| Folds positive at 1¢ (need 5 of 6) | 1 | 0 |
| OOS P&L, 0¢ / 1¢ | −$117.95 / −$214.45 | −$531.15 / −$700.81 |
| OOS ROI, 0¢ / 1¢ | −10.9% / −18.3% | −27.2% / −33.2% |
| OOS positions (triggers) | 797 (44) | 1,505 (171) |
| Levels chosen, May → Oct | hold, then 90¢ × 5 | 50¢, hold, 50¢, hold, 65¢, 65¢ |

The choice jumps around because no level is reliably better than another. In each case the training
P&L of the chosen level was itself mostly negative.

## 4. Take-profit on ordinary positions (selection-neutral entries)
E2 = buy **both** players at the first in-play price, so the entry favours neither side. Δ is per
triggered contract, in cents, with the 95% CI. SD and P10 are per contract for holding → with the rule.

| Rule | Group | Trigger rate 0¢ | Δ 0¢ | Δ 1¢ | SD hold → rule (0¢) | P10 hold → rule (0¢) |
|---|---|---|---|---|---|---|
| +3¢ | ATP/WTA | 78% | −2.4 (−2.9 to −1.9) | −3.4 (−4.0 to −2.9) | 0.450 → 0.221 | −0.617 → −0.417 |
| +3¢ | Challenger | 77% | −2.1 (−2.5 to −1.7) | −3.2 (−3.7 to −2.8) | 0.443 → 0.219 | −0.607 → −0.412 |
| +10¢ | ATP/WTA | 65% | −2.5 (−3.3 to −1.8) | −3.7 (−4.5 to −2.9) | 0.450 → 0.280 | −0.617 → −0.528 |
| +10¢ | Challenger | 64% | −2.0 (−2.6 to −1.5) | −3.1 (−3.7 to −2.5) | 0.443 → 0.277 | −0.607 → −0.508 |
| +30¢ | ATP/WTA | 34% | −2.2 (−3.4 to −0.9) | −3.1 (−4.3 to −1.8) | 0.450 → 0.387 | −0.617 → −0.617 |
| +30¢ | Challenger | 34% | −2.0 (−3.0 to −1.1) | −3.1 (−4.0 to −2.1) | 0.443 → 0.383 | −0.607 → −0.607 |
| sell at 50¢ | ATP/WTA | 26% | −3.4 (−5.4 to −1.5) | −5.0 (−7.0 to −3.0) | 0.450 → 0.369 | −0.617 → −0.617 |
| sell at 50¢ | Challenger | 25% | −2.1 (−3.6 to −0.6) | −3.0 (−4.6 to −1.4) | 0.443 → 0.365 | −0.607 → −0.607 |
| 2× entry | ATP/WTA | 18% | −1.7 (−3.6 to +0.2) | −2.4 (−4.5 to −0.5) | 0.450 → 0.412 | −0.617 → −0.617 |
| 2× entry | Challenger | 17% | −1.2 (−2.6 to +0.3) | −2.6 (−4.1 to −1.1) | 0.443 → 0.408 | −0.607 → −0.607 |

Pre-registered: E[Δ | trigger] ≈ −(half-spread + fee) ≈ −1¢ to −3¢ per contract, with lower variance.
Measured: about −1¢ to −3.5¢ at 0¢ and −2.5¢ to −5¢ at 1¢. That's at or just beyond the costly end of
the range, with large variance reductions for small targets. No rule has a positive Δ with a CI clear of zero, in either group.

**Walk-forward gate (rule chosen on earlier months, Δ as P&L, triggers as trades): FAIL in all four.**

| Entry, group | Folds positive at 1¢ (need 5 of 6) | OOS Δ total, 0¢ / 1¢ | OOS triggers, 0¢ / 1¢ |
|---|---|---|---|
| E1, ATP/WTA | 3 | −$129.50 / −$169.50 | 1,290 / 778 |
| E2, ATP/WTA | 3 | −$220.68 / −$226.34 | 1,396 / 1,216 |
| E1, Challenger | 1 | −$305.38 / −$365.28 | 1,616 / 1,518 |
| E2, Challenger | 3 | −$63.72 / −$292.00 | 2,082 / 1,756 |

**E1 (first pre-match price) is mostly an artefact:** 87% (ATP/WTA) and 82% (Challenger) of E1 entries
were bought at ≥ 80¢. The first pre-match observation is usually the market listing, when the book is
nearly empty and both asks sit near 99¢. Read E1 as a check on that artefact; E2 is the meaningful entry.

## 5. Set end vs mid-set (descriptive, ATP/WTA only, 1¢)
A live exit counts as "set end" if it falls within ±3 min of a Kalshi set-winner close time. Kalshi has
no set markets for Challenger/WTA 125, so that group is all "no set data". E2, Δ per triggered contract:

| Rule | Mid-set | Set end | No set data |
|---|---|---|---|
| +10¢ | −3.7¢ (n = 5,081; CI −4.5 to −2.8) | −3.1¢ (n = 334; CI −7.0 to +0.7) | −6.0¢ (n = 215) |
| +30¢ | −2.9¢ (n = 2,350; CI −4.3 to −1.5) | −3.5¢ (n = 432; CI −7.1 to +0.1) | −4.6¢ (n = 110) |
| sell at 50¢ | −5.0¢ (n = 2,014; CI −7.0 to −2.8) | −4.2¢ (n = 112; CI −12.9 to +5.3) | −6.3¢ (n = 73) |

There's no evidence that cashing out at a set end is better or worse than mid-set; the set-end samples
are small and their CIs wide.

## 6. Caveats
- **Candles, not order books.** These are 1-minute closes with no depth: fills assume the sampled bid or
  ask in full size, and moves inside a minute are missed. Fewer than 0.2% of triggers sold on a bid
  unchanged for > 60 s, so stale-quote exits are not driving the results.
- **Taker only.** Every fill pays the spread and the taker fee. Resting (maker) orders were not tested.
- **E1** is dominated by opening-book prices (see §4).
- **Dog samples are modest:** 817 ATP/WTA dog positions over 7 months. Every CI is shown.
- **Fee constants** (0.07) still await the owner's confirmation at kalshi.com/fee-schedule.
- Kalshi data is for the owner's private research; this report holds aggregates only.

## Bottom line for the owner
Cashing out a dog at 50-50 (or any level from 40¢ to 90¢) neither makes nor saves money compared with
holding it. It lowers the swings by giving up the big wins, but the typical bad outcome, a dog that
never comes back, is unchanged. The dog bet itself loses 11–29% depending on the tour and the fill.
On ordinary positions, each take-profit costs about 2–5¢ per contract in spread and fee in exchange for
a much smoother P&L. If smoother P&L is worth that to you, a small target (+3¢ to +10¢) buys the most
variance reduction per cent paid. It does not add expected profit.
