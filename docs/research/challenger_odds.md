# Challenger / WTA 125 odds: sources for the public page

Data role, 2026-10-26 (live checks around 08:15–08:40 UTC). Read-only. Requests made: about 40 (Polymarket gamma 6,
CLOB 17, Polymarket US gateway 15, The Odds API `/sports` 1, which costs 0 credits). No Kalshi requests.

Tags:
- `[live]`: seen in an API response today.
- `[doc]`: read on the provider's own page today.
- `[snippet]`: from a search summary or third party only; re-verify before relying on it.
- `[unverified]`: could not read the source.

## Answer in one paragraph

**Polymarket international is the only free, keyless source with real Challenger books today.**
- It lists about 110 open ATP Challenger / WTA 125 singles matches across 8 events. Their CLOB books are usable but thin: typical spread 1–7¢ and top-of-book often only 5 shares.
- I could not read its Terms of Use, so whether prices can be shown on a public page is open. polymarket.com is blocked by our network policy, and the page renders empty to WebFetch.

**Polymarket US also lists the same Challenger matches, but its books are much wider.**

**No sanctioned feed confirms DraftKings Challenger lines yet.**
- Three aggregators claim Challenger coverage and list DraftKings as a tennis bookmaker. Each needs a trial to confirm, and each has its own ToS limits:
  - OddsPapi (free tier)
  - odds-api.io (from £49/month)
  - SportsGameOdds (DraftKings on the $299/month Pro plan; Challenger not stated)
- **The Odds API has no Challenger keys on any endpoint.** All 51 tennis keys, active or not, are tour-level.
- **Pinnacle's public API has been closed since 2025-07-23.**

## 1. Polymarket international (gamma + CLOB)

### What is listed
Source: `GET https://gamma-api.polymarket.com/events?tag_id=864&active=true&closed=false`, paged with `limit=100&offset=…`. I read 600 events (588 matches); there may be more pages. `[live]`

Matches carry the tag `Games`. The event `seriesSlug` is `atp`, `wta` or `itf`. There is no separate Challenger or 125 series: the tier is visible only in the tournament name (title prefix `"Brest: A vs B"`).

Open singles matches on Challenger/125 events (doubles excluded), all with `acceptingOrders: true`:

| Event (seriesSlug) | Tier (my reading) | Open matches | Median volume $ | Median liquidity $ |
|---|---|---|---|---|
| Brest (atp) | ATP Challenger | 17 | 119 | 1,236 |
| Guayaquil (atp) | ATP Challenger | 15 | 108 | 1,683 |
| Sioux Falls (atp) | ATP Challenger | 14 | 300 | 2,097 |
| Ningbo (atp) | ATP Challenger | 13 | 122 | 677 |
| Seoul (atp) | ATP Challenger (Cilic–Zhang, Sakamoto–Samrej) | 10 | 2,105 | 25,817 |
| Curitiba (wta) | WTA 125 | 16 | 32 | 1,041 |
| Courmayeur (wta) | WTA 125 (tier not confirmed) | 12 | 0 | 1,969 |
| Queretaro (wta) | WTA 125 | 12 | 0 | 264 |

- **Tier mapping is my reading of the tournament names.** Polymarket does not label the tier, so a page would need its own tournament-to-tier list.
- **ITF coverage is much larger:** about 40 M15–W100 events.
- Two stale, already-played Challenger events still show `active` (Bari 2026-10-02, St. Tropez 2026-09-26) with `acceptingOrders: false`. Filter on `acceptingOrders` and the start time.

### Book quality
Source: `GET https://clob.polymarket.com/book?token_id=…`, two matches per event, 16 books. `[live]`
- **Spreads:** mostly 0.01–0.07; one Courmayeur match at 0.12.
- **Queretaro outlier:** one match was 0.08 / 0.97, which is effectively no book.
- **Top-of-book size:** often the 5-share minimum. Top-3 levels usually held 20–500 shares per side.
- **Seoul is deep:** for example Sakamoto–Samrej was 0.87/0.88 with 215 / 7,228 shares at the top.

So the prices are fine as an **indicative** line (bid/ask or ask-implied probability), but not as a firm fill for size. The CLOB is a peer order book, not a sportsbook line.

Technical notes:
- The CLOB answered `403` to Python `urllib`, which sends no User-Agent, but `200` to curl. Send a User-Agent.
- Read limits documented earlier: `/book` 1,500 per 10 s (see `docs/research/other_venues.md`).
- **US persons can't trade Polymarket international.** Display is a separate question from trading.

### Terms for showing prices on a public page: `[unverified]`
- I could not read the Terms of Use.
  - `polymarket.com/tos` is denied by this environment's network policy (proxy `CONNECT 403`).
  - WebFetch gets only the page shell; the text is rendered by JavaScript.
  - docs.polymarket.com and docs.polymarket.us carry no API or data terms.
- Search results surfaced only third-party scraper listings and unrelated sites `[snippet]`. One Apify listing says the API docs set no specific attribution or redistribution rule for public market data. That is not Polymarket's own statement.
- **The owner (or the Lead) should read https://polymarket.com/tos in a browser** and check the sections on content, IP and prohibited use before we show Polymarket prices publicly. Until then, treat public display as not cleared.

## 2. Polymarket US (gateway.polymarket.us)

- **Sports list:** `GET /v1/sports` shows tennis leagues `atp`, `wta`, `atpcq`, `atpdb`, `wtadb`, `itfm`, `itfw`, `itfme`, `itfwo`, `utr`, `daviscup`, `bjkcup`, all `isOperational: true`. `ttchallenger` is table tennis. `[live]`
- **Challengers are listed under the ATP series.** `GET /v1/search?query=<player>` finds today's Challenger matches with `seriesSlug: atp-2026`. `[live]` Examples:
  - Brooksby–Nakashima (Sioux Falls)
  - Ugo Carabelli–Coria (Guayaquil)
  - Gaston–Glinka (Brest)
  - Schoolkate–Imamura (Ningbo)
  - Searching by tournament name ("Brest", "Guayaquil") returns only soccer or basketball. Search by player.
- **Books are much wider than international.** From `GET /v1/markets/{slug}/book` `[live]`:
  - Brooksby: bids 0.59 / offers 0.83 (international: 0.85 / 0.86).
  - Ugo Carabelli: 0.59 / 0.95.
  - Gaston: 0.40 / 0.70.
  - Top sizes are 0.2–15 contracts.
  - For Challengers, Polymarket US is listed but barely quoted.
- **Settlement differs from international:** a walkover settles at the last fair market price; a retirement settles to the official winner (seen in the market text). `[live]`
- **Terms:** `polymarket.us/tos` renders empty to WebFetch. `[unverified]`

## 3. DraftKings Challenger odds through a sanctioned feed

- **Does DraftKings offer Challenger markets?** DraftKings sportsbook URLs for Challenger events exist, e.g. `sportsbook.draftkings.com/es/leagues/tenis/challenger-bloomfield-hills`. `[snippet]` I did not open DraftKings pages (ToU).
- **The Odds API:** `GET /v4/sports?all=true` (0 credits) lists **51 tennis keys including inactive ones, all ATP/WTA tour-level, none Challenger, 125 or ITF.** `[live]`
  - Its tennis page names Grand Slams, 1000s and 500s. `[snippet]`
  - No other endpoint or plan adds Challengers that I could find. The key's monthly quota is well above the reserve; that is quota, not coverage.

| Provider | Challenger? | DraftKings for tennis? | Price | Personal / free plan | Public display under ToS |
|---|---|---|---|---|---|
| **OddsPapi** (oddspapi.io) | Yes, "ATP Challenger" category (e.g. ATP Challenger Seoul). WTA 125 / ITF not stated `[doc]` | Yes, "Draftkings" listed for tennis `[doc]` | Paid prices not stated | Free tier "on the same endpoints as the paid one"; limits not stated `[doc]` | No public-display clause. "You may not resell, repackage, or redistribute our data as a standalone product" `[doc]` → display inside our page is probably fine; ask in writing |
| **odds-api.io** (not The Odds API) | FAQ: "challenger events, and ITF tournaments" `[doc]` | DraftKings in "Top Tennis Bookmakers" `[doc]` | "Plans from £49/month" `[doc]` | No free tier mentioned | "You may not resell, redistribute, or sublicense our data to third parties without prior written consent"; public display not addressed (ToS updated 2026-10-04) `[doc]` → needs written consent |
| **SportsGameOdds** | ATP page says "tour-level events, Masters 1000s and the Grand Slams"; Challenger **not** stated `[doc]` | DraftKings on all plans' book lists `[doc]`; tennis leagues only on Pro | Amateur free (8 US leagues, no tennis), Rookie $99, **Pro $299/month** (53 leagues), All-Star custom `[doc]` | Free tier has no tennis | Allowed to end users "as part of applications that provide material value"; no bulk dumps or standalone resale (ToS v3, 2026-06-23) `[doc]` → a public odds page likely qualifies; confirm |
| **OpticOdds** | Not stated | DraftKings in its book list `[snippet]` | No public pricing; about $5,000/month reported `[snippet]` | No | Unknown |
| **OddsJam API** | Not stated | Not confirmed | About $4,995/month reported `[snippet]` | No | Unknown |
| **SportsDataIO** | Coverage page: WTA 250 / ATP and above; Challenger not mentioned `[snippet]` | Not stated | About $16.5k/year median across products `[snippet]` | No | Unknown |
| Goalserve | Lists Challenger + odds comparison, about $150/month `[snippet]` | Not stated | | | Unknown |

None of these confirms DraftKings Challenger lines specifically. They confirm "DraftKings for tennis" plus "Challenger events" separately. Only a trial call on a live Challenger match will show whether DraftKings prices it.

## 4. Pinnacle

- **Public access closed:** the official `pinnacleapi/pinnacleapi-documentation` README says: "Access to Pinnacle API suite has been closed for the general public since July 23rd, 2025." `[doc]`
  - It adds: "We offer bespoke data services for select high value bettors & commercial partnerships. We also support academics and pregame handicapping projects."
  - To apply: "write a short description of your use case to api@pinnacle.com."
- **Option:** our project could apply as a "pregame handicapping project", but a public page is probably not what that offer is for.
- **Resellers exist but are not sanctioned:** third parties resell Pinnacle-sourced odds (PinnWire, pinnapi, OddsPapi's Pinnacle feed). They are not sanctioned by Pinnacle as far as I can tell. `[snippet]`

## 5. OddsPapi free-tier test (2026-11-05)

Data role, owner-approved (2026-11-01), run 2026-11-05 around 09:40 UTC. Key from the env var `ODDSPAPI_KEY`; it never
appears in a log, file or commit (the `/v4/account` response echoes the key, so its `api_key` field is stripped before
saving). Raw responses stay in gitignored `data/raw/oddspapi/`. No fixture is committed.

### What the docs say `[doc]`
Source: oddspapi.io/en/docs, v4: overview, "Requests & Quota", Errors, and one page per endpoint.
- Base `https://api.oddspapi.io/v4/…`. The key goes in the `apiKey` query parameter, so request URLs must never be logged.
- **Quota:** 1 request = 1 call to a billable endpoint, whatever the response size or status (4xx/5xx count too). It
  resets on the 1st of each month.
  - `/v4/historical-odds` is free.
  - `/v4/account` is unmetered and still works after the quota runs out.
  - Over quota, every call except `/v4/account` returns 429 `REQUEST_LIMIT_EXCEEDED`.
- **Cooldowns:** per endpoint, 1,000 ms (`account`, `sports`, `tournaments`, `odds-by-tournaments`) and 2,000 ms
  (`fixtures`). I spaced calls 2.1 s apart.
- **`odds-by-tournaments`:** up to 3 `tournamentIds` and exactly one `bookmaker` per call.
- **403 `RESTRICTED_ACCESS`:** "No bookmakers with live access found" when a fixture is live and the plan has no
  live-odds bookmaker.

### What our free account has `[live]`
`GET /v4/account`, read before and after the test:
- `request_limit` 250 per month; `rate_limit` null; `websocket_access` 0; `valid_until` null.
- All sports, ids 10–68, tennis = `sportId` 12.
- 366 bookmakers, `draftkings` among them.
- **`has_live_odds: false` for every bookmaker, DraftKings included. The free tier has no in-play odds**, so the
  "live Challenger match" part of the test can't be done on this plan. Pre-match it is.
- `request_count` was 0 before and **6 after**.

### Calls made (6 billable + 2 unmetered)

| # | Endpoint | Params | Result |
|---|---|---|---|
| – | `/v4/account` | – | 200 (unmetered) |
| 1 | `/v4/sports` | – | 200; tennis = 12 |
| 2 | `/v4/tournaments` | sportId=12 | 200; 11,453 tennis tournaments: Challenger 1,350, WTA 125K 339, ITF 8,020, ATP 311, WTA 312 |
| 3 | `/v4/odds-by-tournaments` | bookmaker=draftkings, 3 Challenger singles | 200 |
| 4 | `/v4/odds-by-tournaments` | bookmaker=draftkings, 3 Challenger singles | 200 |
| 5 | `/v4/odds-by-tournaments` | bookmaker=draftkings, 2 WTA 125K singles | 200 |
| 6 | `/v4/odds-by-tournaments` | bookmaker=draftkings, ATP Paris + WTA Chennai (control) | 200 |
| – | `/v4/account` | – | 200 (unmetered) |

No errors and no 429s.

### DraftKings coverage `[live]`
These are DraftKings pre-match match-winner odds (market 121, two outcomes) on fixtures that hadn't started.
"Last change" is the age of the newest `changedAt` on that market at 09:43 UTC.

| Tier | Events | Fixtures with DK odds | 2-way match winner | DK margin (median, range) | Last change (median, max) | Hours to start (min–max) |
|---|---|---|---|---|---|---|
| ATP Challenger | Charlottesville, Costa do Sauipe, Villa Maria, Taipei, Taranto, Bratislava II | **31** | 31 (29 all outcomes active) | 6.6% (6.0–6.7%) | 1.8 h, 8.8 h | 0.6–32 |
| WTA 125K | Cali, Luanda | **7** | 7 (6 active) | 6.6% (5.9–6.7%) | 1.4 h, 15.3 h | 0.4–24 |
| Tour control | ATP Paris, WTA Chennai | 12 | 12 | 4.8% (4.7–5.0%) | 3.0 h, 7.6 h | 0.3–21 |

- **DraftKings does price ATP Challenger and WTA 125 matches**, through a source DraftKings doesn't run. Every Challenger
  and WTA 125 event I queried returned DK match-winner odds.
- **Not every listed match has a DK price yet.** The tournament list counted 56 upcoming Challenger singles across these
  6 events; DK prices came back for 31 (55%). WTA 125: 13 listed, 7 priced. Most likely the later or unscheduled
  matches aren't priced yet, but I didn't check it, to save calls.
- **DK's Challenger and WTA 125 margin is about 6.6%**, against 4.8% on tour-level events here and 4.84% at tour level
  in our Odds API study (`reports/upsets_dk_small.md`).
- **Freshness:** prices had changed within the last 2 hours in the median case, the oldest up to 15 h. Fine for a
  pre-match line, but there's no in-play price on this plan.
- **Budget:** 250 requests a month at 1 request per call. A page build querying about 6 Challenger/WTA 125 events, 3
  per call, costs 2–3 requests, so about 80–120 builds a month. That's below the page's 3-hourly rhythm (≈ 240 builds a
  month), so a page feed would need either a slower cadence for this block or a paid plan. The pricing page builds a
  custom plan (bookmakers × sports × requests); I didn't price one.

### Terms, still open
The ToS forbids redistributing the data "as a standalone product". Showing DK Challenger prices on our public page next
to our own model is probably allowed, but needs OddsPapi's written OK first (owner decision). Nothing from this test is
on the page.

## Recommendation (for the Lead / owner)

1. **Polymarket international is the only free Challenger source today.**
   - Show it only after the owner reads polymarket.com/tos. I couldn't read it, and it decides public display.
   - If cleared, show it as "Polymarket (indicative bid/ask)" with the tier taken from our own tournament list.
   - Builder cost: about 10 gamma pages plus one `/books` POST per run. No key and no credits.
2. **For DraftKings Challenger lines, trial before paying.**
   - Start with the **OddsPapi free tier**: one or two calls on a live Challenger match, to see whether a DraftKings price is actually there.
   - **Done 2026-11-05 (§5):** DraftKings pre-match prices are there for ATP Challenger (31 of 31 returned fixtures) and
     WTA 125 (7 of 7), with a margin of about 6.6%. The free tier has no in-play odds and allows 250 requests a month. For
     the page: ask OddsPapi for written consent first, then pick a build cadence that fits 250 requests a month, or
     price a small paid plan.
   - If DraftKings is missing or the free tier is too small, try **odds-api.io** (£49/month, ask for written consent to show prices) or **SportsGameOdds Pro** (7-day trial; Challenger coverage not stated).
   - Don't commit to OpticOdds or OddsJam (about $5k/month, unverified).
3. **Don't use Kalshi Challenger prices on the page** (owner rule 4). **Don't use Pinnacle resellers**, since they are not sanctioned.
4. **Polymarket US** is worth noting only as the US-tradeable venue. Its Challenger books are too wide to be a useful line.

Nothing here spends Odds API credits or touches Kalshi.
