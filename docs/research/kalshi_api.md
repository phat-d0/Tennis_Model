# Kalshi Trade API: research notes for the tennis arb / swing-lock scanner

Researched 2026-10-24 from the official docs (fetched as Markdown via `https://docs.kalshi.com/<path>.md`;
index at `https://docs.kalshi.com/llms.txt`; OpenAPI spec version 3.34.0 is embedded in the reference pages)
and from live, unauthenticated calls to the production API (about 40 requests in total).
`D/` below means `https://docs.kalshi.com/`. "live API" means I called the endpoint myself on 2026-10-24.
Fixtures saved from those calls are in `tests/fixtures/kalshi/`.

Confidence tags: **[confirmed: url]** means I read it in an official doc or saw it in a live response.
**[unverified: ...]** means memory, a secondary source, or my own inference.

---

## Key facts for implementers

- **REST base (prod):** `https://external-api.kalshi.com/trade-api/v2` (recommended). `https://api.elections.kalshi.com/trade-api/v2` also works.
  **Demo:** `https://external-api.demo.kalshi.co/trade-api/v2` (or `https://demo-api.kalshi.co/trade-api/v2`). [confirmed: D/getting_started/api_environments]
- **WS (prod):** `wss://external-api-ws.kalshi.com/trade-api/ws/v2` (or `wss://api.elections.kalshi.com/trade-api/ws/v2`). **Every WS connection needs API-key auth at the handshake**, including connections that only use public channels. [confirmed: D/getting_started/quick_start_websockets]
- **No auth needed for REST market data:** series, events, markets, orderbook(s), trades, candlesticks, historical/*, milestones, live_data. [confirmed: D/getting_started/quick_start_market_data, D/getting_started/orderbook_responses; live API]
- **Units:** prices are dollar strings with up to 4 decimals (`*_dollars`, e.g. `"0.5400"`). Responses can emit up to 6 decimals. Counts are fixed-point strings with 2 decimals (`*_fp`, e.g. `"21.15"`), and **fractional counts are real and common** (minimum 0.01). Integer-cent fields are gone from the current schema. [confirmed: D/getting_started/fixed_point_migration; live API]
- **Tennis match = 1 event with 2 mutually exclusive binary markets, one per player.**
  Event: `KXATPMATCH-26OCT24FARBRU` (`collateral_return_type: "MECNET"`, `mutually_exclusive: true`).
  Markets: `KXATPMATCH-26OCT24FARBRU-FAR` (YES = Faria wins) and `...-BRU` (YES = Brunold wins). [confirmed: live API GET /events?series_ticker=KXATPMATCH&with_nested_markets=true]
- **Main match-winner series:** `KXATPMATCH`, `KXWTAMATCH` (fee_type `quadratic_with_maker_fees`, multiplier 1, maker fees since 2025-11-15). `KXATPCHALLENGERMATCH`, `KXWTACHALLENGERMATCH`, `KXITFMATCH`, `KXITFWMATCH` (fee_type `quadratic`, multiplier 1). [confirmed: live API GET /series?category=Sports&tags=Tennis, GET /series/fee_changes]
- **Orderbook returns bids only:** `orderbook_fp.yes_dollars` and `orderbook_fp.no_dollars` are lists of `[price_dollars, count_fp]`, sorted **ascending**, so the **best bid is the last element**.
  `yes_ask = 1 − best_no_bid`. `no_ask = 1 − best_yes_bid`. Ask size = size of that opposite bid. [confirmed: D/getting_started/orderbook_responses]
- **The effective ask for each side of a match combines both markets:**
  `ask(A) = min(1 − best_no_bid(mkt_A), 1 − best_yes_bid(mkt_B))` (buy YES on A, or buy NO on B).
  `ask(B)` is the same with A and B swapped. See §7. [inference from confirmed facts]
- **Taker fee:** `fee = round_up(M × 0.07 × C × P × (1−P))`. **Maker fee** (only for `quadratic_with_maker_fees`): `round_up(M × 0.0175 × C × P × (1−P))`. P is in dollars, C is the contract count, and M = series `fee_multiplier` (or the event override). [confirmed in part: the Series schema in D/api-reference/market/get-series-list says the maker multiplier is 0.25 of taker. Unverified: the 0.07 constant is quoted from the official PDF via search snippets, because the PDF and kalshi.com/fee-schedule sit behind a bot checkpoint]
- **Rounding (current mechanism):** the trade fee is rounded up to $0.000001. The balance change is then floored to the account's precision: **$0.0001 for direct members, $0.01 for non-direct (FCM) members**. A per-order accumulator rebates the overpayment. [confirmed: D/getting_started/fee_rounding]
- **Historical split:** anything that settled before `GET /historical/cutoff` → `market_settled_ts` (it was 2026-08-25T00:00Z on 2026-10-24) is **absent from `/markets` and `/series/.../candlesticks`**. Use `/historical/markets`, `/historical/markets/{ticker}/candlesticks` and `/historical/trades` for it. **Events stay on `/events` forever.** [confirmed: D/getting_started/historical_data; live API]
- **Live score exists:** `GET /milestones?related_event_ticker=<event>` → milestone `id`, then `GET /live_data/milestone/{id}` → set and game scores, server, winner and match_status. There is no historical score series. [confirmed: live API; D/api-reference/live-data/get-live-data]
- **Data Terms of Use restrict scraping, compiling databases, and any ML/AI use of the data.** See §8. **Read this before building the collector.**

---

## 1. Base URLs

| | REST | WebSocket |
|-|-|-|
| Prod | `https://external-api.kalshi.com/trade-api/v2` (alt `https://api.elections.kalshi.com/trade-api/v2`) | `wss://external-api-ws.kalshi.com/trade-api/ws/v2` (alt `wss://api.elections.kalshi.com/trade-api/ws/v2`) |
| Demo | `https://external-api.demo.kalshi.co/trade-api/v2` (alt `https://demo-api.kalshi.co/trade-api/v2`) | `wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2` (alt `wss://demo-api.kalshi.co/trade-api/ws/v2`) |

[confirmed: D/getting_started/api_environments]. Despite the "elections" name, the prod host serves all markets [confirmed: same page]. I tested only `api.elections.kalshi.com` live. Demo data is not real market data, so it is useless for backtesting.

## 2. Auth

- Public (no headers): all REST market-data GETs listed above. [confirmed: D/getting_started/quick_start_market_data, plus live calls without headers]
- Needs a key: portfolio, orders, `/account/*`, **and every WebSocket connection**. [confirmed: D/getting_started/quick_start_websockets]
- Headers: `KALSHI-ACCESS-KEY` (key ID), `KALSHI-ACCESS-TIMESTAMP` (ms since epoch, as a string), `KALSHI-ACCESS-SIGNATURE` (base64). [confirmed: D/getting_started/api_keys]
- Message to sign: `timestamp_ms + METHOD + path`. The path is the full path from the API root **without the query string** and without the host, e.g. `/trade-api/v2/portfolio/orders`. For WS, sign `GET` + `/trade-api/ws/v2`. [confirmed: D/getting_started/api_keys, D/getting_started/api_environments; the WS path comes from github.com/Kalshi/kalshi-starter-code-python clients.py]
- Key types: **Ed25519** (now recommended; signs the message directly) or **RSA-2048 with RSA-PSS**, SHA-256, MGF1(SHA-256) and salt length = digest length. [confirmed: D/getting_started/api_keys]
- The docs do not mention any **read-only key scope**. The project rule "no trading keys with write scope" may not be enforceable on Kalshi's side (open question).

## 3. REST endpoints that matter

Pagination: responses carry `cursor`. Pass it back as `?cursor=`. An empty string or null means done. [confirmed: D/getting_started/pagination; live]

### Series
- `GET /series?category=Sports&tags=Tennis` returns `{series:[...]}` (144 tennis series on 2026-10-24). Other params: `include_volume`, `include_product_metadata`, `min_updated_ts`. `GET /search/tags_by_categories` lists the tags, and `Sports` includes `Tennis`. [confirmed: D/api-reference/market/get-series-list; live]
- `GET /series/{ticker}` gives `ticker`, `title`, `category`, `tags`, `frequency`, **`fee_type`** (`quadratic` | `quadratic_with_maker_fees` | `quadratic_with_combo_maker_fees` | `flat`), **`fee_multiplier`** (float), `settlement_sources`, `contract_terms_url`, `product_metadata`, `volume_fp`, and `exchange_index` (tennis = 3). [confirmed: live API, fixture `series_KXATPMATCH_2026-10-24.json`]
- `GET /series/fee_changes?series_ticker=X&show_historical=true` returns scheduled and past fee changes. KXATPMATCH and KXWTAMATCH switched to `quadratic_with_maker_fees` at 2025-11-15T08:00Z. **For the backtest, apply maker fees only after that date.** [confirmed: live API]

### Events
- `GET /events` params: `series_ticker`, `status` (`unopened|open|closed|settled`), `with_nested_markets`, `with_milestones`, `min_close_ts`, `min_updated_ts`, `tickers` (comma-separated), `limit` (≤200), `cursor`. [confirmed: D/api-reference/events/get-events]
- Event fields: `event_ticker`, `series_ticker`, `title` ("Faria vs Brunold"), `sub_title` ("Faria vs Brunold (Oct 24)"), `collateral_return_type` (`MECNET`), `mutually_exclusive`, `product_metadata.competition` ("ATP Basel", "WTA 125K Rovereto", "ITF"), `fee_type_override`, `fee_multiplier_override` (overrides the series when non-null), and `markets[]` when nested. [confirmed: live API]
- Nested markets settled before the historical cutoff are left out of `with_nested_markets`, but the event itself is still returned. [confirmed: D/getting_started/historical_data]
- However, `GET /events/{event_ticker}` (single event) still returned both markets (top-level `markets` array) for `KXATPMATCH-26AUG24SONHER`, which settled before the cutoff ("ATP Winston Salem"). [observed live; not documented]

### Markets
- `GET /markets` params: `series_ticker`, `event_ticker` (only one), `tickers` (comma-separated), `status` (filter values `unopened|open|paused|closed|settled`), `min/max_close_ts`, `min/max_settled_ts`, `min/max_created_ts`, `min/max_updated_ts`, `mve_filter`, `limit` (≤1000, default 100), `cursor`. Only one status is allowed per call, and timestamp filters are mutually exclusive with some statuses (the table in the doc). [confirmed: D/api-reference/market/get-markets]
- The response `status` field uses different words from the filter: `initialized|active|inactive|closed|determined|disputed|amended|finalized`. Filter `open` = `active` and `settled` = `finalized`. [confirmed: D/getting_started/market_lifecycle]
- Fields we need (all strings unless noted):
  `ticker`, `event_ticker`, `market_type` (`binary`), `yes_sub_title` (player name), `title` (deprecated, "Jaime Faria wins"),
  `yes_bid_dollars`, `yes_ask_dollars`, `no_bid_dollars`, `no_ask_dollars`, `yes_bid_size_fp`, `yes_ask_size_fp`,
  `last_price_dollars`, `volume_fp`, `volume_24h_fp`, `open_interest_fp`, `previous_*_dollars` (one day ago),
  `open_time`, `close_time`, `expected_expiration_time`, `latest_expiration_time`, `occurrence_datetime`, `settlement_ts`,
  `result` (`yes|no|scalar|""`), `settlement_value_dollars`, `can_close_early`, `early_close_condition`,
  `strike_type` (`structured`), `custom_strike.tennis_competitor` (structured-target UUID),
  `price_level_structure`, `price_ranges[{start,end,step}]` (tennis = `linear_cent`, 1¢ tick), `rules_primary`, `rules_secondary`, `exchange_index`.
  [confirmed: D/api-reference/market/get-markets; live API]
- Note: `no_sub_title` holds the **same player name** as `yes_sub_title`, not the opponent's. NO on the FAR market means "Faria does not win". [confirmed: live API]
- For settled tennis markets, `close_time` is moved to roughly the moment the winner was declared (e.g. `2026-10-18T13:50:18Z`), so it is a usable proxy for match end. Open markets show a placeholder close about two weeks out. [confirmed: live API; D/getting_started/market_lifecycle says close_time can move earlier when `can_close_early`]

### Orderbook
- `GET /markets/{ticker}/orderbook?depth=N`. `depth` is 0 (all levels, the default) or 1–100. [confirmed: D/api-reference/market/get-market-orderbook]
- The response is `{"orderbook_fp": {"yes_dollars": [["0.5000","3924.11"], ..., ["0.5300","664.85"]], "no_dollars": [...]}}`, ascending, best bid last. `depth=10` returned the 10 best levels. [confirmed: D/getting_started/orderbook_responses; live, fixtures `orderbook_atp_faria_brunold_*`]
- `GET /markets/orderbooks?tickers=A&tickers=B` (repeat the param, up to 100) returns `{orderbooks:[{ticker, orderbook_fp}]}`. **Use this to snapshot both legs of a match in one request**, which also keeps the two legs closer in time. [confirmed: D/api-reference/market/get-multiple-market-orderbooks; live]
- Derivation: `yes_ask = 1 − no_dollars[-1][0]` with size `no_dollars[-1][1]`, and `no_ask = 1 − yes_dollars[-1][0]`. Walking deeper levels the same way gives ask-side depth. A key may be missing or empty when that side has no bids. [confirmed: D/getting_started/orderbook_responses]

### Trades (public tape)
- `GET /markets/trades` params: `ticker`, `min_ts`, `max_ts` (unix seconds), `is_block_trade`, `limit` (≤1000), `cursor`. Newest come first (observed). [confirmed: D/api-reference/market/get-trades; live]
- Fields: `trade_id`, `ticker`, `count_fp`, `yes_price_dollars`, `no_price_dollars` (= 1 − yes), `taker_outcome_side` (`yes|no`), `taker_book_side` (`bid|ask`), `taker_side` (deprecated), `created_time`, `is_block_trade`. `taker_outcome_side=no` means the taker bought NO at `no_price_dollars` (or sold YES). [confirmed: same; fixture `trades_atp_faria_brunold_FAR_2026-10-24.json`]
- A trade only shows that someone paid that price at that time. It does not prove the opposite leg was available at that moment.

### Candlesticks
- `GET /series/{series}/markets/{ticker}/candlesticks?start_ts&end_ts&period_interval` with `period_interval` ∈ {1, 60, 1440} minutes. Optional `include_latest_before_start`. [confirmed: D/api-reference/market/get-market-candlesticks]
- Candle fields: `end_period_ts` (period **end**, inclusive), `yes_bid{open,low,high,close}_dollars`, `yes_ask{...}_dollars`, `price{open,low,high,close,mean,previous,min,max}_dollars` (trade prices, null when there were no trades), `volume_fp`, `open_interest_fp`. **There are no `no_bid`/`no_ask` OHLC fields.** Derive them: `no_ask = 1 − yes_bid` and `no_bid = 1 − yes_ask`. [confirmed: same; fixture `candlesticks_1m_*`]
- Batch: `GET /markets/candlesticks?market_tickers=A,B&start_ts&end_ts&period_interval` takes up to 100 tickers and 10,000 candles total, and returns `{markets:[{market_ticker, candlesticks}]}`. [confirmed: D/api-reference/market/batch-get-market-candlesticks; live]
- **Historical candles use different field names.** `GET /historical/markets/{ticker}/candlesticks` (no series in the path) returns `yes_bid{open,low,high,close}`, `price{open,low,high,close,mean,previous}`, `volume` and `open_interest`, with no `_dollars` or `_fp` suffixes. The values are still dollar and count strings. The parser has to handle both shapes. [confirmed: D/api-reference/historical/get-historical-market-candlesticks; live, fixture `historical_candlesticks_*`]
- Backtest caveat: a 1-minute candle's `yes_ask.low` and the other market's `yes_ask.low` may come from different seconds. Only `close` vs `close` (both "at period end") is a defensible simultaneous quote. Even then, candles give **no size**. [inference]

### Historical (archive)
- `GET /historical/cutoff` returns `{market_settled_ts, trades_created_ts, orders_updated_ts, market_positions_last_updated_ts}` (RFC3339). On 2026-10-24 the market and trade cutoffs were `2026-08-25T00:00:00Z`, about two months back, and they move forward over time. [confirmed: D/getting_started/historical_data; live]
- `GET /historical/markets` (params `series_ticker`, `event_ticker`, `tickers`, `mve_filter`, `limit`, `cursor`) uses the same Market schema. `GET /historical/markets/{ticker}`. `GET /historical/trades` takes the same params as `/markets/trades` and the same Trade schema. All are public. [confirmed: D/api-reference/historical/*; live, fixtures `historical_markets_*`]
- Rule for the collector: for each event, use `/historical/*` when market `settlement_ts` < `market_settled_ts`, otherwise use the live endpoints. Trades split on `trades_created_ts`. [confirmed: D/getting_started/historical_data]

### Milestones and live data (tennis has them)
- `GET /milestones?related_event_ticker=KXATPMATCH-26OCT24FARBRU&limit=5` returns `type: "tennis_tournament_singles"`, `start_date` (scheduled start, e.g. 10:10Z), `details{tour, tournament_name, round, best_of, gender, first_competitor_id, second_competitor_id, main_game_event_ticker}`, `primary_event_tickers` (the match, set-winner and exact-score events), and `source_ids` (Sportradar `sr:sport_event:*`). Other filters: `category`, `competition`, `type`, `minimum_start_date`, `cursor`, `min_updated_ts`. The `limit` param is required. [confirmed: live API; D/api-reference/milestone/get-milestones]
- The milestone's `details.status` is **stale by design** (it still read `not_started` after the match ended). [confirmed: live; D/getting_started/targets_and_milestones]
- `GET /live_data/milestone/{id}` returns `live_data.details` with `match_status` (`ended`, ...), `status`, `winner` (competitor ID), `competitor{1,2}_round_scores[{score, tiebreak_score, outcome}]`, `competitor{1,2}_overall_score` (sets), `*_current_round_score`, `server`, `advantage`, `competitor*_statistics`, and seeds. It is a **current snapshot only**. To get a score timeline you must poll it yourself. It may be delayed (`live_data_delayed`). [confirmed: live API, fixture `live_data_*`; D/api-reference/live-data/get-live-data]
- `custom_strike.tennis_competitor` on each market equals a milestone competitor ID, which maps each market to player 1 or 2 and to the live-data scores. [confirmed: live API]
- Do not use `occurrence_datetime` / `expected_expiration_time` as the start time. They read 11:00Z when the milestone start was 10:10Z. Use milestone `start_date`. [confirmed: live]

## 4. WebSocket

- One authenticated connection. Send `{"id": 1, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"], "market_tickers": ["T1","T2"]}}`. Also available: `unsubscribe` and `update_subscription` (`add_markets`, `delete_markets`, `get_snapshot`). [confirmed: D/getting_started/quick_start_websockets, D/websockets/orderbook-updates]
- `orderbook_delta`: "Authentication required". You must give a market. The server first sends `orderbook_snapshot` (`msg.yes_dollars_fp` / `no_dollars_fp` as `[price, count_fp]`, keys absent when that side is empty, plus `clock`), then `orderbook_delta` (`msg.price_dollars`, `delta_fp` (signed), `side` yes|no, `clock`, `ts`/`ts_ms`). Check `seq` per subscription for gaps, and re-snapshot with `get_snapshot`. `clock` is the exchange clock and is comparable across connections for the same market. [confirmed: D/websockets/orderbook-updates]
- `ticker`: public within the authenticated session, market list optional. Fields: `yes_bid_dollars`, `yes_ask_dollars`, `yes_bid_size_fp`, `yes_ask_size_fp`, `price_dollars`, `volume_fp`, `open_interest_fp`, `last_trade_size_fp`, `ts_ms`. There is no no_bid/no_ask, but `no_ask = 1 − yes_bid`. [confirmed: D/websockets/market-ticker]
- `trade`: the same fields as a REST Trade, plus `ts_ms`. [confirmed: D/websockets/public-trades]
- Others: `market_lifecycle_v2` (open, close, determined, settled events) and private channels (`fill`, `market_positions`, ...). [confirmed: D/getting_started/quick_start_websockets]
- Implication: a **live scanner needs a Kalshi account and API key** for WS. Without a key, poll `GET /markets/orderbooks` (both legs in one call) within REST rate limits.

## 5. Rate limits

- Token buckets. Most requests cost 10 tokens, with non-default costs listed at `GET /account/endpoint_costs`. Read and Write buckets are separate. [confirmed: D/getting_started/rate_limits]
- Read budget in tokens/s, by tier: Basic 200 (≈20 req/s), Advanced 300, Expert 600, Premier 1,200, Paragon 2,400, Prime 4,800, Prestige 12,000. Basic and Advanced read buckets hold 3 s of budget (burst). Basic write is 100. Advanced is a free upgrade via the API endpoint. Higher tiers are earned by volume share. [confirmed: same]
- A 429 has no `Retry-After` header. Use exponential backoff. The doc shows the body `{"error":"too many requests"}`, but live I got `{"error":{"code":"too_many_requests","message":"too many requests"}}`. [confirmed: doc + live]
- **Unauthenticated limit: not documented.** In practice I hit 429 after about 8–10 back-to-back calls in roughly 2 s, twice. Budget about 2–5 req/s unauthenticated, or sign requests with a key to get the Basic tier (assuming signed public GETs count against the key's bucket; unverified). [observed live; unverified beyond that]

## 6. Fees

**Formula (general schedule):**
- Taker: `fee = round_up(M × 0.07 × C × P × (1 − P))`. M = series `fee_multiplier` (1 for all tennis series on 2026-10-24), C = contracts, P = price in dollars. [unverified-official: WebSearch shows the snippet "Fee Schedule for July 2026 - 7.7.26 Update" at kalshi.com/docs/kalshi-fee-schedule.pdf with this formula. Both that PDF and kalshi.com/fee-schedule return a Vercel bot-checkpoint 429 to curl, so I could not read them. Several secondary guides agree, e.g. quantvps.com/blog/kalshi-fees-explained]
- Maker (resting orders, charged only on fill, and only when `fee_type = quadratic_with_maker_fees`): `round_up(M × 0.0175 × C × P × (1 − P))`. 0.0175 = 0.25 × 0.07. [confirmed in part: the Series.fee_type description in D/api-reference/market/get-series-list says "'quadratic_with_combo_maker_fees' is the same maker-fee structure with a 0.5 maker multiplier instead of 0.25", and D/changelog (2026-08-22) says "maker fee uses a fee multiplier of 0.5, rather than the standard 0.25". The 0.0175 constant itself is unverified]
- `quadratic` series (Challenger, ITF, most others): no maker fee. [confirmed: Series schema text]
- `flat` = the "Specific Trading Fees Table" in the PDF. No tennis series uses it. [confirmed: schema text + live series list]
- Event-level override: `fee_type_override` / `fee_multiplier_override` on the event. Use them when non-null. History: `GET /events/{ticker}/fee_changes` (path unverified; see D/api-reference/events/get-event-fee-changes) and `/series/fee_changes`. [confirmed: D/api-reference/events/get-events]
- Market-level `fee_waiver_expiration_time` (nullable): some markets carry temporary fee waivers. [confirmed: Market schema]
- Grand Slam outright series (e.g. KXUSOMENSINGLES, KXWMENSINGLES, KXFOMEN) are `quadratic_with_maker_fees`. That matters only if we touch outrights. [confirmed: live]

**Rounding** [confirmed: D/getting_started/fee_rounding]:
1. `trade_fee = ceil_6dp(model_fee)`.
2. `aligned_change = floor_to_precision(revenue − trade_fee)`, where revenue is negative for buys and precision is **$0.0001 for direct members, $0.01 for non-direct (FCM-cleared)**.
3. `rounding_fee = (revenue − trade_fee) − aligned_change`. It accumulates **per order across fills (taker and maker)** and is rebated in precision-sized increments. Net fee is never below 0.
- For a direct Kalshi account, the effective cost is about `ceil_4dp(P×C + model_fee)`. For an FCM account, round to the cent. The old "round up to the next cent per order" rule is the conservative upper bound. **Recommendation:** make the precision configurable (0.01 default, as the conservative choice). [inference]
- Worked example: 100 contracts at $0.53 taker gives model fee 0.07×100×0.53×0.47 = $1.7437, so $1.75 at cent precision or $1.7437 at 4 dp. Per contract that is about 1.74¢. At P=0.5 it peaks at 1.75¢ per contract.
- Settlement fees: **zero for yes/no determinations** (they apply only to sub-cent scalar settlement). [confirmed: D/getting_started/market_settlement]

## 7. Tennis market structure and the arb math

**Series** (all `category=Sports`, tag `Tennis`, `exchange_index` 3) [confirmed: live API]:

| Series | Scope | fee_type / M |
|-|-|-|
| `KXATPMATCH` | ATP tour main draw + qualifying ("ATP Basel", "ATP Lyon") | quadratic_with_maker_fees / 1 |
| `KXWTAMATCH` | WTA tour ("WTA Guangzhou") | quadratic_with_maker_fees / 1 |
| `KXATPCHALLENGERMATCH` | ATP Challenger (active Oct 2026) | quadratic / 1 |
| `KXCHALLENGERMATCH` | older Challenger series, no events returned | quadratic / 1 |
| `KXWTACHALLENGERMATCH` | WTA 125 ("WTA 125K Rovereto") | quadratic / 1 |
| `KXITFMATCH`, `KXITFWMATCH` | ITF men/women (competition just "ITF") | quadratic / 1 |
| `KXDAVISCUPMATCH`, `KXUNITEDCUPMATCH`, `KXLAVERCUPMATCH`, `KXSIXKINGSMATCH`, `KXSIXKINGSSLAMMATCH`, `KXEXHIBITIONMEN/WOMEN`, `KXTENNISEXHIBITION`, `KXBATTLEOFSEXES` | team events / exhibitions | quadratic / 1 |
| `KXATPGAME`, `KXWTAGAME` ("ATP/WTA Tennis Winner") | legacy, no events returned | quadratic / 1 |

Grand Slam matches appear to be listed under KXATPMATCH/KXWTAMATCH with the slam as `competition`. Per-slam series (KXUSOMENSINGLES etc.) are tournament-winner outrights. [unverified: I did not fetch a slam-period match event]
Props in the same milestone: `KXATPSETWINNER`, `KXATPEXACTMATCH`, `KXATPGAMETOTAL`, `KXATPGAMESPREAD`, and others. Ignore them for match-winner arb.

**Tickers** [confirmed: live]: event `{SERIES}-{YYMONDD}{AAA}{BBB}`, e.g. `KXATPMATCH-26OCT24FARBRU`, where the date is the scheduled match date and the letters are the first three of each surname. Market = event + `-{AAA}`. Do not parse names from tickers. Use `yes_sub_title`, `custom_strike.tennis_competitor`, and the milestone competitor IDs. Tier and tournament come from the series plus `event.product_metadata.competition` and `milestone.details{tour, tournament_name, round, best_of}`.

**Structure:** one event, two markets, `mutually_exclusive: true` (MECNET). Each market is its own binary book: market A pays $1 on YES if A wins, and on NO if A does not win. **The two books are separate.** On 2026-10-24 Faria/Brunold showed:
- FAR: best YES bid .53, best NO bid .46 → YES ask .54, NO ask .47.
- BRU: best YES bid .47, best NO bid .52 → YES ask .48, NO ask .53.
[confirmed: live, fixtures]

**Four ways to hold one unit of each side.** Exactly one player wins, so each pair below pays exactly $1:
1. YES_A + YES_B: cost `(1−nobid_A) + (1−nobid_B)` = .54 + .48 = 1.02
2. NO_B + NO_A (NO_B is "A wins", NO_A is "B wins"): cost `(1−yesbid_B) + (1−yesbid_A)` = .53 + .47 = 1.00
3. YES_A + NO_A = `1 + spread_A` ≥ 1 (never an arb inside one book)
4. NO_B + YES_B = `1 + spread_B` ≥ 1
- So `ask(A) = min(1−nobid_A, 1−yesbid_B)` and `ask(B) = min(1−nobid_B, 1−yesbid_A)`. True arb: `ask(A)+ask(B)+fee(A)+fee(B) < 1`, with depth = the size at the chosen level of each leg. In the example the best is .53 + .47 = 1.00, which loses after fees.
- Fees: buying NO at price q has fee `0.07·C·q·(1−q)`, which is symmetric in q and 1−q. Price the fee on the price actually paid for each leg.
- Swing lock: holding A from YES_A at p1, the closing leg is `ask(B) = min(YES_B ask, NO_A ask)`. Buying NO_A on the same market you hold YES in **nets against your YES position** (it is equivalent to selling YES at 1 − NO_A ask = the YES_A bid). Either way the P&L is identical. [inference; netting is standard Kalshi behaviour, unverified in docs]
- MECNET collateral-return netting may free capital when holding YES on both legs (or NO on both). It does not change the P&L. [confirmed: event schema text; the effect on cash is unverified]

**Settlement edge cases** [confirmed: live `rules_secondary` and series `product_metadata.important_info`]:
- If the match never starts (no ball played: walkover, injury, cancellation), **both markets resolve to a "fair price"**, not 0/1. `settlement_value_dollars` can then be fractional. Whether the two fair prices sum to exactly $1 is **unverified**. Treat it as a small residual risk for locks.
- Retirement or forfeit after the first ball: the retiring player's market resolves **No** (the opponent's presumably Yes).
- Postponed matches stay open up to about two weeks (the placeholder `close_time`).

**Score/state:** see §3 Milestones. Live set and game scores are available from REST `live_data`, but only as a current snapshot. For the backtest, approximate match start from milestone `start_date` and match end from the settled market's `close_time`.

## 8. Terms of Use (data collection and storage)

- Using the API binds you to the **Developer Agreement** at `https://kalshi.com/developer-agreement`. [confirmed: D/welcome] **I could not read it** (bot checkpoint). One secondary source (github.com/Daatan/retro issue #937) says v1.1 is silent on data. [unverified]
- The **Kalshi Data Terms of Use** (`https://kalshi-public-docs.s3.amazonaws.com/kalshi-data-terms-of-service.pdf`, read in full) cover "Kalshi Data" (volume, bid-ask prices, settlement prices, open interest, and so on) on the Website. They say [confirmed: that PDF]:
  - Use is "personal use for non-commercial purposes" only. Non-commercial excludes, without written consent, (1) developing any software program, and (2) providing archived or cached datasets to others.
  - Prohibited without written authorization: "collecting, copying, reproducing, downloading … scraping, compiling (including … systematic retrieval to create collections, compilations, databases …)", text and data mining, and transferring content to any third person, "including … others in your company".
  - "You agree not to analyze, reverse-engineer … any Kalshi Data". Bots and scripts may not "copy in bulk, retrieve, harvest … or analyze" the Website.
  - **Any use of Kalshi Data "for any machine learning and/or artificial intelligence … or … in connection with the use of such technologies … to generate any … output is expressly prohibited."**
- Read literally, a personal backtest database built by scripts, and analysis done with an AI assistant, sit in tension with the Data ToU. The text says "Website", and the API terms are unknown. **The user should decide on this or get Kalshi's written consent.** Practical mitigations: keep the data private and local, don't redistribute datasets, commit only tiny fixtures (already the project rule), respect the rate limits, and never place orders. [inference]

## Open questions

1. Exact official fee-schedule text (the 0.07 / 0.0175 constants, the PDF's rounding wording, and any tennis-specific rows). Kalshi's site blocks non-browser fetches. The user should open https://kalshi.com/fee-schedule in a browser and confirm the KXATPMATCH and KXWTAMATCH rows.
2. Is the user a direct member ($0.0001 balance precision) or FCM-cleared ($0.01)? This decides the rounding model.
3. Unauthenticated REST rate limit (observed about 8 rapid calls before a 429). Does signing public GETs give Basic-tier (200 tokens/s) limits?
4. Do the fair-price settlements for not-started matches sum to $1 across both markets?
5. Developer Agreement content, and whether the Data ToU applies to API data for private, non-commercial backtesting and to AI-assisted analysis (see §8).
6. Is there a read-only API key scope? None is documented.
7. How far back do tennis match series go (when did KXATPMATCH start)? Paging `/historical/markets?series_ticker=KXATPMATCH` to the end will tell us. Do 1-minute historical candles exist for the oldest markets?
8. Are Grand Slam matches under KXATPMATCH/KXWTAMATCH? Check during the next slam, or in historical events from late Aug 2026 (US Open).
