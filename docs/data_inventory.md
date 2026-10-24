# Data inventory

What's collected, where it lives, and every bulk pull / paid spend. Data role keeps this current.

## data-store branch
Nothing published yet (hold: repo must be confirmed private first, CLAUDE.md owner rule 4).

## Local (Data session container, `data/`, gitignored)
| Dataset | Status (2026-10-24) |
|---|---|
| Kalshi settled matches, 1-min candle quotes, all 6 match series | Backfill running; numbers below get filled in per series |

Settled match events listed on 2026-10-24 (all have both markets, live or `/historical/`):

| Series | Tier | Settled events |
|---|---|---|
| KXATPMATCH | atp | 5,029 |
| KXWTAMATCH | wta | 5,034 |
| KXATPCHALLENGERMATCH | challenger | 10,232 |
| KXWTACHALLENGERMATCH | challenger | 2,214 |
| KXITFMATCH / KXITFWMATCH | itf | (listing next) |

Historical cutoff (`GET /historical/cutoff`, market_settled_ts): 2026-08-25T00:00Z. Matches settled
before it come from `/historical/markets` + `/historical/markets/{t}/candlesticks`.
Milestones (scheduled start) cover start dates from ~Feb 2025 onward.

## Known gaps
- No order-book depth before the recorder runs; candle quotes have NaN sizes.
- Candle legs are carried forward between sparse candles (see docs/data_kalshi_collector.md).
- Fair-price (not-started) settlements have winner NA.

## Pull log
| Date (UTC) | Venue / endpoint | Range | Requests | Notes |
|---|---|---|---|---|
| 2026-10-24 09:15 | Kalshi listings + 3 ATP matches (trial) | 2026-10-23 | 178 | 0.5 s gap → 11 × 429, gap capped at 5 s |
| 2026-10-24 09:29 | Kalshi 80 ATP matches (trial) | Oct 2026 | 82 | 1.0 s gap, 0 × 429 |
| 2026-10-24 09:31 → | Kalshi full backfill, 6 series | all settled | running | 1.0 s gap; 16 × 429 in the first 3 min, none after |

## The Odds API spends
None. No key, no budget yet.
