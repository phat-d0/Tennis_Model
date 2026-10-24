# Role brief: Data

Every backtest number and every live alert depends on your data being right. Historical
candles show sampled ask levels but no depth, so the most valuable long-run asset is our
own recorded order book history. Start recording early. Branch: `team/data`. Read first:
`CLAUDE.md`, `docs/WORK_PLAN.md`, `docs/research/kalshi_api.md`, `swinglock/schema.py`,
and the fixtures in `tests/fixtures/kalshi/`.

## You own
- `swinglock/collectors/` (Kalshi client, normalizers, recorder; Polymarket later)
- `tests/test_collectors*.py`, `tests/fixtures/` (trimmed real responses, a few KB each)
- `docs/research/kalshi_api.md`, `docs/data_*.md`
- The data branch `data-store`, an orphan branch holding processed parquet only. Never merge it
  into `main`. Files stay under 50 MB each; split by month.
- Shared files (`schema.py`, `fees.py`, `config.yaml`): minimal changes only, flagged in
  the PR description. A schema change needs the Lead's OK first, because Backtest and Scanner read it.

## How your work is judged
- Normalizer tests run on real fixtures: for a settled match, `matches` has the right
  winner, players, series/tier and fee type; `quotes` asks/bids equal what the raw orderbook
  or candle says, including the YES-on-A vs NO-on-B resolution for the effective ask.
- No mid or last prices sneak into `ask`/`bid`. Missing sides stay NaN; nothing gets filled in.
- Pulls are resumable: re-running doesn't re-download what's already on disk.
- `docs/data_inventory.md` lists what's in `data-store` (date range, matches per tier,
  quote rows, sources, known gaps). Today's number to beat: 0 settled matches collected.

## Limits
- **You're the only role that bulk-pulls history.** Stay under half the Kalshi read
  rate limit (see `docs/research/kalshi_api.md`), with backoff on 429. Log each bulk pull
  (date, range, request count) in `docs/data_inventory.md`.
- Read-only endpoints only. No API key is needed for market data; if one is ever used,
  it's read-scope and never committed.
- DraftKings: no collection at all (its ToU forbids it). Polymarket: only after Kalshi is done.

## First tasks, in order of value
1. Kalshi REST client (`collectors/kalshi.py`): paging, throttle, retries, raw JSON cache
   under `data/raw/kalshi/`. Cover series → events → markets for the tennis match series in
   `config.yaml`, live and historical (mind the historical cutoff endpoint).
2. Normalizer: settled matches → `matches` + `quotes` (1-minute candles for history), with
   the A/B effective-ask resolution. Tests on the fixtures.
3. Backfill as far back as the API allows, then publish to `data-store` and tell the Lead,
   who passes it to Backtest.
4. Order-book recorder (`collectors/recorder.py`): poll or websocket the open tennis
   markets, append top-of-book plus depth snapshots to daily parquet. This needs a
   long-running process; see Open items in WORK_PLAN for where it will run.
5. Live score/state: check Kalshi's `live_data` / milestones endpoints (see fixtures) for set
   and game state, and join it onto quotes if usable.
6. Polymarket (intl + US) collectors for the cross-venue check.

Write up failures and dead ends too, so nobody repeats them.
