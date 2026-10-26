# Line shopping: DraftKings vs Pinnacle's fair price (pre-registration)

**Status: PRE-REGISTERED, no results yet.** This section was committed before any line-shopping
code or result existed, so the git history shows the rule was fixed first. Results will be added
below it, and the rule will not be changed.

## Question
When DraftKings' price on a player is longer than Pinnacle's no-vig ("fair") price in the same
snapshot, does betting that side at DraftKings make money?

## Data
- The Odds API historical h2h snapshots already cached for the DK studies (DraftKings + Pinnacle).
  They cover Slams 2020–2026, 1000s 2024–2026 and 250/500s 2024–2026, rounds 1–2, and include the
  closing snapshots of job C.
- Results come from Jeff Sackmann's match files (events through May 2026) and Kalshi settlements
  supplied by the Data role (Jun–Oct 2026). Void follows DraftKings' rule: a walkover, a match not
  started, or a retirement before set 1 is complete returns the stake.
- Odds and Kalshi data are never committed. Only aggregates appear here.

## Rule (fixed before looking)
- **Fair chance:** Pinnacle's two prices, de-vigged with the power method (`upsets.odds.devig_power`,
  the same one the DK studies use), in the same snapshot as the DraftKings price.
- **Candidate bet:** side s of match m at snapshot k qualifies at threshold t when DraftKings' decimal
  odds on s × Pinnacle's fair p(s) − 1 > t, for t ∈ {0, 1%, 2%, 3%}. Both sides are tested, not only
  the underdog.
- **One bet per side per match:** the first qualifying snapshot in time order, 1 unit at DraftKings'
  odds in that snapshot.
  - Only snapshots taken at least 5 min before the listed start count.
  - The closing snapshot (the last one ≥ 5 min before the start) is excluded, because it is the CLV
    benchmark. A match whose only snapshot is the close yields no bet.
- **Scores**, each with a 95% bootstrap CI clustered by match:
  1. Realized ROI.
  2. Expected ROI at Pinnacle's fair price: DK odds × fair p − 1 at bet time.
  3. CLV against Pinnacle's close: DK odds × Pinnacle's closing de-vigged p(s) − 1.
- **Walk-forward by season:** for season S, t is the threshold with the best realized P&L on seasons
  before S, among thresholds with ≥ 30 bets there. Season S is then out of sample. The first season
  with history gives no OOS bets.
- **Gate (the project's):** ≥ 30 OOS bets, OOS P&L > 0, and ≥ 3 of the last 4 seasons positive. A
  CLV > 0 with a CI above 0 is reported alongside, but it is not a pass by itself.
- **Also reported:**
  - How often DK beats Pinnacle-fair at all: per (match, side, snapshot) and per match.
  - How stale DK's quote was at those moments: DK `last_update` − Pinnacle `last_update`, in minutes.
- **Slices reported:** all; ATP/WTA; Slams/1000s/250-500s; favourite/underdog side; and per season.
  Every slice computed is shown, none dropped.

## Results
(to be added)
