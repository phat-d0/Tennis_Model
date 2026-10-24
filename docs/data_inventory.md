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

**Checkpoint 2026-10-24 10:47 UTC (group 0, first 1,000 matches):**

| | |
|---|---|
| Matches | 1,000 (WTA 577, ATP 423), all with quotes and a scheduled start |
| Match close range | 2026-09-06 22:44 → 2026-10-24 09:25 UTC (all post-cutoff so far) |
| Winners | A 508, B 453, NA 39 |
| Quote rows | 1,802,442 (2 per timestamp), source `candle`, 0.37 % NaN asks, carry cap 1800 s |
| Quote span | 2026-09-04 18:07 → 2026-10-24 09:25 UTC |
| File size | quotes.parquet 5.3 MB |

**The 39 NA winners are all fair-price settlements** (`result: "scalar"` on both markets, e.g.
0.40/0.60, 0.32/0.68). The two legs' settlement values **sum to exactly $1.00 in all 39**, which answers
open question 4 in docs/research/kalshi_api.md: a held lock pays $1 even when a match never starts.
That's 3.9 % of recent ATP/WTA matches.

Historical cutoff (`GET /historical/cutoff`, market_settled_ts): 2026-08-25T00:00Z. Matches settled
before it come from `/historical/markets` + `/historical/markets/{t}/candlesticks`.
Milestones (scheduled start) cover start dates from ~Feb 2025 onward.

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
| 2026-10-24 10:39 → | Kalshi full backfill (relaunch loop) | all, by group | running | 1.0 s gap |
| 2026-10-24 10:43 | Kalshi `/live_data/batch` | 10 milestones | 1 | live fixture for score formats |

## The Odds API spends
None. No key, no budget yet.
