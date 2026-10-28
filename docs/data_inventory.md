# Data inventory

What's collected, where it lives, and every bulk pull / paid spend. Data role keeps this current.

## data-store branch
Nothing published yet. The repo is still public (Lead, 10:02 UTC 2026-10-24), so per CLAUDE.md owner rule 4
no Kalshi data goes there. Recorded order books stay on the VPS and never go to data-store (Lead decision).

## Local (Data session container, `data/`, gitignored)

### Kalshi settled matches: backfill in progress
`data/processed/kalshi/{matches,quotes}.parquet`, rewritten every 1,000 matches and after each work group.

Settled match events listed on 2026-10-24 (all with both markets, live or `/historical/`):

| Series | Tier | Settled events |
|---|---|---|
| KXATPMATCH | atp | 5,029 |
| KXWTAMATCH | wta | 5,034 |
| KXATPCHALLENGERMATCH | challenger | 10,232 |
| KXWTACHALLENGERMATCH | challenger | 2,214 |
| KXITFMATCH | itf | 20,530 |
| KXITFWMATCH | itf | 18,756 |
| **Total** | | **61,795** |

Work order: group 0 = ATP+WTA closing in the last 183 days (4,670), group 1 = Challenger, last 183
days (8,340), group 2 = everything else (48,785), newest first within each group.

**Group 0 done (recent ATP + WTA), re-normalized 2026-10-24 16:20 UTC** → `data/processed/kalshi_g0/`
(code as of #34, so `settle_a`/`settle_b` are filled):

| | |
|---|---|
| Matches | 4,686 (WTA 2,407, ATP 2,279); all with quotes; 4,685 with a scheduled start |
| Match close range | 2026-04-24 16:02 → 2026-10-24 15:41 UTC; 3,191 settled before the 2026-08-25 cutoff (`/historical/`) |
| Winners | A 2,294, B 2,231, NA 161 |
| Fair-price settlements | 161 (3.4 %), all `result: "scalar"`; `settle_a + settle_b` = $1.00 in 161 of 161 |
| Quote rows | 10,250,672 (1-min candles), 0.36 % NaN asks, carry cap 1800 s, 28 MB |
| Quote span | 2026-04-23 09:08 → 2026-10-24 15:42 UTC |
| Requests | group-0 fetch ≈ 7,400 (≈ 150 × 429 at a 1 req/s floor); re-normalize pass 477 (listings only, 80 × 429), 8,412 cache hits |

The group-0 fetch ran 10:39 → 15:46 UTC. Its pace swung between ~50 matches per 5 min and per 10 min:
`/historical/` candles need one call per market, and 429 bursts widened the request gap.

**Group 1 done (recent ATP Challenger + WTA 125), 2026-10-25 08:52 UTC** → `data/processed/kalshi_g12/`
(current code, `settle_a`/`settle_b` filled):

| | |
|---|---|
| Matches | 8,333 (KXATPCHALLENGERMATCH 6,667, KXWTACHALLENGERMATCH 1,666); 8,331 with quotes; 8,332 with a scheduled start |
| Match close range | 2026-04-24 23:50 → 2026-10-24 21:30 UTC; 5,342 settled before the 2026-08-25 cutoff |
| Winners | A 4,268, B 3,915, NA 150 |
| Fair-price settlements | 150 (1.8 %), `settle_a + settle_b` = $1.00 in 150 of 150 |
| Quote rows | 7,218,880 (1-min candles), 0.75 % NaN asks, carry cap 1800 s, 22.5 MB |
| Quote span | 2026-04-24 09:42 → 2026-10-24 21:31 UTC |
| Requests | ≈ 13,000 over all runs; final run (23:35 → 08:52) 8,280 requests, 902 × 429 (10.9 %), 6,851 cache hits |

**Group 2 (48,825 older ATP/WTA/Challenger and all ITF matches) was not collected**, by Lead
decision 2026-10-24 23:34. Results were uniform (no edge anywhere), group 2 would take about a week
at the rate Kalshi allows unauthenticated (≈ 0.2 req/s on `/historical/` candles with 429 backoff),
and collecting less keeps us lighter on the Kalshi Data ToU. It can be resumed later on a separate
machine (not the scanner/recorder IP) with `python -m swinglock.collectors.backfill --groups 2`;
the raw cache makes it resumable.

**The research set is groups 0 + 1:** 13,019 matches (ATP 2,279, WTA 2,407, ATP Challenger 6,667,
WTA 125 1,666), Apr 24 → Oct 24 2026, 17.47 M quote rows.

Historical cutoff (`GET /historical/cutoff`, market_settled_ts): 2026-08-25T00:00Z. Matches settled
before it come from `/historical/markets` + `/historical/markets/{t}/candlesticks`.
Milestones (scheduled start) cover start dates from ~Feb 2025 onward.

**Set winners (group 0)** → `data/processed/kalshi_g0/sets.parquet`: 9,350 set rows for 4,465 of 4,695 matches
(decided 8,914, fair price 436). No set-winner series exist for Challenger/WTA 125, so group 1 has none.

### Kalshi recorder trial (not kept for analysis)
`data/recorded/kalshi_trial/`: 3 minutes on 2026-10-24 10:34 UTC, 90 matches, 1,980 quote rows,
18,865 depth rows. A test of the recorder only; the real recording runs on the VPS.

## Known gaps
- No order-book depth before the recorder runs; candle quotes have NaN sizes.
- Candle legs are carried forward between sparse candles, capped at `data.max_carry_s`
  (see docs/data_kalshi_collector.md, "Carry-forward check").
- Fair-price (not-started) settlements have winner NA (see above; they pay $1 combined).

## Pull log
| Date (UTC) | Venue / endpoint | Range | Requests | Notes |
|---|---|---|---|---|
| 2026-10-24 09:15 | Kalshi listings + 3 ATP matches (trial) | 2026-10-23 | 178 | 0.5 s gap → 11 × 429, gap capped at 5 s |
| 2026-10-24 09:29 | Kalshi 80 ATP matches (trial) | Oct 2026 | 82 | 1.0 s gap, 0 × 429 |
| 2026-10-24 09:31–10:06 | Kalshi full backfill, v1 order (ATP first) | ATP newest 900 | ~1,120 | 16 × 429; stopped to switch to the new work order |
| 2026-10-24 09:50 | Kalshi orderbooks + candles + trades, BASTSI (carry check) | 12 min | 77 | 1 × 429 |
| 2026-10-24 10:06–10:20 | Kalshi trials: WTA 30, WTA 125 20, ITF 40 | Oct 2026 | ~210 | first grouped-candle version got HTTP 400s (requested-candle cap) |
| 2026-10-24 10:20–10:38 | Kalshi full backfill, new order | group 0 | ~200 | crashed on a proxy outage 10:38 |
| 2026-10-24 10:34 | Kalshi recorder trial | 3 min | 30 | 2 × 429 (shared IP with backfill) |
| 2026-10-24 10:43 | Kalshi `/live_data/batch` | 10 milestones | 1 | live fixture for score formats |
| 2026-10-24 10:39–15:46 | Kalshi backfill group 0 (relaunch loop, no relaunches needed) | ATP+WTA, Apr 24 → Oct 24 | ≈ 7,400 | ≈ 150 × 429 |
| 2026-10-24 15:47–16:20 | Kalshi group-0 re-normalize (`--groups 0`) | same | 477 | listings only; 80 × 429 |
| 2026-10-24 16:21–19:56 | Kalshi backfill groups 1–2 | Challenger | ≈ 4,000 | container reclaimed 19:56 |
| 2026-10-24 20:30–23:35 | Kalshi backfill groups 1–2 (relaunches) | Challenger | ≈ 650 | reclaimed again 20:34; keep-alive from 22:02; 2 listing-phase relaunches (network, 429) |
| 2026-10-24 23:35 → 2026-10-25 08:52 | Kalshi backfill `--groups 1` (Lead: stop after group 1) | Challenger | 8,280 | 902 × 429; group 2 not started |

| 2026-10-26 01:10–01:40 | Kalshi `/series`, set-winner listings (KXATP/KXWTASETWINNER events + `/historical/markets`) | all settled | ≈ 85 | 13 × 429 in one burst, then resumed from cache; `sets.parquet` for group 0 |
| 2026-10-26 04:30 | Kalshi `/milestones` listing (Data, results for the DK 250/500 study; a new `since` date missed the cache, avoidable) | since 2026-06-13 | 75 | 0 × 429 |

## The Odds API spends
Shared paid-plan key since 2026-10-26 (owner). Global floor 5,000; dk_live reserve 481. Per-call log:
`data/raw/odds_api/spend.log` (DK history) and `data/raw/odds_api/live/spend.log` (dk_live), gitignored.

| Date (UTC) | Who / job | Endpoint | Calls | Credits | Balance after |
|---|---|---|---|---|---|
| 2026-10-26 04:16 | Upsets, DK history 250/500 (owner-approved; cap 5,423 = 10,904 − 5,000 − 481) | start balance | — | — | 10,904 |
| 2026-10-26 04:16–04:20 | Upsets, phase (a) listings, 62 key-events, 478 listing calls | `/historical/sports/{key}/events` | 136 non-empty (342 empty, 0 credits) | 136 | 10,768 |
| 2026-10-26 04:22–04:24 | Upsets, phase (c) odds, 6 h cells, `bookmakers=draftkings,pinnacle` | `/historical/sports/{key}/odds` | 151 | 1,510 | 9,258 |
| | **Total for the 250/500 pull** | | 287 | **1,646** | 9,258 |

**Slams + 1000s pull** (Lead-approved 2026-10-26 after the owner's 5M-credit upgrade; job cap 40,000 = spend-log total ≤ 41,646; floor 5,000; 3 h cells; `python -m upsets.dk_history ... --tiers slam,1000 --project-until 2026-10-25 --snap-h 3`). Plan before the pull: ≤ 23,916 credits. Plan verified first with a free `/sports` call: 5,000,000 remaining, 0 used.

| Date (UTC) | Who / job | Endpoint | Calls | Credits | Balance after |
|---|---|---|---|---|---|
| 2026-10-26 05:03 | Upsets, DK history Slams + 1000s | start balance | — | — | 5,000,000 |
| 2026-10-26 05:03–05:13 | Upsets, listings, 106 key-events (916 listing calls; 96 empty, 0 credits) | `/historical/sports/{key}/events` | 820 non-empty | 820 | 4,999,168 |
| 2026-10-26 05:13–05:33 | Upsets, odds, 3 h cells, `bookmakers=draftkings,pinnacle` | `/historical/sports/{key}/odds` | 1,555 | 15,550 | 4,983,618 |
| 2026-10-26 05:39–05:41 | Upsets, top-up after the projected-event fix (qualifying week skipped, +2 days, listing window +10 d): listings + odds | events / odds | 33 + 116 | 33 + 1,160 | 4,982,425 |
| | **Total for the Slams + 1000s pull** | | 2,524 | **17,563** | 4,982,425 |
| 2026-10-26 05:41–05:42 | Upsets, 250/500 top-up with the same fix (6 h cells, as the original pull) | events / odds | 36 + 47 | 36 + 470 | 4,981,919 |
| | **DK history total so far (spend log)** | | 2,894 | **19,715** | 4,981,919 |

**Closing-price snapshots (job C)** (Lead-approved 2026-10-26; job cap 50,000 = spend-log total ≤ 69,715; floor 5,000; plan sent to the Lead before the pull). `python -m upsets.dk_history close --other-from 2024-01-01 --project-until 2026-10-25 --close-min 10`: per round 1–2 match the target is the listed start − 5 min; cached snapshots ≤ 10 min old reused (213); the rest in 10-min cells per key, most recent first. Close age: median 0, p90 4, max 10 min (+ the API's 5–10 min snapshot step).

| Date (UTC) | Who / job | Endpoint | Calls | Credits | Balance after |
|---|---|---|---|---|---|
| 2026-10-26 06:07–07:03 | Upsets, closing snapshots, 10,335 matches, `bookmakers=draftkings,pinnacle` | `/historical/sports/{key}/odds` | 4,296 paid (4,297 fetched) | 42,960 | 4,938,958 |
| | **DK history total so far (spend log)** | | 7,190 | **62,675** | 4,938,958 |

**DK in-play snapshots (DOG50 / exit curve / MISMATCH50 / FAVDIP on DK)** (owner-approved cap 300,000; Lead's job cap 270,000
in this job's own spend log `data/raw/odds_api/inplay/spend.log`; floor 5,000; pre-registered in reports/upsets_dk_inplay.md,
phat-d0/Tennis_Model#157). Staged: pilot ≤ 2,000 first, full pull only after the Lead's go. In-play snapshots are cached apart
(`data/raw/odds_api/inplay/`) so the close studies' closes don't change.

| Date (UTC) | Who / job | Endpoint | Calls | Credits | Balance after |
|---|---|---|---|---|---|
| 2026-10-28 17:09–17:11 | Upsets, in-play **pilot**, ATP Qatar 2025 (24 R1–R2 matches), 10-min, `bookmakers=draftkings,pinnacle` | `/historical/sports/{key}/odds` | 175 | 1,750 | 4,652,408 |
| 2026-10-28 17:37–18:00 | Upsets, in-play stage 1, season 2026 (1,131 R1–R2 matches; stopped by an HTTP 502 in tennis_atp_italian_open; 6 of 23 keys done, 304 matches at 53.4 credits each vs 63.2 planned; resumes after #163) | `/historical/sports/{key}/odds` | 1,667 | 16,670 | 4,624,936 |
| 2026-10-28 18:15–19:13 | Upsets, in-play stage 1 resumed from main (`pull --season 2026`, after #163); cached snapshots re-read free | `/historical/sports/{key}/odds` | 4,232 | 42,320 | 4,561,316 |
| | **Season 2026 done:** 1,131 matches, 58,990 credits = 52.2/match (plan 60.5); event found 1,107, seen in play 1,107, finish detected 1,096 | | 5,899 | 58,990 | |
| 2026-10-28 19:15–21:03 | Upsets, in-play stage 2, season 2025 (`pull --season 2025`, from main 9c8c243) | `/historical/sports/{key}/odds` | 7,953 | 79,530 | 4,477,245 |
| | **Season 2025 done:** 1,753 matches, 79,530 credits = 45.4/match (plan 53.5); event found 1,735, seen in play 1,735, finish detected 1,678 | | | | |
| 2026-10-28 21:04–21:59 | Upsets, in-play stage 3, season 2024 (`pull --season 2024`, from main 9c8c243) | `/historical/sports/{key}/odds` | 4,199 | 41,990 | 4,435,245 |
| | **Season 2024 done:** 1,056 matches, 41,990 credits = 39.8/match (plan 46.7); event found 1,032, seen in play 1,032, finish detected 775 (2024 events often stay listed after the match, so their windows ran to the slack) | | | | |
| 2026-10-28 22:00–22:32 | Upsets, in-play stage 4, season 2023 (`pull --season 2023`, from main 9c8c243) | `/historical/sports/{key}/odds` | 2,367 | 23,670 | 4,411,572 |
| | **Season 2023 done:** 733 matches (Slams), 23,670 credits = 32.3/match (plan 38.0); event found 712, seen in play 712, finish detected 385 | | | | |
| | **In-play job total, pull complete (its spend log)** | | 20,593 | **205,930** of the 270,000 cap | 4,411,572 |

