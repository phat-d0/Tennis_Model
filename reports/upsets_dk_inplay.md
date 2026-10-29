# In-play studies on DraftKings prices: DOG50, exit-level curve, MISMATCH50, FAVDIP (pre-registration)

**Status: RUN 2026-10-29. Every gate FAILs; results in `reports/upsets_dk_inplay_results.md`.** Pre-registered as below. Owner request 2026-10-28: "make sure all these are for the
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

## Amendment 2026-10-28 (2): the in-play window (written before any outcome is read; revised 2026-10-29)
**Why.** An audit of the pulled snapshots found four problems. It read only quote ages, price levels, listed start
times and pre-match fields, never a result.
- **Duplicate listings.** DK often lists one pairing as more than one event: a placeholder for a later start (often the
  next day at 00:00, with prices that never move) next to the real event. Matching by player names latched onto
  placeholders (248 of 281 "unfinished" 2024 matches).
  - The walk now uses the event the DK close came from: `close_event_ids` = `dk_close_check.close_events`, the latest DK
    snapshot ≥ 5 min before its own event's start, over all events joined to the match.
  - It falls back to names only when there is none.
  - **Lead review, 2026-10-29:** the first version took the first joined event instead. That changed the event for 370
    of 733 matches in 2023, 290 of 1,056 in 2024, 54 in 2025 and 2 in 2026.
- **Wrong anchor (found in that review).** `dk_history.prices` reads the right close prices and ages, but the
  `commence` column it outputs is the first joined event's start, not the close event's.
  - They differ by more than 1 h for 363 of 733 matches in 2023 (90th percentile +54 h), 289 of 1,056 in 2024, 13 in
    2025 and 1 in 2026.
  - The window now anchors on the close event's own listed start. The label itself is fixed in its own PR.
  - **The earlier reading "DK had no live market for about half of 2023" came from this anchor bug and is withdrawn.**
    With the right event and start, DK quoted 90% of 2023 matches in play.
- **Leap-frogging starts.** In 2023–24 a delayed match's listed start keeps moving to just after each snapshot, so "the
  start listed in that snapshot" alone can't mark the start of play.
- **Lookahead risk.** Any snapshot taken after a match ended could show settled or near-settled odds, which would give
  away the winner and could fake a "dog reached 50%" trigger or a hedge fill.

**Rule: (a‴), chosen by the Lead's decision rule** ("use (a‴) if it keeps ≥ 90% of what (a′) keeps in 2023–24"). After
both fixes it keeps 99–100% in every season. It replaces "in-play snapshot" everywhere above
(`upsets.dk_inplay.window`, column `live_started`). A snapshot counts as in play for a match only if all of these hold:
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

Matches kept (cache replay, 0 credits):

| Season | Matches | (a) | (a′) | **(a‴)** | Pinnacle moved > 5 pp from its close in those snapshots: (a) / (a′) / (a‴) |
|---|---|---|---|---|---|
| 2023 | 733 | 659 | 661 | **659** | 60% / 59% / 60% |
| 2024 | 1,056 | 892 | 925 | **918** | 66% / 62% / 65% |
| 2025 | 1,753 | 1,560 | 1,619 | **1,605** | 67% / 60% / 66% |
| 2026 | 1,131 | 1,081 | 1,080 | **1,074** | 68% / 60% / 67% |

**Sample: 4,256 matches.**
- 2025–26 is the main sample: 2,679 of 2,884 matches (93%).
- 2023–24 is secondary: 1,577 of 1,789 (88%).
- The 2023–24 counts can still rise: some of their real windows have snapshots we never pulled (refinement plan below).

**Which matches DK quoted live.** Pre-match data only, `subset_table`:

| Season | Quoted in play | Matches | Slam | 1000 | 250/500 | Dog's DK close odds (median) | Elo gap (median) |
|---|---|---|---|---|---|---|---|
| 2023 | no | 74 | 100% | 0% | 0% | 6.75 | 250 |
| 2023 | yes | 659 | 100% | 0% | 0% | 3.10 | 124 |
| 2024 | no | 138 | 96% | 4% | 0% | 5.50 | 228 |
| 2024 | yes | 918 | 67% | 31% | 3% | 3.10 | 125 |
| 2025 | no | 148 | 76% | 20% | 4% | 5.00 | 209 |
| 2025 | yes | 1,605 | 41% | 56% | 4% | 2.85 | 124 |
| 2026 | no | 57 | 39% | 54% | 7% | 12.40 | 277 |
| 2026 | yes | 1,074 | 32% | 54% | 14% | 2.85 | 110 |

- **In every season the matches DK didn't quote live are the big mismatches** (dog median 5.00–12.40 vs 2.85–3.10, Elo
  gap 209–277 vs 110–125). They also lean to Slams.
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
- `close_event_ids` returns the re-listing the close came from, and its start, when a placeholder is joined first.
- A cache replay counts un-pulled snapshots instead of ending a match.

**Refinement (plan only, needs the Lead's approval; remaining cap 64,000):**
- **Un-pulled slots.** The pull walked ~650 matches in 2023–24 from the first-joined event's start, so part of their
  real window was never pulled.
  - The fix is a re-run of the merged `pull --season` with the corrected anchor. Cached slots are free; it pays only
    the missing ones and stops a match at its finish.
- **Postponed.** The close's event was later listed for a start more than 1 h after the close's, and our pull ended
  before it. These are re-walked from their final listed start at 10 min, with the same stop rules.
- **Same spending path as the pull.** Every refinement snapshot goes through `make_fetch`: job cap 270,000, the 5,000
  floor check, every spend logged. The postponed re-walk needs a small CLI option (a pull of those matches from their
  final start), which goes up for review before any call.

Refinement plan, newest season first (credits are ceilings: the walk stops a match once its finish is seen):

| Season | Matches with un-pulled slots | Credits ≤ | Postponed matches | Credits ≤ | Total ≤ |
|---|---|---|---|---|---|
| 2026 | 0 | 0 | 4 | 970 | 970 |
| 2025 | 3 | 260 | 16 | 2,970 | 3,230 |
| 2024 | 189 | 7,170 | 12 | 3,060 | 10,230 |
| 2023 | 147 | 7,270 | 4 | 1,240 | 8,510 |
| **All** | 339 | 14,700 | 36 | 8,240 | **22,940** |

The total fits in the remaining cap of 64,000 (job total now 206,000 of 270,000).

**Refinement run 2026-10-29 (un-pulled slots, Lead-approved after #166).** Run from main 7f91c1b, newest season first.
- **Spend:** 2025 120, 2024 6,030, 2023 5,740 credits. Total 11,890 of the 14,700 ceiling; job total 217,890 of 270,000.
- **Re-stated from the cache (0 credits):** no match has an un-pulled slot left.

| Season | Matches | (a) | (a′) | **(a‴)** | (a‴) / (a′) |
|---|---|---|---|---|---|
| 2023 | 733 | 691 | 697 | **694** | 100% |
| 2024 | 1,056 | 920 | 948 | **943** | 99% |
| 2025 | 1,753 | 1,560 | 1,619 | **1,605** | 99% |
| 2026 | 1,131 | 1,081 | 1,080 | **1,074** | 99% |

**Sample now 4,316 matches.** 2025–26: 2,679 of 2,884 (93%, unchanged). 2023–24: 1,637 of 1,789 (92%).

The excluded matches are still the big mismatches:

| Season | Not quoted live | Dog's DK close odds (median) | Elo gap (median) | Quoted live | Dog odds | Elo gap |
|---|---|---|---|---|---|---|
| 2023 | 39 | 15.00 | 412 | 694 | 3.10 | 124 |
| 2024 | 113 | 5.62 | 240 | 943 | 3.15 | 125 |
| 2025 | 148 | 5.00 | 209 | 1,605 | 2.85 | 124 |
| 2026 | 57 | 12.40 | 277 | 1,074 | 2.85 | 110 |

**Postponed (still to run):** 32 matches (2026 4, 2025 16, 2024 11, 2023 1), at most 6,900 credits. They run via
`pull --season S --postponed`, which:
- finds the season's postponed matches by a cache replay, with the same `is_postponed` rule as the coverage table;
- moves their start to the final listed start;
- walks the same event through `make_fetch`.

Each stage stops at 125% of its ceiling. It runs only after the Lead has reviewed the option.

**Postponed re-walk 2026-10-29 (Lead-approved after #168).** Run from main 8589013, newest season first.
- **Spend:** 2026 70, 2025 10, 2024 700, 2023 10 credits. Total 790 of the 6,900 ceiling; job total 218,680 of 270,000.
- **Still postponed:** DK moved most of these listings again. A cache replay still flags 30 of the 32 as postponed past
  our re-walked window, and the (a‴) counts didn't change. As the Lead decided, they are not chased further: they stay
  out of the sample and are counted.

**Study sample = (a‴) and not still postponed:**

| Season | (a‴) | Still postponed | **Sample** |
|---|---|---|---|
| 2023 | 694 | 0 | **694** |
| 2024 | 943 | 7 | **936** |
| 2025 | 1,605 | 16 | **1,589** |
| 2026 | 1,074 | 2 | **1,072** |
| **All** | 4,316 | 25 | **4,291** |

- 2025–26 (main sample): 2,661 of 2,884 matches (92%).
- 2023–24 (secondary): 1,630 of 1,789 (91%).
- The other 5 of the 30 still-postponed matches had no (a‴) snapshot anyway.

## Amendment 2026-10-29 (3): how the studies are scored
**Timing, stated plainly.**
- The rules below were fixed in the study code (`upsets/dk_inplay_study.py`, commit ff6165d, 03:45 UTC) and in a message
  to the Lead (03:47 UTC), before any study number was read.
- This written amendment is committed after the first run had been read.
- The exit-curve rule doesn't change any verdict: the walk-forward fails under either reading (0 of 3 and 1 of 3 test
  seasons positive).

**Exit-level walk-forward (rule 2), as accepted by the Lead.** With data for 2023 to May 2026, only 2024, 2025 and 2026
can be test seasons; 2023 has no earlier season, and 2026 is a partial season (Jan–May). The gate becomes:
- all 3 test seasons positive;
- out-of-sample P&L > 0 in 2025–26;
- at least 30 out-of-sample positions.

That is stricter than "3 of 4".

**Fixed rules (1, 3, 4B) in 2025–26 alone** (the window amendment's condition) means:
- at least 30 bets in 2025–26;
- P&L > 0 there at the 3% cut.

**Fills.** An in-play trigger or fill uses a snapshot inside the (a‴) window whose DK quote is at most 5 min old; a 1-min
version is reported as a check. No 5-min snapshots were pulled, so the 10-min vs 5-min check can't be run.

**Added descriptive rows (not gate inputs).**
- **Still-postponed matches put back** (Lead): one row per study.
- **Expected cost of each hedge** (added after the first run was read), beside the realized Δ vs hold:
  - the locked result minus the fair value of holding at that snapshot, using Pinnacle's in-play power de-vig p when it
    is quoted ≤ 5 min old;
  - the realized Δ mixes the hedge's cost with the luck of how held dogs finished, and this version doesn't.

## Amendment 2026-10-29 (4): DK in-play price validity, criteria set before looking
**Why.** Pinnacle's in-play quotes in these snapshots barely move, even though their `last_update` looks fresh (§ amendment
3). So DK's in-play prices, which every study fill uses, need their own check. The Lead asked for it before accepting any
study section. It uses prices only, no win/loss outcomes, and costs 0 credits.

**Tests**, on (a‴) rows of sample matches, with p = DK's power de-vig for the home player:
1. **Convergence.** At each match's last (a‴) snapshot, the share of DK quotes that are decided (p ≤ 0.10 or ≥ 0.90),
   against the same share at its first (a‴) snapshot. The same for Pinnacle, for contrast.
2. **Movement.** The distribution of DK's snapshot-to-snapshot |Δp| within (a‴), and the share of consecutive (a‴)
   snapshots where DK's two prices are identical to the previous ones. The same for Pinnacle.
3. **Kalshi cross-check (when Data can run it).** DK p against Kalshi's mid at the same minute for overlapping
   ATP/WTA matches: correlation of levels and of changes. Aggregates only; Kalshi data stays private. This container
   holds no Kalshi data, so Data would run it.

**Pass criteria (fixed now, before any number):**
- DK decided share at the last (a‴) snapshot ≥ 70%;
- DK identical-consecutive share ≤ 20%.

If DK fails either one, no study section is sent as a finding until the Lead decides.

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
