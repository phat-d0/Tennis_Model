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

Groups 1–2 (8,339 recent Challenger + 48,825 others) started 16:21 UTC → `data/processed/kalshi_g12/`.

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
| 2026-10-24 10:39–15:46 | Kalshi backfill group 0 (relaunch loop, no relaunches needed) | ATP+WTA, Apr 24 → Oct 24 | ≈ 7,400 | ≈ 150 × 429 |
| 2026-10-24 15:47–16:20 | Kalshi group-0 re-normalize (`--groups 0`) | same | 477 | listings only; 80 × 429 |
| 2026-10-24 16:21 → | Kalshi backfill groups 1–2 (`--groups 1 2`) | Challenger, then rest | running | 1.0 s gap |

## The Odds API spends
None. No key, no budget yet.
