# In-play studies on DraftKings prices: DOG50, exit-level curve, MISMATCH50, FAVDIP (pre-registration)

**Status: PLAN, PRE-REGISTERED, nothing pulled, no results.** Owner request 2026-10-28: "make sure all these are for the
app too, not just the Kalshi bets". The Lead asked for a plan only; **no credits are spent until the Lead approves the
number.** This document was written before any in-play price was pulled. The rules below won't change once data
exists. Any change gets a dated amendment written before its run.

## What is already known (disclosure)
- **On Kalshi** (`reports/backtest_cashout.md`): DOG50, the exit-level curve, MISMATCH50 and MISMATCH50-U all FAIL.
  - Every dog exit level 40–90¢ is within ±1¢/contract of holding.
  - The worse-ranked player reaches 50¢ less often than its price implies.
- **On DraftKings pre-match** (#86, #99, #134): early-round dogs lose about DK's margin (−10% to −19%).
- FAVDIP had not been run on either venue when this plan was written.
- **Amendment 2026-10-28, before any pull:** Kalshi's FAVDIP result has since come back (Backtest): **FAIL**. Buying at 50%
  in play did worse than buying at the start in 5 of 6 cells. The one bright cell is WTA favourites ≥ 80%: +11.2% on 132
  bets, CI −6% to +28%. That is now a disclosed prior for DK-FAVDIP. The rules above don't change.
- **Data audit:** the only in-play prices we have looked at are a data audit of the cached snapshots, run while writing
  this plan. It covered quote ages and price ranges only, never outcomes (§ Data).

## Question
Using DraftKings' own prices, through The Odds API's historical snapshots:
1. Do the cash-out rules, tested on Kalshi, do any better at DK?
2. Does buying a pre-match favourite after it falls to 50% in play beat buying it at the start?

## Data
- **Universe:** the early-round (R1–R2) tour-level matches we already hold DraftKings + Pinnacle closes for:
  - Slams from 2020, 1000s and 250/500s from 2024;
  - Sackmann results through May 2026;
  - 6,319 matches.
  The proposed pull covers 2023–May 2026 (4,673 matches) or less; see Credits.
- **In-play prices** come from `/v4/historical/sports/{key}/odds`:
  - `markets=h2h`, `bookmakers=draftkings,pinnacle`, decimal odds;
  - one snapshot every 10 min across each match's live window, refined to 5 min (see Credits).
  - Facts and evidence are in docs/research/odds_api.md §4.
- **Usable quote:** a bookmaker's h2h quote is used only when its `last_update` is at most 5 min before the snapshot.
  An in-play market is suspended between points and dropped after about 15 min, so older quotes are stale. A ≤ 1 min
  version is reported as a check.
- **Results and voids:** Sackmann winners. Walkovers and retirements before set 1 is complete are void; both legs are
  refunded, as at DraftKings (`sackmann.void`). A retirement after set 1 stands, and the player who advances wins.
- **No Kalshi data anywhere** in this study, its outputs or the page.
- Odds API data is never committed. Only aggregates appear here.

## Prices and fills
- **Probabilities:**
  - "p" = DK's two decimal odds de-vigged with the power method (`upsets.odds.devig_power`).
  - The fair reference is Pinnacle's in-play power de-vig at the same snapshot, when quoted and fresh.
- **A bet** is filled at DK's decimal odds at the snapshot where its trigger is first seen. Stake 1 unit.
- **Cash-out = hedge to equal payout** (the swing-lock equivalent; a sportsbook bet has no bid):
  - First bet: stake s₁ at odds o₁, which pays N = s₁·o₁.
  - Hedge: bet the other player at their live DK odds o₂, stake s₂ = N / o₂.
  - Locked result either way: N − s₁ − s₂ = s₁·(o₁ − 1 − o₁/o₂).
  - The hedge is placed at the first snapshot where its trigger holds.
- **Robustness (reported for every rule):**
  - DK odds cut by 3% and by 6% on every in-play fill, standing in for in-play acceptance delay and price moves
    between snapshots;
  - the ≤ 1 min quote-age version;
  - 10-min vs 5-min triggers on the subset where both exist.
- **Caveat:** DraftKings may reject or re-price in-play bets, and limits differ by account. A 5- or 10-min snapshot is
  the price shown then, not a guaranteed fill. These are paper results at displayed prices.

## Amendment 2026-10-28 (2): the in-play window (written before any outcome is read)
**Why.** An audit of the pulled snapshots found four problems. It read only quote ages, price levels, listed start
times and pre-match fields, never a result.
- **Duplicate listings.** DK often lists one pairing as more than one event: a placeholder for a later start (often the
  next day at 00:00, with prices that never move) next to the real event. Matching by player names latched onto
  placeholders (248 of 281 "unfinished" 2024 matches). The walk now uses the event the DK close came from
  (`close_event_ids`, joined to Sackmann by player ids) and falls back to names only when there is none.
- **No live market in 2023–24.** For about half the 2023 matches, the close's event disappears at the start and no other
  listing carries live prices: the only other listing of the pairing in the match window is a placeholder dated about a
  day later whose DK prices don't move (favourite odds range 0.00 at the median). DK offered no in-play market we can
  see for those matches.
- **Leap-frogging starts.** In 2023–24 a delayed match's listed start keeps moving to just after each snapshot, so "the
  start listed in that snapshot" alone can't mark the start of play.
- **Lookahead risk.** Any snapshot taken after a match ended could show settled or near-settled odds, which would give
  away the winner and could fake a "dog reached 50%" trigger or a hedge fill.

**Rule: (a‴), chosen by the Lead's decision rule** ("use (a‴) if it keeps ≥ 90% of what (a′) keeps in 2023–24"; it keeps
99% in every season). It replaces "in-play snapshot" everywhere above (`upsets.dk_inplay.window`, column `live_started`).
A snapshot counts as in play for a match only if all of these hold:
- (a‴) its timestamp is at least 15 min after the start listed **at the close** (known in advance), and the start listed
  in that same snapshot is not later than its timestamp (the listing has stopped leap-frogging: play has begun).
- (b) the match's DK quote in it was updated within the last 15 min. A frozen quote means the market was suspended or the
  match was finished.
- (c) neither it nor any earlier in-play snapshot of the match shows a DK price ≤ 1.01 or ≥ 50. That snapshot counts as
  settled and ends the window: it and every later snapshot are out.
- (d) it is no later than the close's listed start + 6 h.

The two variants it was chosen against, reported once here:
- (a) needed timestamp ≥ the start listed in that same snapshot + 15 min.
- (a′) used only the close's listed start.

| Season | Matches | (a) | (a′) | **(a‴)** | Pinnacle moved > 5 pp from its close in those snapshots: (a) / (a′) / (a‴) |
|---|---|---|---|---|---|
| 2023 | 733 | 356 | 361 | **359** | 55% / 55% / 55% |
| 2024 | 1,056 | 641 | 674 | **667** | 66% / 62% / 65% |
| 2025 | 1,753 | 1,549 | 1,606 | **1,592** | 67% / 60% / 66% |
| 2026 | 1,131 | 1,080 | 1,080 | **1,074** | 68% / 60% / 67% |

**Sample: 3,692 matches.** 2025–26 is the main sample, covering 2,666 of 2,884 matches (92%). 2023–24 covers 1,026 of
1,789 (57%).

**Which matches DK quoted live.** Pre-match data only, `subset_table`:

| Season | Quoted in play | Matches | Slam | 1000 | 250/500 | Dog's DK close odds (median) | Elo gap (median) |
|---|---|---|---|---|---|---|---|
| 2023 | no | 374 | 100% | 0% | 0% | 3.20 | 132 |
| 2023 | yes | 359 | 100% | 0% | 0% | 3.15 | 126 |
| 2024 | no | 389 | 98% | 2% | 0% | 3.70 | 148 |
| 2024 | yes | 667 | 54% | 42% | 3% | 3.10 | 125 |
| 2025 | no | 161 | 78% | 19% | 4% | 4.70 | 209 |
| 2025 | yes | 1,592 | 40% | 56% | 4% | 2.80 | 124 |
| 2026 | no | 57 | 39% | 54% | 7% | 12.40 | 277 |
| 2026 | yes | 1,074 | 32% | 54% | 14% | 2.85 | 110 |

- **2023:** the quoted half looks like the excluded half.
- **2024:** the excluded matches are mostly Slams with longer dogs.
- **2025–26:** the excluded matches are the big mismatches (dog median 4.70 / 12.40, Elo gap 209 / 277).
- **So the in-play sample under-represents heavy underdogs.** That matters most for DK-DOG50 (dogs < 20%, odds > 5):
  its results describe the heavy dogs DK chose to quote live, not all of them.

**Reporting and gate (added):**
- Every study is reported three ways: 2025–26 (main), 2023–24 (secondary) and pooled.
- **A gate pass counts only if it also holds in 2025–26 on its own.**
- The season walk-forward for the exit curve keeps its test seasons.

**Reported alongside, never as gate inputs:**
- **Sackmann-minutes cut:** also require timestamp ≤ the close's listed start + Sackmann `minutes` + 30 min. This uses
  the match's real length, so it is labelled a robustness check.
- **Final-start cut:** also require timestamp ≥ the match's final listed start + 15 min. This uses later information,
  so it is descriptive only.
- **Every rule split by stopped vs not.** "Stopped" = the walk saw the event drop out of the snapshots (finished), or never
  found it.

**Tests** (`tests/test_upsets_dk_inplay.py`):
- A synthetic post-finish snapshot (a settled price, or a stale quote) and every later snapshot are never in play.
- The walk follows the close's event rather than a duplicate listing.
- A cache replay counts un-pulled snapshots instead of ending a match.

**Coverage of the real event:** the approved re-walk (7 snapshots, 70 credits) left 0 matches with un-pulled snapshots.

**Refinement for postponed matches (plan only, needs the Lead's approval):**
- **Which matches:** 46 (2023 9, 2024 12, 2025 20, 2026 5). Postponed = the close's event was later listed for a start
  more than 1 h after the close's, and our pull ended before it. Events that just stop being listed at the start are not
  postponed: DK had no live market for them.
- **What:** re-walk them from their final listed start, at 10 min, with the same stop rules.
- **Budget:** ≤ 9,980 credits, inside the 30,000 refinement allowance and the 270,000 cap (job total now 206,000).

## Rules (fixed now)
1. **DK-DOG50.**
   - Entry: back the pre-match dog with DK close p < 20% (also reported for < 30%), at DK's close.
   - Exit: hedge to equal payout at the first in-play snapshot where the dog's DK p ≥ 50%.
   - Control: hold to the result.
2. **DK exit-level curve.** Same entries as DK-DOG50, with the hedge level L at 0.40, 0.50, …, 0.90, plus hold.
   For each L, report P&L, ROI, Δ vs hold, SD and P10. The Kalshi report has the same table.
3. **DK-MISMATCH50.**
   - Match qualifies: Sackmann **official ATP/WTA ranks** before the match, ratio ≥ 4× and the better player ranked
     ≤ 100 (the owner's "#20 vs #200").
   - Back the worse-ranked player at DK's close; hedge at the first in-play p ≥ 50%.
   - Also reported: how often he reaches 50%, against the rate DK's close implies.
4. **DK-FAVDIP**, in two fixed bands: the DK close favourite at p 60–80%, and at ≥ 80%.
   - (A) Control: back the favourite at DK's close.
   - (B) Back the favourite at the first in-play snapshot where his DK p ≤ 50%. If that never happens, there is no bet.
   - Both are held to the result.
   - The comparison is ROI(B) vs ROI(A), and ROI(B) on matches where B triggered vs ROI(A) on the same matches.

## Gate (per rule; FAVDIP per band)
- **Fixed rules (1, 3, 4B):** at least 30 bets; P&L > 0 at the 3% odds cut; positive P&L in at least 3 of the last 4
  seasons (2023, 2024, 2025, 2026 to May).
- **Exit level (2):** walk-forward by season. L is chosen on earlier seasons, by total P&L at the 3% cut, with hold
  always eligible, and tested on the next season. Out-of-sample P&L must be positive in at least 3 of 4 test seasons,
  with at least 30 out-of-sample positions.
- **No lookahead:**
  - Triggers use only snapshots up to their own time.
  - Entries use the close (the last pre-match snapshot ≥ 5 min before the start).
  - A test shuffles later snapshots and checks that earlier decisions don't change.
- **Multiple testing:** four rule families across two bands and two dog cut-offs, so a single PASS is weak evidence. It
  would go to the live paper Portfolio as a forward test, not to "real".

## Expectation (written before any pull)
- **DK-DOG50 and the exit-level curve:** lose about DK's in-play margin on the hedge leg, on top of the entry's
  pre-match margin. Δ vs hold will be negative, about −2% to −5% per hedged position. FAIL.
- **DK-MISMATCH50:** FAIL, like Kalshi. The worse-ranked player reaches 50% about as often as his price implies, or less.
- **DK-FAVDIP:** B loses more than A. Buying at 50% pays the in-play margin and selects favourites who are playing
  badly. FAIL in both bands.

## Credits (dry run, `python -m upsets.dk_inplay plan`, 0 credits)
- **Cost rule:** one snapshot = 10 credits (h2h; draftkings + pinnacle are one region block). It covers every event of
  that key at that moment.
- **What counts:** distinct (key, snapshot) pairs inside each match's live window, where the live window is the
  commence time + Sackmann minutes + slack for late starts.
- The archive is 10-min before 2022-09-18 and 5-min after.

| Universe | Matches | 5 min, +1 h slack | 5 min, +3 h slack | 10 min, +1 h | 10 min, +3 h |
|---|---|---|---|---|---|
| All seasons (2020–May 2026) | 6,319 | 446,770 | 537,430 | 249,240 | 300,430 |
| 2023–May 2026 (5-min archive) | 4,673 | 397,800 | 476,330 | 200,270 | 239,330 |
| 2024–May 2026 | 3,940 | 352,280 | 420,750 | 177,400 | 211,460 |
| 2025–May 2026 | 2,884 | 271,470 | 322,800 | 136,650 | 162,190 |

By tier, 2023–May 2026, 10 min, +3 h slack: 1000s 1,843 matches / 105,930; Slams 2,592 / 106,390; 250/500s 238 / 27,010.

**Approved cap: 300,000 credits** (owner, via the Lead, 2026-10-28). Staged: a pilot on one tournament (≤ 2,000
credits), checked and reported to the Lead before the full pull. **Proposed full pull:**
- 2023–May 2026, 10-min snapshots, ≤ 239,330 credits.
- Plus a 5-min refinement: one extra snapshot just before each first trigger, ≤ 30,000 credits.
- **Total cap 270,000.**
- The pull walks each key's snapshots in time order and stops a match's window once the event is gone from the
  snapshot (finished). So the +3 h slack is an upper bound, and the real spend should come in lower.
- Every call goes through the existing floor check (5,000) and the spend log; the run stops at the cap.

## Live tracking in the app (plan only; see the Lead's decision)
The page builds every 3 h, too slow for in-play triggers. The proposal:
- **What:** a separate in-play poller that paper-trades the same four rules at DK. Only rules whose backtest is run
  appear, labelled "not proven" unless they PASS.
- **Where:** a GitHub Actions workflow on a 10-min schedule, reusing the page's Odds API secret, cache and
  restore-from-page mechanism.
  - The VPS was considered. It is Tailscale-only with no public path to the page, so it would need a repo write token.
  - Actions' schedule can run late; a late poll only means fewer entries, and every fill is still the price shown at
    that poll.
- **Calls:**
  - free `/events` to find keys with an event whose commence time has passed;
  - `/odds?markets=h2h&bookmakers=draftkings,pinnacle` for those keys only, at 1 credit per key per poll;
  - `/scores` as today for settlement.
- **Cost estimate:** about 2–3 tour-level keys in play per day for about 13 h. At 10 min that is about 160–240
  credits/day, about 5–7k/month. At 5 min it is about 10–14k/month. Both are small next to the 5M plan and the
  page's 3,000 cap; this needs its own cap (proposed 10,000/month).
- **Kalshi data never touches it.**
