# DraftKings early-round underdogs: 250/500 tournaments (PRELIMINARY)

**PRELIMINARY: about one season of odds history (ATP Beijing 2024–25, ATP Doha/Dubai 2025, everything
else 2026 only), ~430 matches.**

**Answer: no edge at DraftKings' price, and most of the measured loss is a cold run, not DraftKings.**

- **Cold run first.** On the Sackmann-resolved half (events through May 2026), dogs lost **−29.9%** at
  DraftKings and **−29.7%** at Pinnacle: the sharp book's price lost just as much. Dogs won 24.5% of
  those matches while both books priced them at ~30%. That is bad luck for underdogs, not mispricing.
- **What to expect structurally:** if Pinnacle's de-vigged price is fair, a dog bet at DraftKings'
  price returns **−7.4%** on average (385 matches; −7.6% / −7.0% on the two halves). That is the cost of
  DraftKings' margin, **4.84%** vs Pinnacle's **2.82%**. The Jun–Oct 2026 half (Kalshi-resolved, 184
  bets) came in at **−4.5%**, close to that expectation (dogs won 35.4% vs 32.8% priced).
- **All dogs:** **−18.7%** at DraftKings (417 settled bets, 95% CI −31.9% to −5.6%), −15.6% at
  Pinnacle's price on the same matches. No dog price band is positive. Against seeded favourites (Sackmann
  seeds) the dog lost −27.5% (126 bets), but those are all in the cold half.
- **Model:** the Elo walk-forward (77 out-of-sample bets, 2026) **fails the gate** (−20.5%), and Elo
  prices worse than both books on the same 204 matches (log loss Elo 0.5562 vs DraftKings 0.5351,
  Pinnacle 0.5237). DraftKings' de-vigged prices are slightly less accurate than Pinnacle's
  (0.5691 vs 0.5666 on 397 matches).

How it was built:
- **Odds:** The Odds API historical snapshots, DraftKings + Pinnacle h2h, 6 h cells; price = the last
  snapshot ≥ 5 min before the listed start (median 79 min before, p90 269 min). 1,646 credits
  (docs/data_inventory.md). Odds data is never committed.
- **Results:** events through May 2026 from Jeff Sackmann's match files (CC BY-NC-SA 4.0). Jun–Oct 2026
  events from Kalshi settlements, via the Data role's `results_from_kalshi` run on our match list
  (source of truth: 198 of 199 listed events, sha256 checked; aggregates only).
  - The one miss is a duplicate DraftKings listing (Humbert vs "Andrej" Martin); it is dropped.
  - 3 of the 198 joined events (Monterrey, 2026-08-23) have no DraftKings price, so they add no bets.
  - Cross-check: an independent join of Data's hand-copied Kalshi table matched 195 events. All 195
    agree with Data's output on winner and void (0 disagreements); the other 3 are those Monterrey events.
- **WTA Tokyo is dropped.** Kalshi's data ends 2026-10-24/25, so it has only Tokyo qualifying, no main
  draw. It also has no Odds API key in our list, so it adds no rows either way. ATP Tokyo (Japan Open) is
  included.
- **Void rule = DraftKings':** walkovers / not-started matches and retirements during set 1 are void
  (stake back). The 11 Kalshi-side voids are all not-started matches settled at a fair price. No set-1
  retirement is in the list (the 2 Data flagged are other matches). A retirement after set 1 settles
  normally, as at DraftKings.
- **Rounds 1–2:** Sackmann rounds where joined; for Jun–Oct 2026 events, the first 3–4 days of play
  (Kalshi rounds: 142 R32, 53 R16).
- **Caveats:** a single season, mostly 2026 small events; the 5–10 and >10 odds bands have few bets;
  prices can be hours old for later matches in a 6 h cell.

## Full sample
Odds: The Odds API historical snapshots (DraftKings Sportsbook + Pinnacle; not redistributed). Results: Jeff Sackmann's match files (CC BY-NC-SA 4.0). 1 unit on the underdog (longer DK odds) at the last snapshot ≥ 5 min before the listed start; DK voids walkovers and retirements before set 1 is complete. Aggregates only.

### Coverage
- Events listed 596; joined to Sackmann 278; rounds 1–2 237; with a DraftKings price 431 (Pinnacle too: 397).
- DraftKings price age before the listed start: median 79 min, p90 269 min.

### (a) Every early-round underdog

| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |
|---|---|---|---|---|---|---|---|---|
| All | 417 | 14 | 29.0% | 33.7% | -18.7% | -31.9% to -5.6% | -20.3% | -15.6% (385) |
| … ATP | 270 | 7 | 29.3% | 32.3% | -14.6% | -31.3% to +3.5% | -16.3% | -13.5% (256) |
| … WTA | 147 | 7 | 28.6% | 36.3% | -26.1% | -45.7% to -6.1% | -27.5% | -19.6% (129) |
| … Slams | 0 | 0 | — | — | — | — | — | — |
| … 1000s | 0 | 0 | — | — | — | — | — | — |
| Seeded favourite vs unseeded dog | 126 | 1 | 21.4% | 27.4% | -27.5% | -51.7% to -1.5% | -29.0% | -27.8% (107) |
| … ATP | 101 | 0 | 22.8% | 27.2% | -22.0% | -50.1% to +9.9% | -23.6% | -26.0% (94) |
| … WTA | 25 | 1 | 16.0% | 28.0% | -49.8% | -92.3% to +1.3% | -50.8% | -40.8% (13) |

By DraftKings underdog odds:

| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |
|---|---|---|---|---|---|---|---|---|
| dog odds (1.0, 2.0] | 30 | 1 | 43.3% | 51.2% | -15.4% | -48.2% to +17.5% | -16.7% | -12.9% (28) |
| dog odds (2.0, 3.0] | 188 | 4 | 37.8% | 41.7% | -9.0% | -25.2% to +7.6% | -10.6% | -5.7% (175) |
| dog odds (3.0, 5.0] | 147 | 7 | 23.1% | 26.8% | -17.1% | -41.4% to +8.2% | -18.9% | -11.8% (135) |
| dog odds (5.0, 10.0] | 39 | 2 | 7.7% | 16.2% | -46.9% | -100.0% to +19.8% | -48.2% | -52.4% (35) |
| dog odds (10.0, inf] | 13 | 0 | 0.0% | 6.9% | -100.0% | -100.0% to -100.0% | -100.0% | -100.0% (12) |

Seeded favourite only, by underdog odds:

| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |
|---|---|---|---|---|---|---|---|---|
| dog odds (1.0, 2.0] | 3 | 0 | 33.3% | 51.5% | -35.7% | -100.0% to +93.0% | -36.6% | -100.0% (2) |
| dog odds (2.0, 3.0] | 36 | 1 | 27.8% | 39.7% | -27.8% | -64.6% to +10.0% | -29.1% | -23.9% (32) |
| dog odds (3.0, 5.0] | 58 | 0 | 24.1% | 26.4% | -13.1% | -50.9% to +27.0% | -14.9% | -7.2% (48) |
| dog odds (5.0, 10.0] | 17 | 0 | 11.8% | 14.9% | -23.4% | -100.0% to +91.4% | -25.4% | -40.2% (14) |
| dog odds (10.0, inf] | 12 | 0 | 0.0% | 6.8% | -100.0% | -100.0% to -100.0% | -100.0% | -100.0% (11) |

### (b) Elo model, walk-forward by season

**Gate: FAIL**  OOS bets >= 30 (77): yes; OOS P&L > 0 at 0% haircut: no; OOS P&L > 0 at 3% haircut: no; >= 3 of last 4 seasons positive at 3% (0/2): no

| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |
|---|---|---|---|---|---|---|---|---|
| OOS, all | 77 | 0 | 26.0% | 31.3% | -20.5% | -50.2% to +12.5% | -22.1% | -17.0% (66) |
| … ATP | 47 | 0 | 25.5% | 30.2% | -19.7% | -58.1% to +25.4% | -21.4% | -17.3% (44) |
| … WTA | 30 | 0 | 26.7% | 33.1% | -21.6% | -66.5% to +28.8% | -23.1% | -16.5% (22) |

| Season | Threshold | Bets | P&L 0% | P&L −3% |
|---|---|---|---|---|
| 2025 | — | 0 | +0.0u | +0.0u |
| 2026 | 0.02 | 77 | -15.8u | -17.0u |

Fixed thresholds over all seasons (in-sample, diagnostic):

| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |
|---|---|---|---|---|---|---|---|---|
| Every dog (≥ min history) | 233 | 3 | 24.5% | 32.7% | -29.9% | -46.6% to -13.2% | -31.3% | -29.7% (204) |
| edge ≥ 0.00 | 135 | 1 | 24.4% | 30.8% | -23.6% | -47.3% to +0.4% | -25.2% | -25.1% (119) |
| edge ≥ 0.02 | 123 | 1 | 25.2% | 29.9% | -20.2% | -44.9% to +6.3% | -21.8% | -21.7% (111) |
| edge ≥ 0.05 | 107 | 1 | 24.3% | 28.8% | -22.2% | -49.4% to +8.1% | -23.8% | -25.7% (97) |
| edge ≥ 0.08 | 90 | 1 | 21.1% | 27.5% | -34.3% | -60.7% to -6.3% | -35.7% | -41.8% (80) |
| edge ≥ 0.10 | 83 | 1 | 21.7% | 26.8% | -31.3% | -61.2% to -3.1% | -32.7% | -39.0% (73) |
| edge ≥ 0.15 | 68 | 1 | 23.5% | 26.5% | -27.2% | -59.4% to +6.4% | -28.7% | -40.3% (61) |

### (c) DraftKings vs Pinnacle

| Book | Matches | Mean margin | Median margin | Log loss (de-vigged) | Mean p(dog) |
|---|---|---|---|---|---|
| DraftKings | 397 | 4.84% | 4.85% | 0.5691 | 30.9% |
| Pinnacle | 397 | 2.82% | 2.86% | 0.5666 | 31.5% |
| Realized | 385 | | | | 29.6% |

Same 204 matches with an Elo model price (Sackmann-resolved): log loss DraftKings 0.5351, Pinnacle 0.5237, Elo 0.5562; mean p(dog) DK 29.8%, Pinnacle 30.3%, Elo 33.9%, realized 24.5%.

Margin by tour:

| Tour | DK margin | Pinnacle margin |
|---|---|---|
| ATP | 4.82% | 2.78% |
| WTA | 4.86% | 2.91% |

Calibration by Pinnacle's de-vigged p(dog):

| p(dog) | Matches | Upset rate | DK de-vigged | Pinnacle de-vigged | Elo model |
|---|---|---|---|---|---|
| (0.0, 0.15] | 33 | 6.1% | 8.8% | 9.0% | 14.4% |
| (0.15, 0.25] | 86 | 15.1% | 20.2% | 20.4% | 25.2% |
| (0.25, 0.35] | 103 | 34.0% | 29.3% | 29.8% | 33.2% |
| (0.35, 0.45] | 113 | 39.8% | 40.2% | 40.4% | 43.1% |
| (0.45, 0.5] | 45 | 33.3% | 47.3% | 47.4% | 49.4% |

## Check: Sackmann-resolved subset only (events through May 2026)

### Coverage
- Events listed 596; joined to Sackmann 278; rounds 1–2 237; with a DraftKings price 236 (Pinnacle too: 207).
- DraftKings price age before the listed start: median 79 min, p90 249 min.

### (a) Every early-round underdog

| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |
|---|---|---|---|---|---|---|---|---|
| All | 233 | 3 | 24.5% | 32.7% | -29.9% | -46.6% to -13.2% | -31.3% | -29.7% (204) |
| … ATP | 178 | 2 | 24.2% | 31.7% | -28.3% | -47.9% to -8.1% | -29.7% | -30.1% (164) |
| … WTA | 55 | 1 | 25.5% | 35.9% | -35.1% | -62.6% to -4.2% | -36.3% | -28.0% (40) |
| … Slams | 0 | 0 | — | — | — | — | — | — |
| … 1000s | 0 | 0 | — | — | — | — | — | — |
| Seeded favourite vs unseeded dog | 126 | 1 | 21.4% | 27.4% | -27.5% | -51.7% to -1.5% | -29.0% | -27.8% (107) |
| … ATP | 101 | 0 | 22.8% | 27.2% | -22.0% | -50.1% to +9.9% | -23.6% | -26.0% (94) |
| … WTA | 25 | 1 | 16.0% | 28.0% | -49.8% | -92.3% to +1.3% | -50.8% | -40.8% (13) |

### (c) DraftKings vs Pinnacle

| Book | Matches | Mean margin | Median margin | Log loss (de-vigged) | Mean p(dog) |
|---|---|---|---|---|---|
| DraftKings | 207 | 4.81% | 4.84% | 0.5351 | 29.8% |
| Pinnacle | 207 | 2.75% | 2.81% | 0.5237 | 30.3% |
| Realized | 204 | | | | 24.5% |

Same 204 matches with an Elo model price (Sackmann-resolved): log loss DraftKings 0.5351, Pinnacle 0.5237, Elo 0.5562; mean p(dog) DK 29.8%, Pinnacle 30.3%, Elo 33.9%, realized 24.5%.
