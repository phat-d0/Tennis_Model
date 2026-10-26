# Tennis Odds page (public, GitHub Pages)

Static PWA in `site/`, published by the Lead's `publish.yml` as described in `docs/site_plan.md`. It reads
`data/odds.json` (built by `python -m upsets.site`) and `findings.json` (the Lead's). There is no build step,
no CDN, and no request to any other origin. Links to reports and the licence are plain `<a>` links.
**No Kalshi data:** the page code and its fixture never mention Kalshi, and a test enforces it.

## Files
| File | What |
|---|---|
| `site/index.html` | Shell: top bar (title, odds age, reload button), banners, view, footer, tab bar (Matches, Findings) |
| `site/app.js` | Fetches both JSON files (`no-cache`, and `reload` from the button); renders tabs, banners and footer; re-renders every minute and when the tab comes back into view |
| `site/style.css` | Soccer-app look (same tokens, top bar, tab bar, cards); light and dark via `prefers-color-scheme` (plus `data-theme` hooks); 640 px column on desktop |
| `site/manifest.webmanifest`, `site/sw.js`, `site/icons/` | Installable PWA; the service worker caches the shell and is network-first for everything (cache `tennis-odds-v1`; bump it when the shell changes) |
| `tests/test_site.py`, `tests/test_site_data/odds.json` | Fixture contract and math, static rules, and a Playwright smoke test of 6 data states × 4 viewport/theme combinations (skipped without node + playwright) |

## Page
- **Matches:** All / ATP / WTA filter (remembered per device). Matches are grouped by tournament (ordered by
  first start) and sorted by start time. Each card shows:
  - the start time in local time, with a "Started: odds were pre-match" tag once it has begun;
  - both players and a bar for the fair chance;
  - DraftKings and Pinnacle decimal odds, the fair chance, and the model chance with a **"model: not proven"** tag;
  - margins, the source of the fair chance, and the model's rated-match counts (or why there is no model).
- **Findings:** the "Every test so far: no edge after fees" line, then one card per entry with its verdict tag
  and a "Read the report" link to `github.com/.../blob/main/<report>`. Only `reports/...` paths become links.
- **Footer:** odds age and build age, credits this month against the cap, the ratings date, "Refreshes every
  3 h, often late", Sackmann attribution (CC BY-NC-SA 4.0, non-commercial), odds source, "Not betting advice".
  `credits.left` (the shared key's balance) is not shown.
- **Banners** (the page stays usable in every case):

  | State | Banner |
  |---|---|
  | `odds.json` missing or invalid | "No odds data yet" |
  | `odds.json` fails after an earlier load | "Can't refresh the odds" (keeps the old data) |
  | `no_key` / `below_floor` | "Odds aren't refreshing" |
  | `cap_reached` | "Monthly odds budget used up" |
  | `no_tournaments` | "No tournaments right now" |
  | `error: …` | "The last update failed" + the message |
  | any other status | "Unexpected data status" |
  | odds older than 6 h | "Old odds" |
  | `odds_fetched_at` null while there are matches | "Odds time unknown" |
  | build older than 12 h | "Page not rebuilt lately" |
  | no matches | an empty-state card |

  Null books, a null `fair_1` and a null `model_p1` show as dashes.

## Re-checking
```bash
python -m pytest -q tests/test_site.py
SITE_SHOTS_DIR=/tmp/shots python -m pytest -q tests/test_site.py   # screenshots of every state
```
Screenshots: `docs/ui_screenshots/site/`.
