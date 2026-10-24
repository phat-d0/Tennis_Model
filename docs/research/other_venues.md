# Secondary venues: DraftKings Predictions and Polymarket

Researched 2026-10-24 (around 08:50 UTC). Main venue (Kalshi) is covered separately.

Tags:
- `[confirmed: <url>]` means checked against an official doc or legal page, or against a live public API response from that URL on 2026-10-24.
- `[unverified: secondary]` means the fact comes from a third-party article or a search-engine summary.
- `[unverified: memory]` means it comes from prior knowledge only.

Method notes:
- WebFetch failed with DNS errors for every domain, so docs.polymarket.com, docs.polymarket.us and cftc.gov pages were seen only through WebSearch summaries. Facts that rest on those summaries are tagged `[confirmed (search summary): <url>]`. They should be re-read on the live page before going into code.
- After the policy change, direct curl to `gamma-api.polymarket.com`, `clob.polymarket.com`, `data-api.polymarket.com` and `gateway.polymarket.us` worked. About 25 light requests were made. Facts marked `[confirmed: live API]` come from those responses.
- DraftKings: I made no market-data requests. I downloaded only legal and fee documents from `myaccount.draftkings.com` and `www.draftkings.com`.

Fixtures saved (trimmed, about 7 KB and 2 KB):
- `tests/fixtures/polymarket/gamma_event_tennis_atp_paul_fritz_2026-10-24.json`: Gamma event with its moneyline market.
- `tests/fixtures/polymarket/clob_book_tennis_atp_paul_fritz_2026-10-24.json`: CLOB `/book`, top 6 levels per side in original order, plus a `/prices-history` sample.

---

## Bottom line

### DraftKings Predictions
- **No sanctioned programmatic access.** There is no public or partner market-data API or developer documentation for DraftKings Predictions. The Predictions Terms of Use expressly prohibit "bots, scripts, artificial intelligence, programs, parsers, spiders, screen scrapers, or tools … to collect any information or content". They also restrict use to "personal, non-commercial" purposes. [confirmed: https://myaccount.draftkings.com/documents/predictions-terms-of-use?product=predict]
- Fallback: log prices by hand from the app. Scraping is not recommended.
- Brokerage structure: DraftKings Predictions (Gus III LLC) is a CFTC-registered FCM and NFA member. It routes orders to third-party exchanges (DCMs): CME, Crypto.com/CDNA (North American Derivatives Exchange, Inc.), its own DKeX (Railbird Exchange, LLC), and Bitnomial. Clearing goes through Wedbush. [confirmed: same URL]
- Tennis is listed: there is a "Tennis" topic covering ATP, WTA and Challenger events. [unverified: secondary, search result for https://predictions.draftkings.com/en/topic/tennis]
- Fees are a per-contract schedule, roughly $0.02 per contract at prices from $0.30 to $0.94 (table below). [confirmed: https://myaccount.draftkings.com/documents/fee-disclosure?product=predict]

### Polymarket (international, polymarket.com)
- **Full public read-only market data:**
  - Gamma (discovery), CLOB (`/book`, `/books`, `/price`, `/midpoint`, `/prices-history`) and the Data API (trades) need no key. [confirmed: live API]
  - The websocket market channel is public too. [confirmed (search summary): https://docs.polymarket.com/market-data/websocket/market-channel]
- **US persons may not trade on it.** polymarket.com blocks trading from the US and sends US users to polymarket.us. [confirmed (search summary): https://polymarket.com/trust]
  - So a Kalshi↔Polymarket-international arbitrage can't be acted on by a US user. Treat it as a pricing signal only.
- **Sports taker fees are on:**
  - Formula: `fee = C × 0.05 × p × (1−p)`, charged to takers only.
  - The live tennis markets show `feeSchedule: {"rate":0.05,"exponent":1,"takerOnly":true,"rebateRate":0.15}`.
  - That is about $1.25 per 100 shares at p=0.50. [confirmed: live API; formula confirmed (search summary): https://docs.polymarket.com/trading/fees]
- **Tennis match-winner structure:**
  - Each match is one market (`sportsMarketType: "moneyline"`) with two outcome tokens named after the players.
  - `negRisk: false`.
  - Each event has up to about 17 sibling markets (set and game handicaps, totals and so on). [confirmed: live API]
- **History is price-only.** `/prices-history` returns `{t, p}` points only, with no bid, ask or size. Historical order books are not available from the official API. For a realistic backtest you must record books yourself. [confirmed: live API]

### Polymarket US (polymarket.us, QCX LLC, a CFTC DCM)
- **The venue a US user can actually trade.**
  - It is a separate CFTC-regulated DCM. [confirmed (search summary): https://polymarket.com/trust]
  - It lists the same tennis matches. Example: `aec-atp-tompau-tayfri-2026-10-24`, Paul vs Fritz. [confirmed: live API, https://gateway.polymarket.us/v1/search?query=Fritz]
- **Own API:**
  - Public REST at `https://gateway.polymarket.us` needs no key and covers markets, `/book` and `/bbo`. [confirmed: live API]
  - The websocket `wss://api.polymarket.us/v1/ws/markets` requires a signed API key. [confirmed (search summary): https://docs.polymarket.us/api-reference/websocket/markets]
- **Fees:**
  - Formula: `Θ × C × p × (1−p)`, with taker Θ = 0.0695. The live market shows `feeCoefficient: 0.0695`. That is about $1.74 per 100 contracts at $0.50.
  - Table tennis uses Θ = 0.10. This is not the same as tennis.
  - Tiered maker rebates began 2026-10-19.
  - [confirmed: live API; schedule (search summary): https://docs.polymarket.us/fees, https://docs.polymarket.us/changelog]
- **State restrictions:** some states are excluded. Secondary sources list AZ, IL, MA, MD, MI, MT, NJ, NV and OH, and they disagree with each other. [unverified: secondary, e.g. https://www.squawka.com/us/bet/betting-sites/polymarket/]
- **Settlement rules differ from Polymarket international and possibly from Kalshi** (walkover, retirement). Check before treating markets as the same (details in B6).

---

## Part A: DraftKings Predictions

### A1. Corporate and exchange structure
- **Operator:** "Gus III LLC d/b/a DraftKings Predictions". [confirmed: https://www.draftkings.com/predictions-terms]
- **Registration:** the site footer says "Event Contract Trading is offered by DraftKings Predictions, a CFTC-registered Futures Commission Merchant and NFA member". [confirmed: https://myaccount.draftkings.com/documents/fee-disclosure?product=predict]
- **Exchanges, from the ToU:** orders go to "one or more Designated Contract Markets ('DCMs') and Derivatives Clearing Organizations ('DCOs') … including, without limitation, Chicago Mercantile Exchange Inc. … North American Derivatives Exchange, Inc. (… 'Crypto.com'), Railbird Exchange, LLC ('DKeX'), Bitnomial Clearinghouse, LLC …". [confirmed: https://myaccount.draftkings.com/documents/predictions-terms-of-use?product=predict, last updated 2026-08-04]
- **Clearing FCM:** the ToU names Wedbush: "Such funds will subsequently be transferred to Wedbush, or another registered clearing FCM". Users also agree to be bound by the DKeX Rulebook. [confirmed: same URL]
- **History:**
  - DraftKings agreed to buy Railbird in Oct 2025. [unverified: secondary, https://sbcamericas.com/2025/10/21/draftkins-railbird-prediction-market/]
  - DKeX self-certified sports contract templates in May 2026: GAMEWIN, GAMESPREAD, ENTITYSTAT, ENTITYOUTPERFORM, ENTITYACHIEVEMENT and GAMEPROPERTY. [unverified: secondary, https://defirate.com/news/draftkings-railbird-exchange-files-first-sports-prediction-market-contracts/]
  - DKeX reportedly went live around 2026-06-26. [unverified: secondary, https://bettorsinsider.com/news/2026/06/28/draftkings-launches-dkex-its-own-prediction-markets-exchange-built-on-railbird-technology/]
  - The CDNA (Crypto.com) listing deal was announced in Feb 2026. [unverified: secondary, https://draftkings.gcs-web.com/news-releases/news-release-details/draftkings-expands-prediction-markets-catalog-deal-cryptocom]
- **Which exchange lists tennis is unknown.** It may be CDNA or DKeX. Market rules in the app name the source exchange; the fee page says "Market source information is available in the applicable market rules link". [confirmed: fee-disclosure URL above]

### A2. Tennis markets
- A tennis topic page exists, with ATP, WTA, ATP Quals and Challenger groupings, shown as American-odds head-to-head prices. Example: "F. Tiafoe -223 / A. Pellegrino +203". [unverified: secondary, search snippets of https://predictions.draftkings.com/en/topic/tennis]
- Market tickers look like `DKP3-SPWTAGLMLX…`. [unverified: secondary, search result URL]
- I did not check whether set, game or prop markets exist. The page returns 403 to curl, and I did not try further.

### A3. API and developer docs
- I found no official API or developer portal for Predictions on DraftKings domains, in DraftKings press materials, or in search results.
- The third-party results (Apify actors, odds aggregators) are unofficial scrapers. [unverified: secondary, e.g. https://apify.com/hypebridge/draftkings-predictions/api]
- The ToU contain no API grant. The word "API" does not appear anywhere in the 123k-character document. [confirmed: ToU URL above]
- Underlying exchanges: I found no public market-data API for DKeX or CDNA. The DKeX rulebook was not reviewed for market-data provisions. [unverified]

### A4. Terms of Use: automated access, data use
Source: DraftKings Predictions Terms of Use, last updated August 4, 2026. [confirmed: https://myaccount.draftkings.com/documents/predictions-terms-of-use?product=predict]

- **Prohibited conduct.** Under "A violation of the Agreements includes, without limitation:":
  > "Using, or allowing any other person or entity to use, any unauthorized automated means, automated computerized software, or equivalent mechanisms, including, without limitation, bots, scripts, artificial intelligence, programs, parsers, spiders, screen scrapers, or tools, to interact with the DraftKings Predictions App or the Services, including, without limitation, to collect any information or content from the Services or the DraftKings Predictions App or to automatically execute Commodity Transactions or use the Services in any similar manner;"
  > "Accessing or using your DraftKings Predictions Account or the Services in any manner other than for your own personal, non-commercial benefit;"
- **License scope:**
  > "…a limited, non-transferable, fully revocable, non-sublicensable, non-exclusive right … for your personal, non-commercial use only, and … may not be used, copied, reproduced, distributed, transmitted, broadcast, displayed, sold, licensed, or otherwise exploited for any other purposes whatsoever without the prior written consent of DraftKings Predictions…"
  > "You will not decompile, reverse engineer, modify, create derivatives of, disassemble, or attempt to access the source code of … the DraftKings Predictions App, the Services…"
- **Market data disclaimer:**
  > "…neither DraftKings Predictions nor any DraftKings Released Parties make any representations, warranties, or other guarantees as to the accuracy or timeliness of any market data…"
- **The sportsbook and DFS terms do not apply to Predictions.** The DFS ToU say they do not govern "DraftKings Predictions" [confirmed: https://myaccount.draftkings.com/documents/us-terms-of-use]. The governing document is the Predictions ToU above.
- **Possible reading of "unauthorized":** the word may imply that an authorized automated channel could exist with "prior written consent". No such program is published. [inference]

### A5. Fees
DraftKings Predictions Standard Pricing Fee Schedule. [confirmed: https://myaccount.draftkings.com/documents/fee-disclosure?product=predict]

**CDNA and DKeX markets: fee per contract by contract price**
- The fee rises from $0.0000804 at $0.001–0.002 to $0.0183720 at $0.27–0.29.
- It is a flat **$0.0200000 for $0.30–$0.94**.
- It then falls: $0.0105 at $0.941–0.968, $0.0045 at $0.969–0.991, and $0.0005 at $0.992–0.999.
- Total fee = fee per contract × contracts.
- Rounding:
  > "The fee is always rounded up to bring the total of collateral and fees to a whole cent, rounding the transaction up on a purchase and down on a sale … All rounding will never exceed one cent per transaction."

**CME markets: all-in fee per contract**
- $0.01 at $0.01–0.19.
- $0.02 at $0.20–0.94.
- $0.01 at $0.95–0.99.

**Promo terms version**
- An older promo-terms page (period 3/3/26–4/6/26) says a "$0.01 transaction fee for each event contract bought or sold" plus "a separate exchange fee". Treat the fee-disclosure page as the current schedule. [confirmed: https://www.draftkings.com/predictions-terms]

**State availability**
- Eligible states are listed at `https://predictions.draftkings.com/en/how-to-trade-predictions-availability` [confirmed link: promo terms page]. That page returned 403 to curl, so its contents were not read.

---

## Part B: Polymarket (international)

### B1. Gamma API (discovery)
- **Base URL:** `https://gamma-api.polymarket.com`. No auth needed. [confirmed: live API]
- **Tennis tag:** `GET /tags/slug/tennis` returns `{"id":"864","label":"Tennis","slug":"tennis"}`. [confirmed: live API]
- **League tags,** from `GET /sports` (`id / sport / tags / series`) [confirmed: live API]:
  - ATP Tour `atp`: tags `1,864,100639,101232`, series `10365`
  - WTA Tour `wta`: tags `…,102123`, series `10366`
  - ITF `itf`: tags `…,104923`, series `11634`
  - `atp-doubles` (series 11632) and `wta-doubles` (11633)
  - ATP Challengers appear under the `atp` series. Example: "Florence: Forti vs Roca Batalla", `seriesSlug: atp`.
- **Working query:** `GET /events?tag_id=864&closed=false&limit=50&order=volume24hr&ascending=false`. [confirmed: live API]
  - The docs also describe `/events/keyset` and `/markets/keyset` with `after_cursor` pagination.
  - On the keyset endpoints, `tag_id` is an array.
  - Markets with only a `tag_id` and `closed=any` return 422.
  - [confirmed (search summary): https://docs.polymarket.com/api-reference/events/list-events-keyset-pagination]
- **Event fields useful for matching** [confirmed: live API]:
  - `title` ("Lyon Open: Tommy Paul vs Taylor Fritz")
  - `slug`/`ticker` (`atp-paul-fritz-2026-10-24`)
  - `startTime` (UTC)
  - `eventDate`
  - `seriesSlug`
  - `teams[]` with `name`, `alias` ("L. Fernandez"), `abbreviation`, `ordering` (home/away) and `providerId`
  - `eventMetadata.league` (tournament name) and `eventMetadata.opticOddsFixtureId`
  - `restricted: true`
- **Market fields** [confirmed: live API]:
  - `sportsMarketType` (`moneyline`, `tennis_set_handicap`, `tennis_match_totals`, `tennis_first_set_winner`, `tennis_completed_match`, …)
  - `outcomes` (JSON string of player names)
  - `clobTokenIds` (JSON string, same order as outcomes)
  - `conditionId`, `gameStartTime`
  - `bestBid`/`bestAsk` (outcome[0] only)
  - `orderPriceMinTickSize` (0.01), `orderMinSize` (5)
  - `feesEnabled`, `feeSchedule`, `negRisk`

### B2. CLOB API (prices and books)
- **Base URL:** `https://clob.polymarket.com`. Reads need no auth; only order placement needs L1/L2 auth. [confirmed: live API]
- **`GET /book?token_id=<token>`** [confirmed: live API]
  - Returns `market` (conditionId), `asset_id`, `timestamp` (ms), `hash`, `bids`, `asks`, `min_order_size`, `tick_size`, `neg_risk` and `last_trade_price`.
  - **Ordering gotcha:** bids come sorted ascending, so the best bid is the LAST element. Asks come sorted descending, so the best ask is also the LAST element. Compute the best price with max/min, not `[0]`.
  - Prices and sizes are strings.
- **`POST /books`** with body `[{"token_id":...}, ...]` returns a list of books. [confirmed: live API]
- **`GET /price?token_id=&side=`**: in testing, `side=BUY` returned 0.37 (the best bid) and `side=SELL` returned 0.38 (the best ask). [confirmed: live API]
  - So the price to pay to buy is `side=SELL` (you lift resting sell orders). The naming is easy to get backwards. Prefer `/book`.
  - `GET /midpoint` returns `{"mid":"0.375"}`. `GET /tick-size` returns `{"minimum_tick_size":0.01}`.
  - `GET /fee-rate?token_id=` returns `{"base_fee":1000}`, a legacy-looking number that does not match the 0.05 rate. Use Gamma `feeSchedule` for fee math. [confirmed: live API; meaning unverified]
- **`GET /prices-history`** [confirmed: live API]
  - Example: `?market=<token_id>&interval=1d&fidelity=5` returned `{"history":[{"t":<unix s>,"p":<float>}, ...]}`, 167 points spaced about 5 minutes apart.
  - `p` tracked the midpoint (0.375 while the book was 0.37/0.38).
- **`/prices-history` parameters** [confirmed (search summary): https://docs.polymarket.com/api-reference/markets/get-prices-history]:
  - `market` is a token id.
  - `interval` takes `1m/1h/6h/1d/1w/max/all`, relative to now.
  - `startTs`/`endTs` take unix seconds and cannot be combined with `interval`.
  - `fidelity` is in minutes.
  - The docs also describe `POST /batch-prices-history` (up to 20 tokens).
- **Data API v2 price history:** `GET https://data-api.polymarket.com/v2/prices-history?token_id=&start=&end=&bucket_seconds=300` returned `{"data":[{"timestamp","price","resolution_seconds"}]}`. [confirmed: live API]
  - Documented limits: explicit windows max 15 days; full-history queries default to 12h buckets; finer buckets only cover the last 30 days.
  - Retention floors: 1m data at least 7 days, 5m at least 60 days, 30m at least 90 days.
  - [confirmed (search summary): https://docs.polymarket.com/changelog/sdks, https://docs.polymarket.com/api-reference/markets/get-prices-history]

### B3. Data API (trades)
- `GET https://data-api.polymarket.com/trades?market=<conditionId>&limit=N` (v1) returns fills with these fields [confirmed: live API]:
  - `side`, `asset`, `outcome`, `outcomeIndex`, `size`, `price`, `timestamp` (s), `transactionHash`
  - plus user wallet and pseudonym (personal data; don't store it).
- `GET /v2/trades?condition=<conditionId>` returns snake_case fields under `data`. The v2 API rejects `market=` with a helpful error. [confirmed: live API]
- Trades give the last traded price, not quotes. They can show where fills actually happened, not the quoted ask over time.

### B4. Websocket market channel
- **URL:** `wss://ws-subscriptions-clob.polymarket.com/ws/market`. Public. [confirmed (search summary): https://docs.polymarket.com/market-data/websocket/market-channel]
- **Subscribe:** `{"assets_ids":["<token>",...],"type":"market"}`.
  - Optional `"custom_feature_enabled": true` adds `best_bid_ask`, `new_market` and `market_resolved` events.
  - To change subscriptions on an open socket, send `{"assets_ids":[...],"operation":"subscribe"|"unsubscribe"}`.
  - Send a text `PING` every 10 s; the server replies `PONG`.
  - [confirmed (search summary): same URL]
- I did not test the websocket.

### B5. Rate limits
Source: [confirmed (search summary): https://docs.polymarket.com/api-reference/rate-limits]
- Limits are per IP via Cloudflare, over sliding windows.
- When over a limit, requests are throttled (queued) rather than rejected. 429 is possible; back off exponentially.
- **CLOB:** 15,000 req/10 s general; `/book` 1,500; `/books` 500; `/price` and `/midpoint` 1,500 each.
- **Gamma:** 4,000/10 s general; `/events` 500; `/markets` 300.
- **Data API:** v1 1,000/10 s; `/trades` 200. v2 800; `/v2/trades` 300.

### B6. Tennis market structure, rules, and matching to Kalshi
**Structure** [confirmed: live API]
- One event per match. The match-winner market is `sportsMarketType: "moneyline"`, a binary CTF market with two tokens, one per player.
- `negRisk: false`.
- Buying player A's token is the same as buying "A wins". Player B's token is the complement. Its ask is about 1 − (A's best bid) only approximately, because each token has its own book.

**Polymarket international resolution text, quoted from the live market** [confirmed: live API, Paul–Fritz moneyline `description`]
- Retirement, default or DQ after the match starts → "resolve to the player who advances".
- Walkover → "resolve to 50-50".
- Cancelled, a tie, or no winner within 14 days → 50-50.

**Polymarket US resolution text** [confirmed: live API, gateway search]
- Walkover, withdrawal or cancellation → "settle to the last fair market price".
- Retirement or DQ → official winner.
- Rescheduled by more than 2 days → last fair market price.
- **These rules differ from the international venue. Compare both with Kalshi's tennis rules before treating markets as equivalent.**

**Start-time pitfall** [confirmed: live API]
- The international market's description said "originally scheduled for October 24, 2026 at 4:00AM ET".
- `startTime`/`gameStartTime` said 12:00 UTC, which is 8:00 AM ET. Polymarket US's text also said 8:00AM ET.
- Use the structured `gameStartTime`, not the prose, and allow some tolerance when matching.

**Suggested matching keys to a Kalshi match**
1. Normalized player surname pair, order-insensitive. Use `teams[].name` and `alias` plus `outcomes`.
2. Match date or start time within about ±12 h.
3. Tour, from `seriesSlug`/`sport` (atp/wta/itf).
4. Tournament, from `eventMetadata.league`, as a tie-breaker.

Slugs use abbreviated surnames: international `atp-paul-fritz-2026-10-24`, US `aec-atp-tompau-tayfri-2026-10-24`. They are not reliable for cross-venue matching. The slug date may be the local or ET date (`itf-…-2026-10-25` events start on 10-24 UTC). [confirmed: live API]

### B7. Fees (international)
- **Formula:** taker `fee = C × feeRate × p × (1 − p)`.
  - Makers pay no fee and get a rebate (sports 15% of taker fees).
  - Fees are in collateral (USDC/pUSD), rounded to 5 decimals.
  - [confirmed (search summary): https://docs.polymarket.com/trading/fees, https://docs.polymarket.com/programs/maker-rebates]
- **Sports rate:** 0.05. Raised from 0.03; the changelog dates it July 2026. [confirmed (search summary): https://docs.polymarket.com/changelog]
  - Every tennis market inspected shows `feeSchedule.rate = 0.05`, `takerOnly: true`, `rebateRate: 0.15`. [confirmed: live API]
- **Effective cost of buying at ask a:** `a + 0.05·a·(1−a)` per share. At a = 0.38 the fee is about 0.0118 per share.
- Note: Gamma `takerBaseFee`/`makerBaseFee` = 1000 is a legacy field. Read `feeSchedule` instead. [inference]

### B8. Geo and eligibility
- polymarket.com: "trading is blocked in the United States". US users are directed to polymarket.us.
- The Trust & Safety Hub says users in restricted jurisdictions, including the US, may not trade on Polymarket International "or use tools intended to circumvent geographic restrictions".
- [confirmed (search summary): https://polymarket.com/trust]
- Read-only API access from the US worked in testing. Reading data is not trading eligibility.
- **Implication:** a US user cannot act on an arbitrage involving Polymarket international. Polymarket US is the actionable leg.

### B9. Polymarket US API
- **Public REST:** `https://gateway.polymarket.us`, no key. [confirmed: live API]
  - `GET /v1/sports` lists operational leagues including `atp`, `wta`, `atpcq`, `itfm`, `itfw`, `atpdb`, `wtadb`, `daviscup`, `bjkcup` and `utr`.
  - `GET /v1/search?query=Fritz` returns events with markets.
  - `GET /v1/markets?active=true&closed=false&limit=200&categories=sports` works, but the first page was all MLB and MLS. Use search, offset pagination or the sports endpoints.
  - `GET /v1/sports/{slug}/events` returned 400 for `atp`. I did not resolve the right parameters.
- **US market shape** [confirmed: live API]:
  - A single instrument, with `marketSides` long = player A and short = player B.
  - `sportsMarketType: "tennis_match_winner"`, `marketType: "moneyline"`.
  - `orderPriceMinTickSize` 0.01, `minimumTradeQty` 0.01, `feeCoefficient` 0.0695.
- **`GET /v1/markets/{slug}/book`** returns `marketData.bids` and `marketData.offers` as `{px:{value,currency},qty}`, best-first. [confirmed: live API]
- **`GET /v1/markets/{slug}/bbo`** returns `bestBid`, `bestAsk`, `lastTradePx`, `currentPx`, `openInterest`, `sharesTraded`, `state` and `longQuote`/`shortQuote`. [confirmed: live API]
- **`/v1/price-history`** is documented, but my guessed params returned 400. [confirmed (search summary): https://docs.polymarket.us/api-reference/market/overview]
- **Websocket:** `wss://api.polymarket.us/v1/ws/markets` requires `X-PM-*` signed headers (access key, ms timestamp, signature over timestamp+"GET"+path). Timestamp must be within 30 s. [confirmed (search summary): https://docs.polymarket.us/api-reference/authentication]
  - Public REST is said to be limited to about 20 req/s per IP. That figure came from the institutional docs and may not apply. [unverified: search summary]
- **Fees:**
  - Taker Θ = 0.0695: $1.74 per 100 contracts at $0.50.
  - Table tennis Θ = 0.10.
  - Maker rebates from 2026-10-19: Tier 1 0, Tier 2 −0.0035, Tier 3 −0.0070, Tier 4 −0.0104, by prior-month maker volume.
  - [confirmed (search summary): https://docs.polymarket.us/fees, https://docs.polymarket.us/changelog; Θ confirmed: live API]
  - Older reports of 0.01% or 0.30% premium-based fees are superseded. [unverified: secondary]
- **Observation:** at about 08:52 UTC the US and international best bid/ask for Paul were identical (0.37/0.38), with different sizes. The two venues may be linked by market makers. The size of any arbitrage between them may be small. [confirmed: live API, a single snapshot]

### B10. Historical data limitation for backtesting
- The official APIs give only single price points: CLOB `/prices-history` and Data API v2, which match the mid or last price, plus trades.
- No endpoint returns historical order book snapshots or bid/ask series. [confirmed: live API responses; no such endpoint found in docs]
- **Implication:** any backtest that fills at the ask can't use Polymarket history directly.
  - Options: start recording `/book` (or websocket `book`/`price_change`/`best_bid_ask`) snapshots now, or model the half-spread from recorded data.
  - Never fill at `p` from prices-history.
  - Fine-grained history retention is limited (B2), so record ahead of time.

---

## Open questions
1. DraftKings: which exchange (DKeX, CDNA or CME) lists each tennis market? Only the per-market rules in the app show this, and it decides which fee row applies.
2. DraftKings: would DraftKings Predictions or DKeX grant written consent or a data license? No program is published. The user could email support@draftkings.com. [contact confirmed: https://www.draftkings.com/predictions-terms]
3. Is DKeX or CDNA market data distributed publicly anywhere, such as exchange-published settlement or price files? The DKeX rulebook was not reviewed.
4. Polymarket US `/v1/price-history` parameters and the `/v1/sports/{slug}/events` error: read the live docs pages.
5. Polymarket US: are trading API keys available to all retail KYC'd users? What are the real REST rate limits?
6. Polymarket US state list: get it from polymarket.us or the app, not secondary sites.
7. Kalshi tennis walkover and retirement rules versus both Polymarket rule sets. Mismatched settlement rules can turn an "arbitrage" into a loss.
8. Meaning of CLOB `/fee-rate` `base_fee: 1000` and Gamma `takerBaseFee`, versus `feeSchedule.rate = 0.05`. Confirm on the live fees page that fees are computed only from `feeSchedule`.
9. WebFetch could not reach docs.polymarket.com or docs.polymarket.us. Re-read the fees, rate-limits and prices-history pages directly before relying on exact numbers.
