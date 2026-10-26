# Upsets: data sources

## tennis-data.co.uk (results + closing odds): not available
2026-10-25 17:37 UTC: Cloudflare blocks the cloud container's IP (HTTP 403, "Sorry, you have been
blocked"; the bare host without `www.` is denied by the network policy). Not worked around. The
owner may still deliver the xlsx files by hand.

## Jeff Sackmann ATP/WTA match files (results, no odds)
Archival fork `phat-d0/tennis-sackmann-archive` (public; anonymous clone, ~900 MB):
`GIT_LFS_SKIP_SMUDGE=1 git clone --depth 1 https://github.com/phat-d0/tennis-sackmann-archive`.
**Licence CC BY-NC-SA 4.0** (Jeff Sackmann, tennis_atp / tennis_wta): non-commercial, attribute,
never commit the CSVs to this repo. Loader: `upsets/sackmann.py`.

| What | ATP | WTA |
|---|---|---|
| Tour-level files | `atp_matches_YYYY.csv`, 1968–2026 | `wta_matches_YYYY.csv`, 1968–2026 |
| Lower-level files (Elo only) | `atp_matches_qual_chall_YYYY.csv` (qualifying + Challenger) | `wta_matches_qual_itf_YYYY.csv` (qualifying + ITF) |
| Last tournament start | 2026-05-25 (Roland Garros) | 2026-05-25 |
| Tour-level rows loaded, 1990 → 2026-05 | 116,449 | 98,183 |
| Levels | G (Slam), M (1000), A (250/500), O (Olympics), D (Davis Cup), F (Finals) | G, PM (1000; T1 before 2009), P (500 / Premier 5 until 2020), I (250), T2–T5 (pre-2009), W (mixed: 1990 tour, 2021 some 250s, 125s), O, D, F |

Checked on the real files (2026-10-25):
- Rounds: R128, R64, R32, R16, QF, SF, F, RR, plus rare ER/BR. `round_idx` = 1 for the first
  main-draw round, from the draw size rounded up to a power of two (a 28/56 draw starts at R32/R64
  with byes for the top seeds).
- Dates: `tourney_date` (YYYYMMDD) is the tournament's start, so matches are ordered by tournament
  date → round → match_num.
- Scores: retirements end in `RET`, defaults `DEF`, walkovers `W/O` (also ` W/O`, `Walkover`), 12
  rows "Played and unfinished". Void (a sportsbook would void it) = walkover, or RET/DEF/unfinished
  before set 1 is complete. In rounds 1–2 of tour-level events 2010–2025, ~1.0% of matches are
  void and ~3.1% (ATP) / 3.0% (WTA) end in a retirement.
- Seeds: numeric, present on every tour-level tournament except a handful a year (ATP 0–3, WTA 0–7
  per season with no seeds recorded). Entry codes: Q, WC, LL, PR, SE, ALT.
- Excluded from tour-level tables: levels CC / 35+H / 50+H and events named "… 125" (ITF and 125s
  coded into the WTA files), team ties (D), Finals (F) and any event with round-robin matches.
- Elo sanity (overall Elo, players with ≥ 10 matches in the year, year-end): ATP 2010 Federer,
  Nadal, Djokovic, Murray; 2016 Djokovic, Murray; 2023 Djokovic, Sinner, Alcaraz; 2025 Sinner,
  Alcaraz, Djokovic. WTA 2016 S. Williams, Azarenka, Kerber; 2023 Swiatek, Gauff, Pegula,
  Sabalenka; 2025 Sabalenka, Swiatek, Rybakina, Gauff.

## DraftKings / Pinnacle historical odds (The Odds API, paid plan)
Planner + puller: `upsets/dk_history.py`; analysis: `upsets/dk_study.py`. Scope: Slams 2020+ and 1000s
2024+ (95 key-events through Roland Garros 2026), rounds 1–2, `bookmakers=draftkings,pinnacle`.
Raw responses are cached gzipped under `data/raw/odds_api/` (gitignored; **never committed**: the Odds
API terms forbid redistribution) with their own spend log `data/raw/odds_api/spend.log`. Every spend
also goes in `docs/data_inventory.md`. Order: `plan` (dry run, free) → `events --yes` (listings, ≤ 683
credits) → `plan` (exact odds count) → `odds --yes` (10 credits per snapshot). Pull cap 15,000, floor 1,000.
