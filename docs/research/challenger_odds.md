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
  - No other endpoint or plan adds Challengers that I could find. The key's monthly quota is 4,938,943 remaining; that is quota, not coverage.

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

## Recommendation (for the Lead / owner)

1. **Polymarket international is the only free Challenger source today.**
   - Show it only after the owner reads polymarket.com/tos. I couldn't read it, and it decides public display.
   - If cleared, show it as "Polymarket (indicative bid/ask)" with the tier taken from our own tournament list.
   - Builder cost: about 10 gamma pages plus one `/books` POST per run. No key and no credits.
2. **For DraftKings Challenger lines, trial before paying.**
   - Start with the **OddsPapi free tier**: one or two calls on a live Challenger match, to see whether a DraftKings price is actually there.
   - If DraftKings is missing or the free tier is too small, try **odds-api.io** (£49/month, ask for written consent to show prices) or **SportsGameOdds Pro** (7-day trial; Challenger coverage not stated).
   - Don't commit to OpticOdds or OddsJam (about $5k/month, unverified).
3. **Don't use Kalshi Challenger prices on the page** (owner rule 4). **Don't use Pinnacle resellers**, since they are not sanctioned.
4. **Polymarket US** is worth noting only as the US-tradeable venue. Its Challenger books are too wide to be a useful line.

Nothing here spends Odds API credits or touches Kalshi.
