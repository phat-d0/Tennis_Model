# Tennis Odds page (GitHub Pages): plan and contract

The owner approved this on 2026-10-26: a public phone page like the soccer app (phat-d0.github.io/Soccer_Stats). It shows
ATP/WTA match odds from DraftKings and Pinnacle, refreshed every 3 hours. URL once live:
`https://phat-d0.github.io/Tennis_Model/`.

## Hard rules
- **No Kalshi data on the page or in its build.** The repo is public, and a Pages site is public even from a private
  repo. The builder must not read `data/processed/kalshi*`, `data/raw/kalshi`, or call Kalshi. Kalshi prices,
  locks and positions stay on the private VPS dashboard.
- **No raw odds history in git.** The current odds are shown on the page. The snapshot history stays in the GitHub
  Actions cache (`site-cache-*`). It is never committed, and it is never uploaded as an artifact.
- **Credits.** The page uses the shared paid key (repo secret `ODDS_API_KEY`) under these limits:
  - The **5,000 reserve** applies to every call: `OddsApi(floor=5000)`.
  - The page may spend at most **600 credits a calendar month**, paced so a busy week can't use the whole month.
  - One `/odds` call per tournament key with `bookmakers=draftkings,pinnacle` costs 1 credit, and is only made when
    that key has a match starting in the next 36 h. `/sports` and `/events` are free.
  - This replaces `upsets.dk_live` and its 481-credit cap.
- **Sackmann data (CC BY-NC-SA).** The page states the attribution and the non-commercial use. The CSVs are never
  committed; the build clones the archive and caches the ratings.

## Pieces and owners
| Piece | Owner | Path |
|---|---|---|
| Builder: odds → `odds.json`, Elo ratings, spend cap, snapshot history | Upsets | `upsets/site.py` (CLI `python -m upsets.site`), `tests/test_upsets_site.py` |
| Page: static PWA, no CDN, light/dark, 390 px and desktop | Dashboard | `site/` (`index.html`, `app.js`, `style.css`, `manifest.webmanifest`, `sw.js`, `icons/`), `tests/test_site*.py` |
| Findings tab content | Lead | `site/findings.json` |
| Workflows: `publish.yml` (cron `17 */3 * * *`, dispatch, push to main), `ci.yml` (pytest on PRs) | Lead | `.github/workflows/` |

## Build command (the workflow runs exactly this)
```
python -m upsets.site build --out _site/data --cache data/site_cache \
    --archive data/sackmann --floor 5000 --month-cap 600
cp -r site/* _site/
```
- With no `ODDS_API_KEY`, or under the cap or floor, it makes no paid calls. It writes `odds.json` from the
  last cached snapshot and sets `status` to say why.
- `--archive` is a shallow, sparse clone of `phat-d0/tennis-sackmann-archive`, restricted to the
  `atp/atp_matches_*.csv` and `wta/wta_matches_*.csv` files. Ratings are cached by the archive's commit SHA.

## `_site/data/odds.json`
```json
{"generated_at": "ISO-8601 UTC", "odds_fetched_at": "ISO-8601 UTC | null",
 "status": "ok | no_key | cap_reached | below_floor | no_tournaments | error: ...",
 "credits": {"left": 0, "used_this_month": 0, "month_cap": 600},
 "ratings_through": "YYYY-MM-DD",
 "tournaments": [{"sport_key": "tennis_atp_paris", "title": "ATP Paris Masters", "tour": "ATP"}],
 "matches": [{"event_id": "", "sport_key": "", "tournament": "", "tour": "ATP|WTA",
   "commence_time": "ISO-8601 UTC", "player_1": "", "player_2": "",
   "draftkings": {"odds_1": 1.8, "odds_2": 2.0, "last_update": "", "margin": 0.056} ,
   "pinnacle":   {"odds_1": 1.85, "odds_2": 2.05, "last_update": "", "margin": 0.028},
   "fair_1": 0.0, "dk_implied_1": 0.0,
   "model_p1": 0.0, "model_n1": 0, "model_n2": 0}]}
```
- A book is `null` when it doesn't quote the match.
- `margin` = 1/odds_1 + 1/odds_2 − 1.
- `fair_1` = Pinnacle's chance with the margin removed proportionally, or DraftKings' when Pinnacle is missing.
- `dk_implied_1` = 1/odds_1 at DraftKings.
- `model_p1` = surface Elo blended with overall Elo, from Sackmann results. It is `null` when either player has fewer
  than 20 rated matches or the name isn't matched. `model_n*` are the players' rated match counts.

## `site/findings.json`
A list of `{"title", "verdict", "summary", "report"}`. `report` is a path into `reports/`, linked on github.com.

## Page
- **Matches tab:** grouped by tournament, then start time. Each card shows the two players, DraftKings odds,
  Pinnacle odds, DraftKings' margin, the fair chance, and the model chance with a "model: not proven" tag.
- **Findings tab:** the cards from `findings.json`. The header line says "Every test so far: no edge after
  fees".
- **Footer:** data age, credits used this month against the cap, the refresh rate (every 3 h, often late because
  GitHub delays scheduled runs), and the Sackmann attribution (CC BY-NC-SA).
- Bad states show a banner and keep the page usable: odds older than 6 h, any `status` other than ok, an empty
  list.
- Before review, take screenshots at 390×844 and 1280×800 in light and dark, with no console errors (team rule).

## Owner one-time setup
1. Repo Settings → Pages → Source: **GitHub Actions**.
2. Add the Actions secret `ODDS_API_KEY`. Done 2026-10-26.
