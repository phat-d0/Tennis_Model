# Fallen-favourite study: findings

**Status: PRELIMINARY.** These are Kalshi 1-minute candles with no order-book depth; each leg is carried forward
≤ 1,800 s. The study was pre-registered in `docs/edge_favdip.md` (2026-10-28) before any run. Data ran it on
2026-10-28 from `main` 98fa42c (phat-d0/Tennis_Model#156) with `python -m swinglock.backtest.favdip`, on both research
groups, with 0 Kalshi requests. This report holds aggregates only, copied from the run summaries. Each whole summary
was sha256-checked: ATP/WTA 9d8878b1…, after Data corrected one CI cell it had mistyped when pasting, and
Challenger/WTA 125 b67eba89….

## The answer (the owner's question)
**Does buying the original favourite when it drops to 50¢ beat buying it at the start? No.** In every gated band of
every tier except one, the dip buy has a **worse ROI** than the start buy. **Every pre-registered gate FAILs.**

ROI at 0¢ / 1¢ slippage, each rule on its own entries (the owner's comparison):

| Band (pre-match ask) | Tier | START entries | START ROI | DIP50 entries | DIP50 ROI |
|---|---|---|---|---|---|
| 60–80¢ | ATP | 1,254 | −5.0% / −6.3% | 706 | −13.3% / −15.0% |
| 60–80¢ | WTA | 1,206 | −3.7% / −5.0% | 691 | −6.1% / −7.9% |
| 60–80¢ | Challenger/WTA 125 | 4,265 | −3.1% / −4.5% | 2,529 | −4.2% / −6.1% |
| 80–97¢ | ATP | 413 | −0.7% / −1.8% | 98 | −10.2% / −12.1% |
| 80–97¢ | WTA | 539 | +0.4% / −0.7% | 132 | **+13.5% / +11.2%** (1¢ CI −6.3% to +27.8%) |
| 80–97¢ | Challenger/WTA 125 | 1,804 | −0.1% / −1.1% | 402 | −1.4% / −3.4% |
| 50–60¢ (context) | ATP | 580 | −6.2% / −7.8% | 460 | −9.8% / −11.6% |
| 50–60¢ (context) | WTA | 587 | −3.9% / −5.5% | 491 | −4.6% / −6.5% |
| 50–60¢ (context) | Challenger/WTA 125 | 2,098 | −3.9% / −5.5% | 1,729 | −6.3% / −8.1% |

**Is a fallen favourite underpriced at 50¢? No.** The test is the DIP50 win rate against what it costs (0¢,
all-in = ask + fee):

| Band | Tier | DIP50 win rate | Mean ask | Mean all-in | Win rate − all-in |
|---|---|---|---|---|---|
| 60–80¢ | ATP | 42.0% | 46.6¢ | 48.4¢ | −6.4 pp |
| 60–80¢ | WTA | 46.3% | 47.5¢ | 49.3¢ | −3.0 pp |
| 60–80¢ | Challenger/WTA 125 | 46.6% | 46.8¢ | 48.6¢ | −2.0 pp |
| 80–97¢ | ATP | 42.9% | 46.0¢ | 47.7¢ | −4.8 pp |
| 80–97¢ | WTA | 54.5% | 46.3¢ | 48.1¢ | +6.5 pp |
| 80–97¢ | Challenger/WTA 125 | 47.9% | 46.8¢ | 48.6¢ | −0.7 pp |

A favourite that has fallen to 50¢ wins **less** often than its price in 5 of the 6 gated cells. In 4 of them it
wins less often than even the raw ask. The market doesn't overreact to a favourite's slump; if anything it is slow
to mark the favourite down. Pooled over the three tiers, the 80–97¢ dip wins 48.5% against a 48.4¢ all-in cost
(632 entries): no edge before slippage, and a loss at 1¢.

**The one positive cell, WTA 80–97¢ DIP50 (+11.2% at 1¢), is not a finding.**
- It's 132 entries, and the CI includes zero.
- It is 1 of 6 gated band × tier cells (12 with the 50–60¢ context band).
- Its neighbours are negative: ATP 80–97¢ is −12.1% and Challenger 80–97¢ is −3.4%.
- WTA's DIP45/DIP40 rows are also positive, but they are nested subsets of the same matches, not independent
  evidence.
- It was found after the fact. It would need its own pre-registration and fresh data, such as live paper trading,
  before it could count.

## Gate (DIP50 per band, fixed rule, absolute P&L, monthly): FAIL in all four
Each test needs ≥ ⌈0.75 × months⌉ months positive at 1¢, total P&L > 0 at 0¢ and 1¢, and ≥ 30 entries.

| Group, band | Months positive at 1¢ (need 6 of 7) | P&L 0¢ / 1¢ | ROI 0¢ / 1¢ | Entries |
|---|---|---|---|---|
| ATP/WTA, 60–80¢ | 0 | −$660.71 / −$800.72 | −9.7% / −11.5% | 1,397 |
| ATP/WTA, 80–97¢ | 3 | +$37.96 / +$14.89 | +3.4% / +1.3% | 230 |
| Challenger/WTA 125, 60–80¢ | 1 | −$515.38 / −$768.93 | −4.2% / −6.1% | 2,529 |
| Challenger/WTA 125, 80–97¢ | 2 | −$27.30 / −$67.58 | −1.4% / −3.4% | 402 |

ATP/WTA 80–97¢ fails on months only: its total is positive, but only 3 of 7 months are, and its WTA half is the
cell discussed above.

## How often favourites fall, and when
Share of favourites whose ask reaches 50¢ in play on a formed book:

| Band | ATP | WTA | Challenger/WTA 125 |
|---|---|---|---|
| 50–60¢ | 79.3% | 83.7% | 82.4% |
| 60–80¢ | 56.3% | 57.3% | 59.3% |
| 80–97¢ | 23.7% | 24.5% | 22.3% |

So about half of 60–80¢ favourites and a quarter of 80–97¢ favourites trade at 50¢ or below at some point (deeper
dips: 47–51% reach 40¢ in the 60–80¢ band, 17–20% in the 80–97¢ band). The dip comes a median **35–46 min** after
the scheduled start for 60–80¢ favourites, and **71–73 min** for 80–97¢ favourites.

## Paired: DIP50 vs START on the matches where the dip happened
On the same matches, the dip buy beats the start buy by **+20¢ per contract** (60–80¢) and **+37–38¢** (80–97¢); the
CIs are narrow. **This comparison is biased by construction:** it only includes matches where the favourite was
already losing, so START is measured on its worst matches (START ROI −32% to −50% there). It says that buying later
at a lower price is better *once you know the dip happens*. You can't know that at the start, so it is not the
owner's question. The unconditional ROIs above are.

## Before vs after the end of set 1 (descriptive; ATP/WTA only)
| Band | Dip before set 1 ends: entries, ROI 1¢ (CI) | After: entries, ROI 1¢ (CI) |
|---|---|---|
| 60–80¢ | 1,071, −11.2% (−17.3% to −5.7%) | 289, −10.1% (−21.6% to +1.9%) |
| 80–97¢ | 114, +1.4% (−15.6% to +19.7%) | 106, +0.3% (−19.8% to +20.0%) |

When the dip happens makes no difference that the data can see. Dips in matches with no set-1 market are left out
of these rows: 37 in the 60–80¢ band and 10 in the 80–97¢ band.

## Against the pre-registered expectation
- **START**, expected −2% to +1% ROI. 80–97¢ favourites match that (−0.7%, +0.4%, −0.1% at 0¢). 60–80¢ favourites
  are worse than expected (−3.1% to −5.0% at 0¢): their win rate is 0.6–1.9 pp below their ask, so mid-priced favourites
  are slightly overpriced too, not only underdogs.
- **DIP50**, expected −3% to −6%. Challenger 60–80¢ (−4.2%) and WTA 60–80¢ (−6.1%) are in range. ATP is worse
  (−13.3% / −10.2%), Challenger 80–97¢ a little better (−1.4%), and WTA 80–97¢ is the outlier above.
- **Verdict FAIL**, as expected, in every gated band of both groups.

## Caveats
- **Candles, not order books.** Fills assume the sampled ask in full size, up to 10 contracts. Moves inside a minute
  are missed, so the true first-dip price can differ by a tick.
- **Taker only.** Every fill pays the spread and the taker fee. A resting bid at 50¢ (maker) was not tested.
- **Favourite** = the higher ask at the last formed pre-match row. It is not the opening line, and it is not a
  bookmaker's line.
- **Many cells.** Each band × tier cell is a separate look. Only the pre-registered per-band gate counts.
- **Fee constants** (0.07) still await the owner's confirmation at kalshi.com/fee-schedule.
- Kalshi data is for the owner's private research; this report holds aggregates only.

## Bottom line for the owner
Waiting for a favourite to fall to 50¢ and then buying it does **not** beat buying it before the match. In
mid-priced matches (60–80¢) it loses more: the favourite that falls to 50¢ goes on to win a bit *less* often than
50%, so the market is not overreacting to its slump. For heavy favourites (80–97¢), buying at the start is about
break-even before slippage, and buying the dip is no better overall. The one WTA cell that looks good is a small,
after-the-fact sample. If you want to pursue it, the honest next step is to pre-register it and paper-trade it on
new matches; the backtest can't support it.
