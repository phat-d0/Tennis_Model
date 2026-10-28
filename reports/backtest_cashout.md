# Cash-out (take-profit) study: findings

**Status: PRELIMINARY.** Kalshi 1-minute candles, no order-book depth, each leg carried forward ≤ 1,800 s.
Pre-registered in `docs/edge_cashout.md` (2026-10-28, plus dated amendments 1–4, each before its run; amendment 5,
E1r, is post hoc and its verdicts are not counted).
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

- **Ranking mismatches** (the owner's "#20 vs #200 goes to 50-50 often"): about a third of the much
  worse-ranked players do reach 50¢, but their price implies a bit more (ATP/WTA 34.1% vs 38.4% at 1¢). The
  rule loses (ROI −16.0% in play at 1¢) and FAILs (§6).
- **Unranked players** (MISMATCH50-U): "unranked" does not mean "underdog". Half or more of these entries cost
  over 50¢, so the rule often buys the favourite. It reaches 50¢ far less often than priced and FAILs (§7).
- **Formed-book pre-match entry (E1r, post hoc):** fixing E1 changes no conclusion. Every take-profit still costs
  money and every gate still FAILs (§8).

**Verdict: every gate FAILs** (E1, E2, DOG50, DOGL, MISMATCH50, MISMATCH50-U; both groups), as pre-registered. **E1 is
invalid**: it buys listing-time placeholder offers (§4); E2 is the valid read. The losses come
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

In-play entries only (E2, the valid part; 775 of 817 and 1,503 of 1,597 positions): ROI −11.9% / −19.9%
(ATP/WTA, 0¢ / 1¢) and −21.2% / −28.5% (Challenger). The remaining E1 dogs are listing-book entries (§4).

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

**E1 is invalid: a listing-book artefact, superseded by E1r.** At a match's first pre-match observation the book is mostly
empty: the median ask_a + ask_b is **$1.84** (ATP/WTA) and **$1.88** (Challenger), so E1 buys placeholder
offers on both players. That's why 87% (ATP/WTA) and 82% (Challenger) of E1 entries cost ≥ 80¢. The E1 rows
measure the empty opening book, not cashing out. **E2 is the valid entry.** The formed-book version (E1r = the
first pre-match row with ask_a + ask_b ≤ $1.05, amendment 5) is in §8: it also FAILs (post hoc, not counted).
The registered verdicts above stand.

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

## 6. MISMATCH50: buy the much worse-ranked player, sell at 50-50 (amendment 3): FAIL
The owner's observation: ranking mismatches (e.g. #20 vs #200) "go to 50-50 pretty often". Rule: in matches where the
worse-ranked player's rank is ≥ 4× the better one's and the better player is ranked ≤ 100, buy the worse-ranked
player (E1 and E2), sell at net bid ≥ 50¢, otherwise hold. **Rank = a pre-match Elo rank, a proxy built from earlier
results, not the official ranking.** Data's run (main c018be0); both sections were sha256-checked.

**The direct test: they reach 50¢ less often than their price implies.** Implied = entry ask ÷ the bid needed to net
50¢ after the fee, which is generous because it uses the ask. Eligible = bought below 50¢ all-in (mostly E2).

| Group | Positions eligible | Reached 50¢, 0¢ / 1¢ | Price-implied, 0¢ / 1¢ |
|---|---|---|---|
| ATP/WTA, all | 1,051 | 34.8% / 34.1% | 39.2% / 38.4% |
| ATP/WTA, E2 (in play) | 936 | 34.2% / 33.3% | 38.0% / 37.3% |
| Challenger/WTA 125, all | 159 | 34.6% / 34.6% | 38.5% / 37.8% |
| Challenger/WTA 125, E2 | 123 | 35.0% / 35.0% | 35.6% / 34.9% |

By rank-ratio bucket (every worse-ranked player, any better rank; 0¢), the reach rate falls short of the price in
**every bucket of both groups**:

| Rank ratio | ATP/WTA reached vs implied | Challenger reached vs implied |
|---|---|---|
| < 2× | 64.7% vs 71.2% | 61.1% vs 68.2% |
| 2–4× | 52.3% vs 58.2% | 43.1% vs 49.1% |
| 4–8× | 39.6% vs 45.3% | 28.4% vs 35.7% |
| ≥ 8× | 27.8% vs 30.0% | 18.8% vs 23.4% (n = 48) |

So the owner is right that a third of these players get to 50-50, but the price already expects a bit more than
that. **There's no under-pricing to exploit.** The one near-tie, Challenger E2 at 1¢ (35.0% vs 34.9%), is 123 positions.

**P&L, read on E2 (in play; the valid entry):**

| | ATP/WTA (946 positions) | Challenger/WTA 125 (125 positions) |
|---|---|---|
| ROI, 0¢ (95% CI) | −9.8% (−17.8% to −2.6%) | −4.1% (−25.8% to +18.7%) |
| ROI, 1¢ (95% CI) | −16.0% (−23.5% to −9.2%) | −9.4% (−30.1% to +12.2%) |
| Δ vs hold, ¢/contract, 0¢ | −1.2 (−2.9 to +0.7) | −6.0 (−10.9 to −0.9) |
| Share bought under 20¢ (DOG50 overlap) | 50% | 59% |

**Gate (fixed rule, all entries, as registered): FAIL**, 0 of 7 months positive in both groups. ATP/WTA: −$6,288.37 /
−$6,522.58 at 0¢ / 1¢ on 1,916 positions. Challenger: −$651.65 / −$679.17 on 251 positions; few Challenger players
rank inside the Elo top 100. Those totals are dominated by **E1, which is invalid**: ROI −75.6% (ATP/WTA) and −69.0%
(Challenger) from buying listing-time placeholder offers (§4). At E1r (§8) the rule still FAILs.

## 7. MISMATCH50-U: buy an unranked player vs a player ranked ≤ 100 (amendment 4): FAIL
Same rule as §6, but the bought player has no pre-match Elo rank (assumed to sit below the whole active pool).
Data's single run on main ad76187 (#148), rank file sha256 98753d11…; both sections sha256-checked
(ATP/WTA a8e2d519…, Challenger a5c33a87…).

**Unranked is not the same as underdog.** The entry-price distribution shows many of these players are priced
as favourites, so the rule often buys the favourite rather than a long shot:

| Group, reason | Entries | Median entry ask | Under 20¢ | Over 50¢ |
|---|---|---|---|---|
| ATP/WTA, too few rated matches | 14 | 66¢ | 43% | 50% |
| ATP/WTA, name not matched | 59 | 62¢ | 12% | 61% |
| Challenger, too few rated matches | 12 | 14¢ | 67% | 25% |
| Challenger, name not matched | 16 | 60¢ | 19% | 63% |
| any group, inactive (no match in 365 days) | 0 | not observed (by construction: the rank export never writes it) | | |

"Name not matched" is mostly a name-matching gap, not a weak player: those players are often ranked and favoured.

**Reach and P&L on E2 (in play):**

| | ATP/WTA (36 positions) | Challenger/WTA 125 (14 positions) |
|---|---|---|
| Reached 50¢ vs price-implied, 0¢ | 29.6% vs 47.3% (27 eligible) | 8.3% vs 29.2% (12 eligible) |
| ROI, 0¢ (95% CI) | −19.9% (−47.7% to +6.2%) | −47.2% (−100% to +2.7%) |
| ROI, 1¢ (95% CI) | −22.1% (−49.3% to +3.5%) | −49.9% (−100% to −1.9%) |
| Δ vs hold, ¢/contract, 0¢ | −2.4 (−10.5 to +6.0) | −3.5 (−10.5 to 0) |

**Gate (fixed rule, all entries, as registered): FAIL.** ATP/WTA: 0 of 6 months positive, −$244.02 / −$250.93 at
0¢ / 1¢ on 73 positions, only 8 sales at 50¢ (the gate needs ≥ 30). Challenger: 0 of 5 months, −$100.32 / −$103.29
on 28 positions, 1 sale. By reason (all entries, 0¢): too few rated matches lost the whole stake in both groups
(ROI −100% ATP/WTA, −93% Challenger; 0 sales); name not matched −44% / −64%. The samples are small; the
direction is the same everywhere.

## 8. E1r robustness check (amendment 5): post hoc, not counted
E1r = the first pre-match row with a formed book (ask_a + ask_b ≤ $1.05). It replaces E1's listing-time
placeholder offers. **E1r was defined after the E1 results were seen, so its gate verdicts are reported but not
counted; the registered verdicts above stand.** A formed pre-match book exists for 4,609 of 4,677 ATP/WTA matches
(98.5%) and 8,261 of 8,304 Challenger matches (99.5%). Same run as §7; sections sha256-checked (ATP/WTA c3c3d2cb…,
Challenger 0e5714bd…).

| Rule at E1r (post hoc, not counted) | ATP/WTA: positive at 1¢ | P&L 0¢ / 1¢ | Challenger: positive at 1¢ | P&L 0¢ / 1¢ |
|---|---|---|---|---|
| Take-profit walk-forward | 2 of 6 folds (need 5) | −$654.72 / −$800.92 | 1 of 6 folds | −$290.14 / −$524.22 |
| DOG50 (dog < 20¢, sell at 50¢) | 2 of 7 months (need 6) | −$81.24 / −$148.34 | 0 of 7 months | −$531.06 / −$676.86 |
| MISMATCH50 | 0 of 7 months | −$622.42 / −$757.62 | 2 of 7 months | −$32.06 / −$47.03 |
| MISMATCH50-U | 1 of 6 months (need 5) | −$29.30 / −$38.91 | 1 of 5 months (need 4) | −$15.41 / −$16.96 |

All **FAIL (post hoc, not counted)**.

- **Take-profit at E1r** (9,218 ATP/WTA and 16,522 Challenger positions): every rule has a negative Δ per
  triggered contract. At 0¢ that's −2.0¢ to −5.9¢ (ATP/WTA) and −0.2¢ to −2.9¢ (Challenger); at 1¢ −1.1¢ to
  −6.7¢ and −1.7¢ to −3.8¢. Every CI excludes zero except "sell at 3× entry" (few triggers). That's the same
  cost of 2–5¢ per sale as E2 (§4). Small targets again cut SD the most (+3¢: 0.45 → 0.22) and lift P10
  (−0.63 → −0.45).
- **DOG50 at E1r:** ROI −10.0% / −17.2% (ATP/WTA, 532 positions) and −30.3% / −36.0% (Challenger, 1,240) at
  0¢ / 1¢. Δ vs hold is −0.8¢ (CI −2.8 to +1.2) and +0.0¢ (−1.1 to +1.2): cashing out at 50¢ is again about the
  same as holding.
- **MISMATCH50 at E1r:** the worse-ranked player reaches 50¢ 33.4% of the time vs 44.6% implied (ATP/WTA, 939
  eligible) and 34.1% vs 40.3% (Challenger, 126) at 0¢. ROI at 1¢: −29.5% (966 positions) and −16.1% (126).
- **MISMATCH50-U at E1r:** reach 34.5% vs 55.2% (ATP/WTA, 29 eligible) and 8.3% vs 30.5% (Challenger, 12);
  ROI at 1¢ −28.7% (37 positions) and −51.0% (14).

The fixed entry changes the sizes of the E1 losses, not their sign. No conclusion changes.

## 9. Caveats
- **Candles, not order books.** These are 1-minute closes with no depth: fills assume the sampled bid or
  ask in full size, and moves inside a minute are missed. Fewer than 0.2% of triggers sold on a bid
  unchanged for > 60 s, so stale-quote exits are not driving the results.
- **Taker only.** Every fill pays the spread and the taker fee. Resting (maker) orders were not tested.
- **E1 is invalid:** it buys listing-time placeholder offers (median combined ask $1.84 / $1.88); see §4.
  Read E2. Superseded by E1r (formed book; post hoc, verdicts not counted), which also FAILs (§8).
- **Dog samples are modest:** 817 ATP/WTA dog positions over 7 months. Every CI is shown.
- **Rank** in §6–§7 is a pre-match Elo rank (a proxy), not the official ATP/WTA ranking. "Unranked" (§7)
  mixes genuinely new players with name-matching gaps, and its samples are small (73 and 28 positions).
- **Fee constants** (0.07) still await the owner's confirmation at kalshi.com/fee-schedule.
- Kalshi data is for the owner's private research; this report holds aggregates only.

## Bottom line for the owner
Cashing out a dog at 50-50 (or any level from 40¢ to 90¢) neither makes nor saves money compared with
holding it. It lowers the swings by giving up the big wins, but the typical bad outcome, a dog that
never comes back, is unchanged. The dog bet itself loses 11–29% depending on the tour and the fill.
On ordinary positions, each take-profit costs about 2–5¢ per contract in spread and fee in exchange for
a much smoother P&L. If smoother P&L is worth that to you, a small target (+3¢ to +10¢) buys the most
variance reduction per cent paid. It does not add expected profit.

Ranking mismatches don't change this: the much worse-ranked player reaches 50-50 about a third of the time, a
little less often than the price already implies, so buying them to sell at 50¢ loses too. Unranked players
lose more, partly because many of them are actually the favourite. Re-testing with a properly formed pre-match
entry (E1r) changes none of this.
