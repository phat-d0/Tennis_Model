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

Generated by `python -m upsets.seed_portfolio`. 3,123 qualifying matches, Aug 2020 – May 2026. 1 unit per bet. Aggregates only.

### Verdict

**No sub-rule passes the gate.** Backing the unseeded player against a seed returned -10.3% a bet at DraftKings over 3,123 matches, against -14.2% expected at Pinnacle's fair price.

- Qualifiers and lucky losers: -8.2% over 538 bets (3 of 4 recent seasons positive, total -44.3u).
- Unseeded players DraftKings makes the favourite: -1.7% over 269 bets.
- As pre-registered, three sub-rules on one dataset means any single bright spot in a split below is weak evidence.

### Gate (per pre-registered sub-rule)

| Sub-rule | Bets | P&L | Seasons positive (of 2023–2026) | Gate |
|---|---|---|---|---|
| (a) All unseeded players | 3,123 | -322.8u | 0 | FAIL |
| (b) Qualifiers and lucky losers | 538 | -44.3u | 3 | FAIL |
| (c) Other unseeded players | 2,585 | -278.5u | 0 | FAIL |

### Sub-rules

| Slice | Bets | Win rate vs Pinnacle-fair | ROI at DK (95% CI) | Expected ROI = CLV | ROI, odds −3% | P&L |
|---|---|---|---|---|---|---|
| (a) All unseeded players | 3,123 | 27.2% vs 25.5% | -10.3% (-16.8% to -3.3%) | -14.2% | -13.0% | -322.8u |
| (b) Qualifiers and lucky losers | 538 | 25.5% vs 21.9% | -8.2% (-23.1% to +7.7%) | -15.8% | -11.0% | -44.3u |
| (c) Other unseeded players | 2,585 | 27.5% vs 26.3% | -10.8% (-17.6% to -3.5%) | -13.9% | -13.4% | -278.5u |

### Seed band of the opponent

| Slice | Bets | Win rate vs Pinnacle-fair | ROI at DK (95% CI) | Expected ROI = CLV | ROI, odds −3% | P&L |
|---|---|---|---|---|---|---|
| 1–4 | 466 | 12.7% vs 12.3% | -30.0% (-51.1% to -7.6%) | -27.9% | -32.1% | -139.9u |
| 5–8 | 451 | 22.6% vs 20.1% | -1.9% (-22.2% to +20.7%) | -14.0% | -4.9% | -8.8u |
| 9–16 | 840 | 26.1% vs 25.2% | -12.5% (-24.1% to +0.2%) | -13.5% | -15.1% | -104.6u |
| 17–32 | 1,354 | 34.1% vs 31.9% | -5.1% (-13.5% to +3.2%) | -10.1% | -8.0% | -69.7u |

Qualifiers only, by seed band of the opponent:

| Slice | Bets | Win rate vs Pinnacle-fair | ROI at DK (95% CI) | Expected ROI = CLV | ROI, odds −3% | P&L |
|---|---|---|---|---|---|---|
| 1–4 | 93 | 9.7% vs 10.6% | -52.0% (-82.7% to -12.2%) | -30.4% | -53.5% | -48.4u |
| 5–8 | 82 | 20.7% vs 17.0% | -13.4% (-50.6% to +28.0%) | -17.9% | -16.0% | -11.0u |
| 9–16 | 142 | 25.4% vs 22.5% | -8.5% (-36.2% to +21.5%) | -15.2% | -11.3% | -12.1u |
| 17–32 | 221 | 33.9% vs 28.2% | +12.3% (-12.1% to +37.4%) | -9.3% | +8.9% | +27.1u |

### DraftKings' view of the unseeded player

| Slice | Bets | Win rate vs Pinnacle-fair | ROI at DK (95% CI) | Expected ROI = CLV | ROI, odds −3% | P&L |
|---|---|---|---|---|---|---|
| DK underdog | 2,854 | 23.9% vs 22.3% | -11.1% (-18.5% to -3.6%) | -15.0% | -13.8% | -318.1u |
| DK favourite | 269 | 61.3% vs 59.2% | -1.7% (-11.8% to +8.1%) | -5.4% | -4.7% | -4.7u |

Qualifiers only, by draftKings' view of the unseeded player:

| Slice | Bets | Win rate vs Pinnacle-fair | ROI at DK (95% CI) | Expected ROI = CLV | ROI, odds −3% | P&L |
|---|---|---|---|---|---|---|
| DK underdog | 522 | 24.1% vs 20.7% | -8.8% (-24.4% to +8.3%) | -16.2% | -11.6% | -46.1u |
| DK favourite | 16 | 68.8% vs 61.7% | +11.1% (-30.1% to +47.5%) | -4.6% | +7.9% | +1.8u |

### Tour

| Slice | Bets | Win rate vs Pinnacle-fair | ROI at DK (95% CI) | Expected ROI = CLV | ROI, odds −3% | P&L |
|---|---|---|---|---|---|---|
| atp | 1,576 | 26.7% vs 24.9% | -8.3% (-17.8% to +1.4%) | -14.7% | -11.0% | -130.4u |
| wta | 1,547 | 27.6% vs 26.2% | -12.4% (-20.8% to -3.0%) | -13.7% | -15.1% | -192.4u |

### Tier

| Slice | Bets | Win rate vs Pinnacle-fair | ROI at DK (95% CI) | Expected ROI = CLV | ROI, odds −3% | P&L |
|---|---|---|---|---|---|---|
| slam | 2,078 | 24.4% vs 23.2% | -13.1% (-21.5% to -4.0%) | -16.4% | -15.7% | -271.3u |
| 1000 | 924 | 33.7% vs 30.7% | -2.2% (-12.8% to +9.1%) | -11.0% | -5.2% | -20.6u |
| other | 121 | 25.6% vs 26.6% | -25.5% (-48.8% to -1.1%) | -0.9% | -27.8% | -30.9u |

### Season

| Slice | Bets | Win rate vs Pinnacle-fair | ROI at DK (95% CI) | Expected ROI = CLV | ROI, odds −3% | P&L |
|---|---|---|---|---|---|---|
| 2020 | 61 | 13.1% vs 23.0% | -70.1% (-88.5% to -47.9%) | -17.6% | -71.0% | -42.8u |
| 2021 | 260 | 24.6% vs 23.0% | -12.7% (-35.2% to +12.7%) | -16.4% | -15.4% | -33.1u |
| 2022 | 327 | 23.9% vs 22.9% | -10.0% (-31.1% to +13.7%) | -17.6% | -12.7% | -32.8u |
| 2023 | 374 | 25.9% vs 24.2% | -14.8% (-31.0% to +2.7%) | -16.5% | -17.4% | -55.4u |
| 2024 | 606 | 27.4% vs 25.0% | -10.9% (-26.0% to +6.1%) | -15.3% | -13.6% | -65.9u |
| 2025 | 938 | 30.1% vs 27.5% | -2.4% (-14.1% to +9.3%) | -11.2% | -5.3% | -22.6u |
| 2026 | 557 | 27.5% vs 26.6% | -12.6% (-27.7% to +4.1%) | -13.2% | -15.2% | -70.1u |
