# DraftKings early-round underdogs: Slams, 1000s and 250/500s

**Answer: no edge at DraftKings' price. Underdogs lose what DraftKings' margin says they should.**

- **The structural cost:** if Pinnacle's de-vigged price is fair, an early-round underdog bet at
  DraftKings' closing price should return **−10.9%**. It returned **−11.2%** on 6,655 settled
  matches (95% CI −15.0% to −7.3%), matching that. Ask for 1 unit and get back 0.89 on average.
- **Why −11% and not −5%:** DraftKings' margin is 5.16% a match against Pinnacle's 2.75%. On top of
  that, it puts most of its margin on the underdog, so a dog price is about twice as expensive as
  the margin suggests. It is cheapest on 1000s (expected −8.2%) and dearest on Slams (−12.9%).
- **Not a cold run this time:** by season, realized ROI swings between −43% (2020, 120 bets) and
  −4% (2022, 2025). Over 6,655 matches it lands on the expected −11%. The 250/500 report's −30% on
  the Sackmann half was luck; across all tiers it averages out.
- **Model:** the Elo walk-forward **fails the gate**: 2,426 out-of-sample bets at −15.3%, 0 of the
  last 4 seasons positive. Elo is less accurate than both books on the same matches (log loss Elo
  0.5854, DraftKings 0.5565, Pinnacle 0.5546).

How it was built:
- **Odds:** The Odds API historical h2h snapshots, DraftKings + Pinnacle; Slams from 2020, 1000s and
  250/500s from 2024. **Price = the close:** the last snapshot ≥ 5 min before the listed start
  (job C's 10-min cells; median 9 min before, p90 49 min). Odds data is never committed. Credits:
  docs/data_inventory.md (DK history 19,715; closes 42,960).
- **Results:**
  - Events through May 2026 come from Jeff Sackmann's match files (CC BY-NC-SA 4.0).
  - Jun–Oct 2026 events come from Kalshi settlements, via the Data role's `results_from_kalshi`
    run on our 1,294-event list.
  - Data's join: 1,293 matched, 58 qualifying rows left out, 1,235 rows with a round label,
    sha256 verified. Each event keeps its two largest Kalshi rounds (rounds 1–2), which drops QF/SF
    and round 3.
  - The one miss is the duplicate "Andrej" Martin DraftKings listing. Aggregates only.
- **Void = DraftKings' rule:** walkover / not started, or a retirement before set 1 is complete.
  Kalshi's set-1 status flags the latter (4 of the 34 Kalshi-side voids).
- **Rounds 1–2 for 2026 events:** the window starts at the first listing on or after the projected
  main-draw date − 1 day, so Wimbledon's qualifying week is no longer read as round 1 (fixed in
  this work). It runs for the round 1–2 days + 2, and then Kalshi's round labels decide.

### The 250/500 top-up
The first 250/500 study (reports/upsets_dk_small.md, merged) anchored 2026 events on their first
listing. That missed some round-2 matches; it priced no wrong ones, since Kalshi's rounds were all
R32/R16. With the fixed window and 506 more credits, the 250/500 sample is 455 bets (was 417):
underdogs −21.1% at DraftKings (CI −32.7% to −8.5%) vs −18.7% before, and −16.2% at Pinnacle. The
expected cost there is −5.9%; the rest is the same cold run the first report described.

## Full sample (all tiers)
Odds: The Odds API historical snapshots (DraftKings Sportsbook + Pinnacle; not redistributed). Results: Jeff Sackmann's match files (CC BY-NC-SA 4.0). 1 unit on the underdog (longer DK odds) at the last snapshot ≥ 5 min before the listed start; DK voids walkovers and retirements before set 1 is complete. Aggregates only.

### Coverage
- Events listed 13,393; joined to Sackmann 11,104; rounds 1–2 9,069; with a DraftKings price 7,261 (Pinnacle too: 6,728).
- DraftKings price age before the listed start: median 9 min, p90 49 min.

### DraftKings' price vs Pinnacle's fair price

Expected ROI = mean(Pinnacle de-vigged p(dog) × DK odds − 1): the cost of DraftKings' margin if Pinnacle is right. Realized ROI is on the same settled matches; the gap between them is luck (or Pinnacle being wrong).

| Slice | Matches | Pinnacle p(dog) | Upset rate | Expected ROI at DK (Pinnacle fair) | Realized ROI at DK | 95% CI |
|---|---|---|---|---|---|---|
| All | 6,655 | 29.0% | 29.5% | -10.9% | -11.2% | -15.0% to -7.3% |
| … ATP | 3,350 | 28.8% | 29.9% | -11.3% | -8.4% | -14.3% to -2.2% |
| … WTA | 3,305 | 29.1% | 29.0% | -10.5% | -14.0% | -19.1% to -8.6% |
| … 1000s | 2,153 | 32.6% | 34.3% | -8.2% | -4.6% | -10.9% to +2.0% |
| … 250/500s | 433 | 31.0% | 29.1% | -5.9% | -19.0% | -31.7% to -5.7% |
| … Slams | 4,069 | 26.8% | 26.9% | -12.9% | -13.8% | -18.8% to -8.4% |
| … results from Sackmann (through May 2026) | 5,643 | 28.6% | 29.3% | -11.1% | -10.4% | -14.6% to -6.2% |
| … results from Kalshi (Jun–Oct 2026) | 1,012 | 30.9% | 30.3% | -10.2% | -15.2% | -24.0% to -6.2% |
| … season 2020 | 120 | 25.9% | 17.5% | -14.5% | -42.5% | -66.8% to -16.9% |
| … season 2021 | 510 | 26.4% | 25.7% | -13.0% | -15.1% | -29.4% to -0.8% |
| … season 2022 | 588 | 26.5% | 29.6% | -13.6% | -4.3% | -19.3% to +10.8% |
| … season 2023 | 659 | 27.8% | 29.0% | -13.0% | -12.1% | -23.8% to +0.2% |
| … season 2024 | 1,033 | 27.3% | 27.9% | -12.9% | -13.9% | -23.9% to -3.3% |
| … season 2025 | 1,667 | 30.4% | 32.3% | -8.7% | -3.9% | -11.7% to +4.0% |
| … season 2026 | 2,078 | 30.5% | 29.6% | -9.6% | -14.4% | -20.7% to -7.3% |

### (a) Every early-round underdog

| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |
|---|---|---|---|---|---|---|---|---|
| All | 7,176 | 85 | 29.3% | 31.3% | -10.6% | -14.3% to -6.5% | -12.4% | -7.4% (6,655) |
| … ATP | 3,619 | 38 | 29.7% | 31.1% | -7.2% | -13.1% to -1.2% | -9.1% | -4.2% (3,350) |
| … WTA | 3,557 | 47 | 28.9% | 31.6% | -14.0% | -19.2% to -9.1% | -15.7% | -10.7% (3,305) |
| … Slams | 4,544 | 32 | 26.9% | 29.3% | -12.9% | -18.0% to -7.6% | -14.7% | -9.7% (4,069) |
| … 1000s | 2,177 | 35 | 34.5% | 35.2% | -3.5% | -9.7% to +2.9% | -5.4% | -1.2% (2,153) |
| … 250/500s | 455 | 18 | 28.4% | 33.6% | -21.1% | -32.7% to -8.5% | -22.6% | -16.2% (433) |
| Seeded favourite vs unseeded dog | 3,230 | 35 | 23.9% | 24.9% | -10.1% | -16.6% to -2.8% | -12.1% | -6.2% (2,850) |
| … ATP | 1,649 | 16 | 23.8% | 24.3% | -6.3% | -16.6% to +4.0% | -8.4% | -3.0% (1,454) |
| … WTA | 1,581 | 19 | 24.0% | 25.6% | -14.1% | -23.0% to -4.7% | -15.9% | -9.5% (1,396) |

By DraftKings underdog odds:

| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |
|---|---|---|---|---|---|---|---|---|
| dog odds (1.0, 2.0] | 483 | 4 | 48.0% | 51.1% | -6.0% | -14.3% to +2.5% | -7.4% | -3.4% (466) |
| dog odds (2.0, 3.0] | 3,024 | 34 | 40.5% | 41.4% | -1.9% | -6.0% to +2.5% | -3.6% | +1.0% (2,854) |
| dog odds (3.0, 5.0] | 2,054 | 29 | 24.1% | 26.7% | -10.2% | -17.0% to -3.2% | -12.2% | -6.8% (1,903) |
| dog odds (5.0, 10.0] | 1,079 | 16 | 11.6% | 15.2% | -22.0% | -34.1% to -8.6% | -24.0% | -22.1% (964) |
| dog odds (10.0, inf] | 536 | 2 | 4.1% | 6.8% | -41.5% | -63.9% to -14.4% | -43.1% | -34.5% (468) |

Seeded favourite only, by underdog odds:

| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |
|---|---|---|---|---|---|---|---|---|
| dog odds (1.0, 2.0] | 75 | 1 | 57.3% | 51.2% | +12.5% | -8.5% to +34.0% | +10.9% | +13.5% (70) |
| dog odds (2.0, 3.0] | 846 | 12 | 40.8% | 40.1% | +1.7% | -6.6% to +9.5% | -0.1% | +6.1% (767) |
| dog odds (3.0, 5.0] | 1,068 | 10 | 25.4% | 26.2% | -3.8% | -13.4% to +6.6% | -5.9% | +0.4% (945) |
| dog odds (5.0, 10.0] | 779 | 10 | 11.9% | 15.0% | -17.7% | -33.1% to -0.9% | -19.8% | -18.3% (673) |
| dog odds (10.0, inf] | 462 | 2 | 4.3% | 6.7% | -37.3% | -62.9% to -9.9% | -39.0% | -28.7% (395) |

### (b) Elo model, walk-forward by season

**Gate: FAIL**  OOS bets >= 30 (2426): yes; OOS P&L > 0 at 0% haircut: no; OOS P&L > 0 at 3% haircut: no; >= 3 of last 4 seasons positive at 3% (0/4): no

| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |
|---|---|---|---|---|---|---|---|---|
| OOS, all | 2,426 | 24 | 22.5% | 25.4% | -15.3% | -22.8% to -7.3% | -17.2% | -12.8% (2,216) |
| … ATP | 1,125 | 13 | 25.0% | 26.7% | -9.0% | -21.0% to +3.9% | -10.9% | -7.2% (1,027) |
| … WTA | 1,301 | 11 | 20.4% | 24.3% | -20.8% | -30.7% to -10.7% | -22.6% | -17.7% (1,189) |

| Season | Threshold | Bets | P&L 0% | P&L −3% |
|---|---|---|---|---|
| 2021 | 0.10 | 386 | -70.9u | -77.7u |
| 2022 | 0.15 | 317 | -9.8u | -16.5u |
| 2023 | 0.15 | 270 | -70.3u | -74.5u |
| 2024 | 0.15 | 426 | -68.8u | -76.9u |
| 2025 | 0.15 | 595 | -57.9u | -69.8u |
| 2026 | 0.15 | 432 | -94.0u | -101.4u |

Fixed thresholds over all seasons (in-sample, diagnostic):

| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |
|---|---|---|---|---|---|---|---|---|
| Every dog (≥ min history) | 6,156 | 52 | 29.1% | 31.0% | -9.7% | -14.2% to -5.4% | -11.5% | -6.5% (5,637) |
| edge ≥ 0.00 | 3,770 | 33 | 25.9% | 28.5% | -12.1% | -18.2% to -5.9% | -14.0% | -9.8% (3,443) |
| edge ≥ 0.02 | 3,568 | 32 | 25.3% | 28.0% | -12.5% | -18.4% to -6.8% | -14.4% | -10.4% (3,253) |
| edge ≥ 0.05 | 3,304 | 32 | 24.7% | 27.4% | -13.3% | -19.7% to -6.9% | -15.2% | -11.1% (3,008) |
| edge ≥ 0.08 | 3,051 | 31 | 23.7% | 26.8% | -14.6% | -21.3% to -7.9% | -16.5% | -12.2% (2,776) |
| edge ≥ 0.10 | 2,865 | 27 | 23.2% | 26.3% | -15.6% | -22.8% to -8.7% | -17.4% | -13.1% (2,607) |
| edge ≥ 0.15 | 2,456 | 22 | 22.1% | 25.1% | -15.8% | -23.4% to -7.9% | -17.7% | -13.4% (2,241) |

### (c) DraftKings vs Pinnacle

| Book | Matches | Mean margin | Median margin | Log loss (de-vigged) | Mean p(dog) |
|---|---|---|---|---|---|
| DraftKings | 6,728 | 5.16% | 5.08% | 0.5573 | 28.5% |
| Pinnacle | 6,728 | 2.75% | 2.78% | 0.5561 | 29.0% |
| Realized | 6,655 | | | | 29.5% |

Same 5,643 matches with an Elo model price (Sackmann-resolved): log loss DraftKings 0.5565, Pinnacle 0.5546, Elo 0.5854; mean p(dog) DK 28.2%, Pinnacle 28.6%, Elo 34.0%, realized 29.3%.

Margin by tour:

| Tour | DK margin | Pinnacle margin |
|---|---|---|
| ATP | 5.18% | 2.62% |
| WTA | 5.14% | 2.87% |

Calibration by Pinnacle's de-vigged p(dog):

| p(dog) | Matches | Upset rate | DK de-vigged | Pinnacle de-vigged | Elo model |
|---|---|---|---|---|---|
| (0.0, 0.15] | 1243 | 7.8% | 8.3% | 8.7% | 16.9% |
| (0.15, 0.25] | 1283 | 20.2% | 20.1% | 20.4% | 27.9% |
| (0.25, 0.35] | 1546 | 31.8% | 29.7% | 30.1% | 35.4% |
| (0.35, 0.45] | 1832 | 41.8% | 39.8% | 40.0% | 43.4% |
| (0.45, 0.5] | 674 | 46.9% | 46.8% | 47.2% | 48.3% |
