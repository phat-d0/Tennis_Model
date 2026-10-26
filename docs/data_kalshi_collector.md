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
- **Crossed candles:** a candle whose `yes_ask` close is below the same market's `yes_bid` close
  gets its ask set to NaN (the bid is kept). Found 2026-10-25 while reading the Challenger
  backfill: 84 of 13.8 M two-sided candles, all historical, in 5 markets
  (KXATPCHALLENGERMATCH-26MAY12POLSTR-STR 31, -26MAY12MONAND-AND 21, -26MAY13SAKMUL-SAK 19,
  -26MAY13VIRMPE-VIR 9, KXWTACHALLENGERMATCH-26MAY13ZAKBOU-ZAK 4), all on 2026-05-13 11:00–15:00 UTC.
  In each, the ask close sat frozen (e.g. 0.62) while the bid traded far above it on heavy volume.
  Those candles produced the largest "true arbs" in the read (up to 34¢ for 14 min), which were not real.
  Live (post-cutoff) candles had none.
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

## Order-book recorder (`recorder.py`)
```
python -m swinglock.collectors.recorder                  # until SIGTERM/SIGINT (docker: --profile recorder)
python -m swinglock.collectors.recorder --duration 300   # test run
```
- Discovery every 600 s: `GET /events?series_ticker=…&status=open&with_nested_markets=true&with_milestones=true`
  per series in `scanner.series` (scheduled start from the embedded milestones).
- Every `poll_s` (10 s): `GET /markets/orderbooks?tickers=…&depth=5`, 100 tickers (50 matches) per
  call, both legs of a match in the same call and stamped with the same receive time.
- One client throttle covers everything: `max_rps` (default 1.0). At 90 open matches that is
  2 calls per poll, ~0.2 req/s, plus 6 discovery calls per 10 min.
- Output under `data/recorded/kalshi/` (gitignored):
  - `quotes/`: the schema `quotes` table (source `orderbook`, with sizes), via `orderbooks_to_quotes`;
  - `depth/`: ts, match_id, ticker, book (yes|no bid list), level (0 = best), price, size; top 5
    per list. YES ask levels = 1 − NO bid levels;
  - `matches.parquet`: upserted on every flush.
  Each flush (60 s) writes `<table>/<day>/part-HHMMSS.parquet`; past days are compacted to
  `<table>/<day>.parquet`. `pd.read_parquet()` reads either.
- A failed poll writes no rows (no half quotes). A match missing a leg in the response is skipped.
- Settings come from config `recorder:` (`poll_s`, `discovery_s`, `flush_s`, `max_rps`, `depth`,
  `out_dir`) with the defaults above; CLI flags override.

Trial 2026-10-24 10:34 UTC (3 min, 15 s polls, 0.5 req/s cap, next to the running backfill):
- 90 open matches (ITF 39, ATP 22, WTA 21, Challenger 8); 11 snapshots; 30 requests; 2 × 429.
- 1,980 quote rows; 2.4 % NaN asks; 18,865 depth rows; 176 KB on disk.
- Combined ask(A)+ask(B) over 953 two-sided observations: min 0.99, median 1.01; 12 at 0.99
  (before fees, about 3.5¢ for a pair near 50/50, so not an arb), 101 at exactly 1.00.
- Disk estimate at 10 s polls and ~90 matches: on the order of 100 MB/day of part files before
  compaction. Check the compacted size on the VPS before publishing; day files may need splitting
  under the 50 MB `data-store` limit.

## Set-winner markets (`kalshi_sets.py`, 2026-10-26)
```
python -m swinglock.collectors.kalshi_sets --out data/processed/kalshi_g0   # writes sets.parquet
```
- Series: `KXATPSETWINNER`, `KXWTASETWINNER` (quadratic, mult 1). `GET /series?category=Sports` lists no
  Challenger, WTA 125 or ITF set series. (Related but not collected: KXATPANYSET, KXATPSETSWEEP,
  KXATPTOTALSETS, KXATPEXACTSETS.)
- One event per set, `KXATPSETWINNER-<match code>-<n>`, one market per player (`...-<n>-FAR`). The
  match is `KXATPMATCH-<match code>`. `close_time` = when the set ended; `result` yes/no, or `scalar`
  (fair price: not started, or not decidable after a retirement).
- **Kalshi only lists sets before the decider:** sets 1–2 in best-of-3 (never set 3) and sets 1–4 in
  best-of-5 (never set 5). Set 4 shows up only when the match reached a fourth set, and not always.
  The decider's winner is the match winner, and it ends at about the match market's close.
- Listings only: settled events (nested markets) + the series' `/historical/markets` for pre-cutoff
  events, cached like the backfill. Rows kept for match_ids in `<out>/matches.parquet`.
- Table `sets`: match_id, set_no, event_ticker, close_time, settlement_ts, winner_side (A/B via the
  player suffix vs the match's instrument tickers; NA unless decided), status (decided | fair_price |
  unsettled).
