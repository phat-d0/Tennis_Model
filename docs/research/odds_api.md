# The Odds API (v4): research notes for the tennis arb / swing-lock scanner

Researched 2026-10-24 from the public docs only, fetched with curl and read as extracted text.
**No endpoint that needs an API key was called and no credits were spent.**
`G/` below means `https://the-odds-api.com/liveapi/guides/v4/` and `S/` means `https://the-odds-api.com/sports-odds-data/`.
Pages read: `G/`, `G/api-error-codes.html`, `S/sports-apis.html`, `S/bookmaker-apis.html`,
`S/betting-markets.html`, `S/update-intervals.html`, `https://the-odds-api.com/historical-odds-data/`,
`https://the-odds-api.com/guide/rate-limit.html`, `https://the-odds-api.com/` (plans) and
`https://the-odds-api.com/terms-and-conditions.html`.
DraftKings tennis rules come from the DraftKings Massachusetts Sportsbook House Rules PDF hosted by the MA Gaming
Commission (implementation date 2025-08-26 per its page footer; file `...8.18.25.pdf`):
`https://massgaming.com/wp-content/uploads/DraftKings-House-Rules-8.18.25.pdf` (abbreviated `DKHR`).

Confidence tags: **[confirmed: url]** means I read it in that official page.
**[unverified: ...]** means inference, a secondary source, or something that can only be checked with a key.

---

## Key facts for implementers

- **Host:** `https://api.the-odds-api.com` (IPv6: `https://ipv6-api.the-odds-api.com`). Paths start with `/v4/`. [confirmed: G/#host]
- **Auth:** query parameter `apiKey=...` on every call, including the free ones. Our key comes from the env var `ODDS_API_KEY`. Never log the full URL, because it contains the key. [confirmed: G/ (every endpoint lists `apiKey`)]
- **Quota headers on every response:** `x-requests-remaining` (credits left until the quota resets), `x-requests-used` (credits used since the last reset), and `x-requests-last` (cost of this call). Log all three for each spend. [confirmed: G/ "Response Headers"]
- **Free calls (0 credits):** `GET /v4/sports` (in-season sports; `all=true` adds out-of-season ones) and `GET /v4/sports/{sport}/events` (ids, players, commence_time, no odds). [confirmed: G/#get-sports, G/#get-events]
- **Main cost rule:** `/odds` costs **markets × regions** credits. `bookmakers=` counts as one "region" per started block of 10 bookmakers. **A call that returns no events costs 0.** [confirmed: G/#get-odds]
- **Tennis has no generic key.** There is one key per tournament and tour, e.g. `tennis_atp_us_open`, and only big events are listed. **No Challenger, ITF, ATP/WTA 250s (bar a few), or doubles.** See §2. [confirmed: S/sports-apis.html]
- **`draftkings` (region `us`) is DraftKings Sportsbook.** Its link points to `https://draftkings.com/`. DK Pick6 is a separate `pick6` key in `us_dfs`. [confirmed: S/bookmaker-apis.html]
- **`us_ex` includes `kalshi`, `polymarket`, `polymarket_us`, `novig`, `prophetx`, `betopenly` and `limitless`.** Whether they quote tennis is **[unverified: needs a keyed call]**.

## 1. Endpoints and costs

| Endpoint | Cost | Notes |
|---|---|---|
| `GET /v4/sports?apiKey=` | 0 | `active`, `group`, `title`, `has_outrights` [confirmed: G/#get-sports] |
| `GET /v4/sports/{sport}/events` | 0 | params `commenceTimeFrom/To`, `eventIds` [confirmed: G/#get-events] |
| `GET /v4/sports/{sport}/odds` | markets × regions | params `regions`, `markets` (default `h2h`), `oddsFormat` (`decimal` default, or `american`), `bookmakers`, `eventIds`, `commenceTimeFrom/To`, `includeLinks`, `includeSids`, `includeBetLimits` (mainly exchanges). Costs 0 if no events. [confirmed: G/#get-odds] |
| `GET /v4/sports/{sport}/events/{id}/odds` | unique markets **returned** × regions | Any market, one event per call [confirmed: G/#get-event-odds] |
| `GET /v4/sports/{sport}/events/{id}/markets` | 1 | Market keys per bookmaker [confirmed: G/] |
| `GET /v4/sports/{sport}/scores` | 1, or 2 with `daysFrom` (1–3) | Live scores update about every 30 s [confirmed: G/#get-scores] |
| `GET /v4/sports/{sport}/participants` | 1 | For tennis, a player list [confirmed: G/#get-participants] |
| `GET /v4/historical/sports/{sport}/odds?date=` | **10 × markets × regions** | Closest snapshot ≤ `date` [confirmed: G/#get-historical-odds] |
| `GET /v4/historical/sports/{sport}/events?date=` | 1 (0 if no events) | [confirmed: G/] |
| `GET /v4/historical/sports/{sport}/events/{id}/odds?date=` | 10 × markets returned × regions | Featured + extra markets [confirmed: G/] |

- The `/odds` response gives a market-level `last_update`. When a market is suspended or closed, `last_update` stops advancing and the market is removed after about 15 min. The `/odds` endpoint never returns completed events. An event is in-play when `commence_time` < now. [confirmed: G/#get-odds "More info"]
- American odds can have small rounding discrepancies, so **use `oddsFormat=decimal`**. [confirmed: G/#get-odds]
- Each `h2h` response has two outcomes, named by player. Exchanges also return `h2h_lay`. [confirmed: G/#get-odds; S/betting-markets.html]

## 2. Tennis sport keys

- One key per tournament and tour, in the form `tennis_{atp|wta}_{tournament}`. A key is `active` only while the tournament is on, so discover keys from free `/v4/sports` calls. [confirmed: S/sports-apis.html; G/#get-sports example `tennis_atp_french_open`, "Men's Singles"]
- The 47 listed keys are 23 ATP and 24 WTA: the 4 Slams (`*_aus_open_singles`, `*_french_open`, `*_wimbledon`, `*_us_open`), the 1000s (Indian Wells, Miami, Madrid, Italian, Canadian, Cincinnati, Shanghai/Wuhan, Paris, Monte-Carlo, China, Dubai, Qatar), and a few 500/250s (ATP Barcelona, Hamburg, Halle, Japan, Munich, Queen's, Washington; WTA Bad Homburg, Charleston, German, Guadalajara, Monterrey, Singapore, Queen's, Strasbourg, Stuttgart, Washington). [confirmed: S/sports-apis.html]
- **Not covered:** Challenger, ITF, most 250s, team events (Davis/United/Laver Cup) and doubles. These are most of Kalshi's tennis volume (KXATPCHALLENGERMATCH, KXITF*). [confirmed absent from S/sports-apis.html; "uncovered by DK in the API" is an inference]
- `/scores` support (✔ on the sports page) exists only for some tennis keys: the US Open, Canadian, Cincinnati, China, Japan, Shanghai, Washington, Wuhan, Guadalajara, Monterrey and Singapore keys. Others have none. [confirmed: S/sports-apis.html]
- The home page describes the coverage as "Grand Slams, ATP 1000, WTA 1000 and more". [confirmed: https://the-odds-api.com/]
- Sport keys can't be listed for today without a key. Late October usually means the ATP Paris Masters (`tennis_atp_paris_masters`). [unverified: calendar inference]

## 3. Markets, regions, bookmakers

- Featured markets are `h2h`, `spreads`, `totals`, `outrights`, `h2h_lay` and `outrights_lay`. "spreads and totals markets are mainly available for US sports and bookmakers". [confirmed: S/betting-markets.html]
- Tennis-specific additional markets go through `/events/{id}/odds`: `h2h_s1`, `h2h_s2`, `spreads_s1`, `totals_s1`, `alternate_set_spreads`, `alternate_set_totals` and `alternate_totals_s1/s2`. We only need `h2h`. [confirmed: S/betting-markets.html]
- **Regions:** `us`, `us2`, `us_dfs`, `us_ex`, `uk`, `eu`, `au`, `ca`, `fr`, `se`, `fi`. [confirmed: S/bookmaker-apis.html]
  - `us`: betonlineag, betmgm, betrivers, betus, bovada, williamhill_us (Caesars, paid plans only), **draftkings**, fanatics (paid only), fanduel, lowvig, mybookieag.
  - `us2`: ballybet, betanysports, betparx, courtside, espnbet, fliff, hardrockbet(+_az/_fl/_oh), rebet.
  - `us_ex`: betopenly, **kalshi**, limitless, novig, **polymarket** (intl), **polymarket_us**, prophetx.
  - `uk`/`eu`/`au` include Betfair Exchange and Matchbook (with lay odds), and `eu` includes pinnacle ("public website, may incur a delay").
- Whether `kalshi`/`polymarket_us` appear on tennis events is **[unverified: needs a keyed call; the docs don't list coverage by sport and bookmaker]**. The docs say "Some bookmakers may not list for less popular sports". [confirmed: S/bookmaker-apis.html "Notes"]

## 4. Historical odds

- Featured markets from **2020-06-06**, in **10-min snapshots, then 5-min snapshots from Sept 2022**. Additional markets from 2023-05-03, in 5-min snapshots. **Paid plans only** (`HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN`). [confirmed: https://the-odds-api.com/historical-odds-data/; G/api-error-codes.html]
- Earliest snapshot per tennis key (historical page table): Slams from 2020–21 (e.g. `tennis_atp_us_open` 2020-08-28, `tennis_atp_aus_open_singles` 2021-02-06). Most 1000s start in 2024–25 (e.g. `tennis_atp_paris_masters` 2024-10-28). Several 250/500s start only in 2026. [confirmed: https://the-odds-api.com/historical-odds-data/]
- Historical odds before 2022-09-18 were captured as decimal only. [confirmed: G/#get-historical-odds]
- **In-play events are in historical snapshots** (Upsets, 2026-10-28, from our own cached responses, 0 credits).
  The docs host (the-odds-api.com) isn't reachable from cloud sessions, so this rests on our data, not on the docs
  text. The cache holds 6,166 `/historical/sports/{key}/odds` snapshots, all tennis keys we pulled for the DK studies,
  with `bookmakers=draftkings,pinnacle`.
  - 28,446 event rows have `commence_time` before the snapshot `timestamp`. DraftKings is quoted on 23,362 of them and
    Pinnacle on 21,299.
  - 42,527 bookmaker quotes have `last_update` after the start.
  - In-play quotes are fresh: at snapshots at least 10 min after the start, the quote age (snapshot − `last_update`) is
    a median of 0.8 min for DK (p75 4.7, p90 6.1) and 0.7 min for Pinnacle.
  - Prices move like live prices: the max of the two odds has a median of 4.3 and a p99 of 67, and 23% are over 10.
  - **So DK and Pinnacle are both quoted in play** in the historical archive.
- **Snapshot interval, measured** from each response's `next_timestamp − timestamp`: 10 min in 2020–2022 and 5 min from
  2023. One 2026 gap was 1.4 min. This matches the docs line above (5-min from Sept 2022).
- Cost per historical snapshot: 10 × markets × regions [confirmed, §2]. h2h with draftkings + pinnacle (≤ 10
  bookmakers = 1 region block) = **10 credits**. One snapshot covers every event of that key at that moment.
- DK in-play dry run for the cash-out/FAVDIP studies: reports/upsets_dk_inplay.md (`python -m upsets.dk_inplay plan`).
- Cost example: one 5-min snapshot of one key, h2h, with ≤10 bookmakers costs 10 credits. A 14-day tournament at 5-min resolution is 4,032 snapshots ≈ **40k credits**. Pull only windows around Kalshi matches. [inference from the confirmed cost rule]

## 5. Rate limits and freshness

- **30 requests/s** on paid plans. A 429 means "space out over several seconds" and retry after a couple of seconds. Cache `/sports` (~1 h) and `/events` (~10 min). [confirmed: https://the-odds-api.com/guide/rate-limit.html; G/api-error-codes.html]
- **Update intervals** (pre-match / in-play): featured markets (h2h) 60 s / **40 s**; additional markets 60 s / 60 s; outrights 5 min / 60 s; **betting exchanges (all markets) 20 s / 10 s**. The interval shrinks over the 6 h before start. [confirmed: S/update-intervals.html]
- Polling DK h2h faster than about every 40 s in-play only buys duplicate data.
- Plans: Starter is free with 500 credits/month and no historical data. Paid plans: 20K $30, 100K $59, 5M $119, 15M $249 per month. The owner's plan and budget aren't known here. [confirmed: https://the-odds-api.com/]
- Terms prohibit reselling or redistributing the data as a raw feed. Internal analytical use is allowed. [confirmed: https://the-odds-api.com/terms-and-conditions.html]

## 6. DraftKings Sportsbook tennis settlement vs Kalshi

Source: DKHR, Sport Rules → Tennis (pp. 137–139). This is the MA version; other states' house rules may differ. [confirmed: DKHR]

| Situation | DraftKings match moneyline | Kalshi match market |
|---|---|---|
| Walkover / match never starts | **All bets void** (stake back) | Settles at a "fair price" (not 0/1) |
| Retirement/DQ **before set 1 completes** | **Void** | Retiring player's market → **No** (opponent wins) |
| Retirement **after set 1**, ATP/WTA/Slam | Official winner (player advancing) **wins**; other side loses | Retiring player → No |
| Retirement after set 1, **ITF / UTR / exhibition** | **Void** | Retiring player → No |
| Interrupted and not finished within the competition | Void (unless already unconditionally determined) | per Kalshi rules [unverified for this case] |
| Format change before start (e.g. Bo5→Bo3) | Void | n/a [unverified] |

- **Implication:** a DK + Kalshi "lock" is **not risk-free** when a player retires before the end of set 1. The DK leg is refunded while the Kalshi leg settles 0 or 1, which leaves one leg naked. Size the risk by the retirement-in-set-1 rate per tour. [inference]
- Secondary reports say DK moved to "first set" retirement rules for ATP in 2023 (WTA was full match at the time). The current DKHR text applies the set-1 rule to all non-ITF matches. [unverified: https://www.actionnetwork.com/tennis/tennis-betting-rules-player-retires-rain-weather-delay; superseded by DKHR]

## 7. Implications for our collector

- **Cheapest live DK poll:** `GET /v4/sports/{key}/odds?markets=h2h&bookmakers=draftkings&oddsFormat=decimal` costs **1 credit per call per tournament key** while events exist, and 0 when the list is empty. [from confirmed rules]
- **Same 1 credit gets more venues:** `bookmakers=draftkings,kalshi,polymarket_us,fanduel,...` (≤10 keys) is still 1 region, so add cross-venue quotes at no extra cost. If `kalshi` appears, its quote is a midpoint/price snapshot, not our order book, so keep using our own Kalshi collector for fills. [cost confirmed; the meaning of exchange prices is unverified]
- **Discovery at 0 credits:** call `/v4/sports` once an hour to find `active` `tennis_*` keys, and `/events` every 10 min for ids and commence times.
- **Budget formula:** credits/day ≈ Σ over active keys of (hours with listed events × 60 / M), with M = poll interval in minutes.
  Example: 2 keys (ATP + WTA of one event) × 14 h/day of listings: M=1 → 1,680/day (~50k per 30-day month); M=5 → 336/day (~10k/month); M=15 → 112/day.
  Keys stay listed between matches with pre-match odds, so "hours with events" is close to all day during a tournament. Budget 24 h unless we gate on `commence_time`. [estimate]
- Pre-match prices update every 60 s, so poll pre-match slowly (e.g. 15 min) and in-play at ~1 min only for keys with an event where `commence_time` < now. Use `eventIds` to limit the payload (it doesn't change the cost).
- **Coverage gap:** DK via this API covers only the listed big events. Challenger/ITF Kalshi matches have no DK leg here.
- **Settlement-risk gap:** see §6. Any cross-venue alert must flag "not hedged vs retirement before end of set 1 / walkover".

**Open questions for the owner**
1. Which plan is the shared key on, what's the monthly credit budget and floor for tennis, and when does the quota reset?
2. OK for Data to make free `/sports` and `/events` calls (0 credits, but they use the key) to confirm live tennis keys and whether `kalshi`/`polymarket_us` quote tennis? A one-off 1-credit `/odds` test with `bookmakers=draftkings,kalshi,polymarket_us` would answer coverage.
3. Is historical backfill (10 credits/snapshot, paid plan) worth it for tennis, and over which tournaments and windows?
4. Which state's DK house rules apply to the owner? The MA version is used here.
