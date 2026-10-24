# Kalshi collector: how it works, choices, dead ends

Data role, 2026-10-24. Code: `swinglock/collectors/{kalshi,kalshi_normalize,backfill}.py`,
tests: `tests/test_collectors_kalshi.py` (fixtures in `tests/fixtures/kalshi/`).

## Run it
```
python -m swinglock.collectors.backfill                       # all series in config.yaml
python -m swinglock.collectors.backfill --series KXATPMATCH --max-matches 20 --out data/processed/kalshi_trial
python -m swinglock.collectors.backfill --since 2026-09-01    # only matches closing after a date
```
Output: `data/processed/kalshi/matches.parquet`, `quotes.parquet` (schema.py contract), and one
JSON line per run in `data/processed/kalshi/backfill_runs.jsonl` (counts, requests, 429s).
Raw responses: `data/raw/kalshi/<endpoint path>/<sha1 of params>.json.gz`.

## Client (`kalshi.py`)
- Public REST only, no key, no order code. Base `https://external-api.kalshi.com/trade-api/v2`.
- Throttle: a minimum gap between requests (default 0.5 s; **the backfill runs at 1.0 s**).
  On 429: exponential backoff 2, 4, 8 … 60 s, and the gap widens ×1.5 (cap 5 s); after 50
  clean requests it eases back ÷1.25 toward the configured gap. Also retries 5xx and
  network errors; other non-200s raise `KalshiError`.
- Raw cache: every response is written gzipped (atomically). Same path + params → read from
  disk. Listings (events, historical markets, milestones) are re-fetched after 6 h; series
  meta after 24 h; candles of settled markets are cached forever. That's what makes the
  backfill resumable: a rerun only fetches what's missing.

## Backfill (`backfill.py`)
Per series: `GET /series/{s}` + `/series/fee_changes` → `GET /events?status=settled&with_nested_markets=true`
(200 per page). Events settled before `GET /historical/cutoff` come back **without** nested
markets, so the series' `/historical/markets` (1000 per page) is listed once and joined by
`event_ticker`. Then 1-minute candles, window = open_time − 60 s … close_time + 60 s:
- live markets: `GET /markets/candlesticks?market_tickers=A,B` (both legs, one call per 4,900 min);
- archived markets: `GET /historical/markets/{t}/candlesticks` per leg (same chunking).
Scheduled start: one bulk listing of `GET /milestones?type=tennis_tournament_singles`
(500 per page; ~63k milestones back to early 2025), mapped by `main_game_event_ticker`.

## Normalizer choices (`kalshi_normalize.py`)
- **Side A** = the player listed first in the event ticker (`…-26OCT23VANMUS` → VAN), which
  is also the title order ("Van Assche vs Musetti"). Fallback: ticker order.
- **Effective ask/bid** (CLAUDE.md data contract):
  `ask(A) = min(YES ask on A, 1 − YES bid on B)`, `bid(A) = max(YES bid on A, 1 − YES ask on B)`.
  `ask_source` = `yes:<A ticker>` or `no:<B ticker>`; on an exact tie both, `yes:…|no:…`
  (and for order books the sizes of both legs are summed, since both are fillable at that price).
- **Candles:** we use each period's `yes_bid.close` / `yes_ask.close` (quote at period end).
  Never the `price` block (trades), never mid. `ask_size`/`bid_size` are NaN (candles have no size).
  Both field shapes are parsed (`close_dollars` live, `close` historical).
- **Sparse candles:** Kalshi omits some minutes (VanMus: 786 candles over 1,745 minutes).
  Each leg's last close is carried forward to the other leg's candle times, **for at most
  `data.max_carry_s` (default 300 s)**; an older leg counts as missing (NaN), so a stale leg
  can't be paired with a fresh one. Nothing is filled before a leg's first candle. Rows are
  at the union of both legs' times. Whether a missing minute means "quote unchanged": see
  "Carry-forward check" below.
- **No quote → NaN.** A YES ask of 1.00 (no NO bids) or a YES bid of 0.00 (no YES bids)
  means that level doesn't exist; it becomes NaN, not a price.
- Candles ending more than one minute after the match's close_time are dropped.
- **Winner:** A/B when one market settled `yes` at $1 and the other `no`. A not-started match
  settled at a "fair price" (fractional `settlement_value_dollars`) gets winner NA.
- **Fee type:** event override if set; else the series' fee history at the match's open time
  (`/series/fee_changes`); before the first recorded change we assume `quadratic` (KXATP/KXWTAMATCH
  switched to `quadratic_with_maker_fees` on 2025-11-15). Maker fees only matter for resting orders.
- **Tier:** KXATPMATCH→atp, KXWTAMATCH→wta, KXATP/KXWTACHALLENGERMATCH→challenger (WTA 125
  counts as challenger), KXITF(W)MATCH→itf.
- `orderbooks_to_quotes()` builds the same two rows from a `GET /markets/orderbooks` snapshot,
  with sizes; the recorder (next task) will use it.

## Carry-forward check (2026-10-24)
Question (Lead): does Kalshi write a 1-min candle when only the quote moves (no trade)? If
candles only appeared on trade minutes, carrying a leg forward would pair stale quotes.

1. **Cached candles** (265 batch responses, 382,891 candles, live markets Aug–Oct 2026):
   250,383 candles have `volume_fp` 0, and **26,786 of those show a different yes_bid/yes_ask
   close than the previous candle**, so quote-only moves do produce candles. A further 9,060
   zero-volume candles have an intra-minute quote move that reverted by the close. 218,076 are
   zero-volume and fully flat. So candles are not trade-driven; flat ones appear too
   (presumably on size changes, which candles don't show).
2. **Live comparison:** KXATPMATCH-26OCT24BASTSI (ATP Basel, the busiest open match at
   09:50 UTC). Both legs' books were polled every 10 s for 12 min (72 snapshots), then
   that window's candles and `/markets/trades` were fetched (77 requests, 1 × 429).
   - The candles covered 14/15 and 15/15 minutes. 6 and 9 of those candle minutes had no trade.
   - Every minute in which a snapshot saw the top of book change had a candle (1 of 1).
   - The carried candle state (last close at or before the snapshot) matched the snapshot's
     best YES bid/ask in **140 of 144** cases. The 4 misses were one intra-minute move
     (YES bid .31 vs carried .32, 9–42 s into the minute) that the next candle picked up.
- **Answer:** candles are emitted on quote changes, not only on trades, and between candles the
  carried quote matched the live book. Limits: one match, 12 minutes, a quiet book (one top
  change). Within a minute the carried state lags by up to 60 s. The order-book recorder will
  give a much bigger sample. The 300 s cap bounds the damage if a gap hides a move.

## Known limits / caveats for Backtest
- Candle closes of the two legs are both "at period end", but within a minute they can still
  come from different seconds; and a carried-forward leg can be up to `max_carry_s` old (the
  as-of join's staleness rule doesn't see that, because each row is stamped at the union time).
  A tight combined price from candles is a lead to check, not a fill.
- Last minutes of a decided match show lopsided quotes (0.01 / NaN). Use phase and close_time.
- No depth anywhere in history. Depth starts with the order-book recorder.

## Dead ends / gotchas
- Unauthenticated rate limit: at a 0.5 s gap the listing phase got 11 × 429 in ~180 requests
  (the gap hit the 5 s cap and, in v1 of the client, never came back down: 178 requests took
  13 minutes). At a 1.0 s gap: 0 × 429 in the first 82 requests. Hence 1.0 s for the backfill.
- `/milestones` without a date filter pages back to Feb 2025 (126 pages × 500); fine once, cached.
- `limit` is required on `/milestones` (max 500).
