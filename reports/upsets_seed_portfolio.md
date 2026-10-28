# Seed losing early: back the unseeded player at DraftKings (pre-registration)

**Status: PRE-REGISTERED, PRELIMINARY, no results yet.** This document was committed before any code or result for this
rule existed. Results will be added below it, and the rule won't change. Owner request 2026-10-28 ("add seed losing
early as a portfolio"); plan approved by the Lead the same day.

## Disclosure: one slice of this has already been seen
The private Tennis Backtest Explorer (2026-10-26) has a row "Seeded favourite vs unseeded dog": **2,894 bets at
DraftKings' closing price, about −11%**. That is the subset of this rule where the unseeded player is also DraftKings'
underdog, on almost the same data. So that slice isn't blind. The rest of the rule, where the unseeded player is
DraftKings' favourite, and every split below, has not been looked at. The expectation below was written knowing the
−11% figure.

## Question
In rounds 1–2, when a seeded player meets an unseeded one, does backing the unseeded player at DraftKings make money?

## Data
- **Odds:** the cached Odds API h2h snapshots of the DK studies (#99, #100), DraftKings + Pinnacle. Price = each book's
  last snapshot at least 5 min before the listed start (the Portfolio backtest's convention, `upsets.dk_history.collect`).
  Coverage: Slams from 2020, 1000s and 250/500s from 2024, rounds 1–2.
- **Results, seeds, rounds and entry type:** Jeff Sackmann's match files (`w_seed`/`l_seed`, `w_entry`/`l_entry`,
  `round`). They end in May 2026, so the test does too.
  - Kalshi results (Jun–Oct 2026) are not used, since they carry no seeds.
- **Voids:** walkovers and other void results (`sackmann` `void`) are left out. That is close to DraftKings' rule: a
  walkover or a retirement before set 1 is complete returns the stake.
- Odds data is never committed. Only aggregates appear here.

## Rule (fixed before looking)
- **Match qualifies:** round 1 or 2 of the event (`round_idx` ≤ 2), exactly one player seeded.
- **Bet:** 1 unit on the unseeded player at DraftKings' odds, whether DraftKings has them as the underdog or the
  favourite.
- **Fair chance:** Pinnacle's two prices, de-vigged with the power method (`upsets.odds.devig_power`), as on the page
  since #112.
- **Three fixed sub-rules, all reported:**
  - (a) every qualifying match;
  - (b) the unseeded player entered as a qualifier or lucky loser (Sackmann entry `Q` or `LL`);
  - (c) every other unseeded player (direct acceptance, wildcard, protected ranking, etc.).

## What is reported
- **ROI at DraftKings:** P&L per unit staked, with a 95% bootstrap CI clustered by match.
- **Expected ROI at Pinnacle-fair:** mean of DK odds × Pinnacle fair p − 1. It says what the bets were worth if
  Pinnacle's price was right.
- **CLV against Pinnacle's close:** DK odds × Pinnacle's closing fair p − 1, where Pinnacle's close is its last quote
  at least 5 min before the start. Since the bet price is also the last snapshot, CLV and expected ROI are close to
  equal here. That is by construction, not evidence.
- **Splits:** seed band of the seeded opponent (1–4, 5–8, 9–16, 17–32), qualifier vs not, tour, tier, and DK
  underdog vs DK favourite, per season.
- **Robustness (reported, not part of the gate):** ROI with DraftKings' odds cut by 3%, standing in for slippage.

## Gate
The rule has nothing to fit (no threshold or parameter is chosen from the data), so every bet is out of sample by
construction. A sub-rule passes only if all of these hold:
- at least 30 bets;
- total P&L at DraftKings > 0;
- positive P&L in at least 3 of the last 4 seasons (2023, 2024, 2025, 2026 to May).

**Multiple testing:** three sub-rules are tested on one dataset, so a single pass in (b) or (c) is weak evidence on its
own. It would go to a forward test, not to "real".

## Expectation (written before the run)
- **Negative ROI overall.** Phase A found seeds lose about 30% of R1/R2 matches against unseeded players, roughly 2 pp
  more than Elo expects. But that gap is in the market already: DraftKings early-round underdogs lost −11% (#99, all
  tiers) to −19% (#86, 250/500s), about DraftKings' margin, and the seeded-favourite slice above is about −11%.
- **The DK-favourite unseeded players** (a seed priced as the underdog) should lose roughly DraftKings' smaller
  favourite-side margin, about −2% to −5%.
- **Qualifiers (b)** are the only place an edge could plausibly show. Phase A's 2 pp excess upset rate was mostly
  against qualifiers. Even so, the expectation is a loss there too, smaller than in (c).

## Live counterpart (after the backtest)
- **What it is:** a fourth Portfolio strategy, "Seed loses early", with $10 paper bets, settled by `/scores` like the
  others and inside the page's 3,000-credit cap.
- **Seeds:** read from Wikipedia's tournament articles via the MediaWiki API, credited CC BY-SA on the page. An event
  whose seed list doesn't parse is skipped and logged, never guessed.
- **Round 1–2:** a labelled proxy, the seeded player's first or second listed match in that event in the page's own
  odds history.
- **Coverage:** like the other strategies, it only trades tournaments `/scores` covers, so its ledger stays empty until
  about Jan 2027.

## Results
Not run yet.
