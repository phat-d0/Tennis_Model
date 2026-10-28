# Work plan

Status for every project. Each role updates its own block of the Master plan and its own status lines, in
the same PR as the work (CLAUDE.md, Team rule 7). The Lead keeps the priority order and merges. Durable rules
and facts are in `CLAUDE.md`.

## Master plan (read first; updated 2026-10-28)
**Where we stand:** no edge found anywhere after fees. That covers Kalshi true arbs and swing locks, early-round
underdogs at Kalshi and DraftKings, Elo models against Pinnacle, and the penultimate-set and decider prices. Line
shopping is a thin, unproven edge. What's running now: live forward tests on real order books (paper trading) and
answers to the owner's open questions.

**Priority order (owner sets it; the Lead records it):**
1. **Cash-out study** (owner 2026-10-28): when to cash out, including the owner's DOG50. Design: docs/edge_cashout.md.
2. **Paper trading forward test** on the VPS: 4 frozen rules, live ledger + nightly lookback. Read monthly, with
   ≥ 30 settled trades per rule before any verdict.
3. **Public Tennis Odds page + Portfolio** upkeep. Line-shopping forward test via the Portfolio (readout Jan 2027).
4. **Open on the owner:** `ODDSPAPI_KEY` + allow oddspapi.io / api.oddspapi.io (DK Challenger lines test). Optional:
   ask GitHub Support to purge the orphaned commit ae08bf5.

**Roles.** Each role edits only its own block. The blocks are kept apart by blank lines so that two PRs don't
conflict (git merges edits that touch different blocks).

- **Lead.** Now: review and merge; the Odds API budget; owner reports; reading the first paper lookback (owner screenshot).
  Next: consolidate the scanner and collector clients; the README. Waiting on: the owner's health-check paste and screenshot.

- **Data.** Now: cash-out study run done (2026-10-28; g0 + g12, all FAIL); aggregates sent to Backtest. Next: the OddsPapi
  test; Kalshi work otherwise paused. Waiting on: the owner's OddsPapi key.

- **Backtest.** Done: cash-out study complete, every gate FAILs (`reports/backtest_cashout.md`): DOG50, DOGL, take-profit,
  MISMATCH50, MISMATCH50-U (unranked players are often the favourite, not a dog); E1 invalid (listing-book placeholders),
  E1r robustness check (post hoc, not counted) also FAILs everywhere. Next: re-run on recorded order books when the Lead
  asks. Waiting on: nothing.

- **Scanner.** Now: paper trading live on the VPS since 2026-10-27 17:34 UTC; cash-out group C0–C4 (owner 2026-10-28)
  built and pre-registered, PR #132. Next: after merge the owner updates the server; watch 429s, the 04:00 UTC lookback and
  the C rules' first exits. Waiting on: Dashboard's contract-test update for the new keys; the owner's health-check paste.

- **Dashboard.** Now: public page Portfolio tab in the folder layout (home › portfolio › strategy), PR open; the Paper tab's
  folder layout merged (#149). Next: check both against the owner's screenshots. Waiting on: Lead review; owner screenshots.

- **Upsets.** Now: page builder + Portfolio upkeep (Polymarket Challengers #111, power de-vig #112 live). The Portfolio ledger
  and month's spend are restored from the live page when the cache is evicted (#129). Now (owner 2026-10-28): "seed loses
  early" — pre-registered (#131); backtest done, gate FAIL on all 3 sub-rules (all −10.3%, qualifiers −8.2%, 3,123 bets).
  Live strategy built (#137): Wikipedia seeds + round proxy, rows "seed" and "seed_q"; trades only in /scores
  tournaments, so empty until about Jan 2027. Real-draw parser test pending en.wikipedia.org on the allowlist. Now (owner
  2026-10-28, MISMATCH50): pre-match Elo rank export for Backtest (`upsets/elo_ranks.py`, #141/#142, unranked reasons #145;
  Data runs it), plus a live-rank table `current()` (#144; Lead: live loads from 2010, backtest stays on 1990, a known
  gap of a median 2–4 places; Scanner owns the nightly job). Later: the line-shopping forward-test readout in Jan 2027.
  Waiting on: owner to allow en.wikipedia.org in this environment (real-draw parser fixture).


## Done
| # | What | Result | Where |
|---|---|---|---|
| 1 | Core math | Fee model (per-series fee_type/multiplier), true arb, swing-lock quote, max lock price; worked example reproduced (lock +$0.83 vs brief's rounded +$0.84; unmatched +$7.74 / −$8.44) | `swinglock/fees.py`, `locks.py`, `tests/test_locks.py` |
| 2 | Config, positions loader, data schema | — | `config.yaml`, `swinglock/{config,positions,schema}.py` |
| 3 | DraftKings + Polymarket research | DK: no sanctioned API, ToU bans bots. Polymarket intl: public APIs, but US users can't trade there. Polymarket US: own read API | `docs/research/other_venues.md` |
| 4 | Backtest engine v1 (synthetic-data tests only) | Align, arb scan, swing sim, metrics, grid, CLI. Not yet run on real data | `swinglock/backtest/` |
| 5 | Kalshi API research | see doc | `docs/research/kalshi_api.md` |
| 7 | Walk-forward gate + findings skeleton | `walkforward.py` (monthly folds, purged expanding window, match-clustered bootstrap CI); 37 tests, synthetic only, not run on real data | `swinglock/backtest/walkforward.py`, `reports/backtest_findings.md`, phat-d0/Tennis_Model#2 |
| 8 | Scanner v1 | REST polling, discovery (95–96 open matches across 6 series), effective ask/bid with depth, arb + lock alerts with dedup/re-alert, `state.json`, read-only test. Live pass 2026-10-24 09:14 UTC: best combined ask $1.00, no arb. ~0.22 req/s steady state | `swinglock/scanner/`, `docs/scanner_live.md`, phat-d0/Tennis_Model#3 |
| 9 | Dashboard v1 | Stdlib server + static page (no CDN), alerts / markets / positions, stale + offline banners; Lead-verified at 390×844 and 1280×800 light/dark on real scanner output, no errors or overflow | `swinglock/dashboard/`, phat-d0/Tennis_Model#5 |
| 10 | Dashboard filters | Search, phase filter, "No market" group; 61 tests | phat-d0/Tennis_Model#8 |
| 11 | Kalshi collector + backfill | Read-only client (throttle, 429 backoff, gz raw cache → resumable), normalizer (effective ask/bid, no trade/mid), historical split handled; trial 3 ATP matches → 4,888 quote rows, winners correct. Odds API research (0 credits) | `swinglock/collectors/`, `docs/data_*.md`, `docs/research/odds_api.md`, phat-d0/Tennis_Model#9 |
| 12 | Candle carry-forward check | Valid: candles are written on quote changes (live check 140/144 matches); `data.max_carry_s` cap = 1800 s | phat-d0/Tennis_Model#11 |
| 13 | VPS deploy | Docker compose (scanner + dashboard; recorder and Caddy as profiles), systemd, logrotate; owner setup ~20 min | `deploy/`, `docs/scanner_deploy.md`, phat-d0/Tennis_Model#13 |
| 14 | Backfill work order + batch candles | Recent ATP+WTA first; shared candle calls for post-cutoff markets (~3 matches/call; cap = requested candles) | phat-d0/Tennis_Model#15 |
| 15 | Order-book recorder | 10 s snapshots of all open match books (top-5 depth), daily parquet; trial: 90 matches, min combined $0.99, nothing below fees | `swinglock/collectors/recorder.py`, phat-d0/Tennis_Model#17 |
| 16 | Network-outage handling | Backfill pauses and retries instead of saving quote-less matches | phat-d0/Tennis_Model#19 |
| 17 | Live score recording | Recorder logs set/game/point state every 60 s via `/live_data/batch`, A/B mapped, change-only | `docs/data_live_score.md`, phat-d0/Tennis_Model#20, #21 |
| 18 | Backfill checkpoint | 1,000 recent ATP/WTA matches, 1.80 M quote rows; 3.9% not started (fair prices sum to $1) | `docs/data_inventory.md`, phat-d0/Tennis_Model#23 |
| 19 | Fair-price settlement end to end | Normalizer fills settle_a/b (#25); backtest settles not-started matches at fair prices instead of dropping them (#26) | phat-d0/Tennis_Model#24, #25, #26 |
| 20 | Findings report v1 + leg-age arb filter | `reports/backtest_findings.md` answers the owner's question (no edge on 6 months ATP/WTA); `arb_max_leg_age_s` for a stale-leg-free arb count | phat-d0/Tennis_Model#37 |
| 6 | Team set up | 4 role sessions started 2026-10-24 on `team/*` branches (IDs in `docs/team/lead.md`) | phat-d0/Tennis_Model#1 |

## Findings so far (PRELIMINARY: 1-min candles, no depth; run locally by Data, aggregates only)
**2026-10-24, group 0 = 6 months of ATP+WTA (4,686 matches, closes 2026-04-24 → 10-24; 5.09 M aligned
observations, 12% live; 161 fair-price settlements included via settle_a/b):**
- **True arb:** combined < $1 before fees in 2.46% of observations (0.99: 109,629; 0.98: 13,821;
  ≤ 0.95: 127). After fees: 98 episodes in 40 matches at 0¢ (26 in 18 at 1¢), median one candle, sum of
  1-contract profits $2.49, depth unknown. The top ones are stale pre-match quotes (NAKBAE 21¢; PELMAN
  13¢ used a *carried* leg; CHOVAN 13¢ with zero volume). **98 is an upper bound**: the 1800 s carry cap
  can pair a stale leg with a fresh one. Read: no executable true arb.
- **Stricter arb count (`arb_max_leg_age_s`, both legs' asks changed within N s):** 0¢: 98 → 40
  episodes (300 s) → 35 in 26 matches (60 s), $1.32 total 1-contract profit; 1¢: 19 in 15 matches
  ($0.77) at either setting. All single-candle, depth unknown. It removes carried-leg cases (PELMAN)
  but not wide stale offers that tick by 1¢ (NAKBAE 21¢, CHOVAN 13¢: zero volume, 3 days pre-match).
  Conclusion unchanged: ~$1 of one-contract profit in 6 months of ATP/WTA is not a tradeable edge.
- **Swing grid:** every rule negative. Best X=0.20/Y=0.90: 4,509 trades, 48.8% locked, −$1,374 at 0¢
  (−$0.30/trade), −$2,023 at 1¢.
- **Walk-forward: FAIL, 0 of 6 folds positive** (May–Oct). OOS 4,432 trades: mean −$0.32/trade
  (95% CI −0.37 to −0.28) at 0¢, −$0.47 (CI −0.52 to −0.43) at 1¢.
- `entry_phase: live`: WF FAIL 0/6, OOS mean −$0.27 (0¢) / −$0.43 (1¢).
  First hour of play only (window 0–60 min): WF FAIL 0/6, OOS mean −$0.27 / −$0.42; 3,108 OOS trades.
- **Full Challenger, group 1 (8,333 matches: ATP Challenger 6,667 + WTA 125 1,666; closes 2026-04-24 → 10-24;
  3.56 M aligned obs, pre 2.44 M / live 1.12 M; 150 fair-price settlements):** combined < $1 before fees in
  2.11% of obs (0.99: 63,507; ≤ 0.95: 166). After fees: 112 episodes in 59 matches at 0¢ ($4.30 total
  1-contract profit); 47 at 1¢ ($2.53); leg-age 60 s: 50 episodes ($2.09). The top hits (SAKMUL 34¢, ZAKBOU, MONAND) were crossed historical candles
  (ask < bid; 84 candles, 5 markets, 2026-05-13 11:00–15:00 UTC). **After the guard (phat-d0/Tennis_Model#46),
  re-normalized (8,349 matches):** 106 episodes / 57 matches, $2.89, best 28¢ at 0¢; 40 / $1.25 at 1¢;
  leg-age 60 s 47 / $1.18, best 11¢. Leftovers are artefacts: TONBRO 28¢ (stale pre-match quote) and
  POLSTR ≤ 11¢ (inside the 05-13 glitch window, not crossed; no date exclusion added). ATP/WTA unchanged
  (no crossed candles). Swing: best first/0.20/0.90 −$3,031 at 0¢ (8,156 trades, 46.8%
  locked), −$4,242 at 1¢. **Walk-forward FAIL 0/6**: OOS 7,748 trades, −$0.39/trade (CI −0.42…−0.35) at 0¢,
  −$0.53 at 1¢. Live-only: 0/6, −$0.32 / −$0.47. First hour: 0/6, −$0.30 / −$0.45. Interim read (3,000) superseded.
- **Answer:** on the research set (13,019 matches, groups 0+1, Apr → Oct 2026, 1-min candles), neither
  true arbs nor swing locks have an edge after fees and the ask spread. The gate fails on sign in every
  fold and variant, not just sample size. Order-book history (recorder on the VPS) is the remaining test.

## Next steps
Superseded by the Master plan above (2026-10-28). The earlier list (backfill, backtest, collectors) is done; its remaining
Lead items, client consolidation and README, are in the Lead's row.

## Second project: early-round upsets (ATP + WTA)
Plan, method, gate and data blockers: `docs/upsets_plan.md`. Code: `upsets/` (Lead).
- Status 2026-10-25: pipeline built and tested on synthetic data (122 tests); **no real-data result yet**.
- 2026-10-25: the owner allowed tennis-data.co.uk and added `ODDS_API_KEY`. It's the **free plan** (~500
  credits/month, no historical odds), so there's no DraftKings history; Bet365/Pinnacle closing odds stand
  in for DraftKings. **Odds API budget (key used only by this project, owner 2026-10-25): ≤ 400 credits/month, never below
  a balance of 50.** **DraftKings history test (owner 2026-10-26: "let's test on draftkings odds"):** the owner
  upgrades to the 20K plan (~$30/month). One-off pull budget **≤ 15,000 credits, floor 1,000**, covering
  Slams 2020+ and 1000s 2024+, rounds 1–2, `bookmakers=draftkings,pinnacle`. Upsets builds a dry-run planner
  first, and the Lead approves the estimate before any paid call. Odds data is never committed. Spent by Upsets/Data only, each spend logged in docs/data_inventory.md. **Owner 2026-10-26: use up the free key's ~491 credits first
  (floor lowered to 10 for this key) on live DK + Pinnacle pre-match odds (`upsets/dk_live.py`, starts when a tennis
  key goes active), then ask again.** The owner then plans to switch `ODDS_API_KEY` to their shared paid plan (also
  used by soccer/baseball). The DK history pull (~13k) needs a fresh owner OK on a budget and a floor for that shared key. **Update (owner 2026-10-26):** the key is now the shared plan
  (balance ≈ 10,906). **Reserve 5,000: no tennis call may take the balance below it.** Approved: DK history for the
  **250/500 tier only** (budget ≈ balance − 5,000 − 481 for dk_live ≈ 5,400; listings first, then 6 h cells, else 8 h,
  else most recent events first). dk_live is capped at 481. Slams/1000s (~14–15k more) wait for an owner decision
  (a 100K upgrade was suggested). Run by the Upsets role (session in docs/team/lead.md).
- **Blocked (2026-10-25 17:37):** tennis-data.co.uk's Cloudflare blocks the cloud container's IP (403
  "you have been blocked"; not worked around). The owner downloads the ATP + WTA xlsx files for 2015–2026
  by hand. The Limited network policy also denies api.the-odds-api.com, so it needs adding.
- **Kalshi preview (2026-10-25, `reports/upsets_kalshi_preview.md`): no edge.** The test bets every early-round
  underdog against a ≥ 75¢ favourite at the closing ask with the fee. ATP+WTA: 688 bets, −15.7% ROI
  (CI −29% to −1%); WTA −32.5%; ATP +4.0% (CI −18% to +29%, noise). Challenger+WTA 125: 1,151 bets, −16.7%
  (CI −27% to −6%). Underdogs win less often than their price implies (favourite–longshot bias).
- **Phase A done (phat-d0/Tennis_Model#58):** in rounds 1–2, seeds lose to unseeded players 29.7% (ATP) /
  30.1% (WTA) of the time (2010–2025). Elo expects 27.5% / 28.4%; the gap is mostly qualifiers, and at
  Slams seeds lose less than Elo says. These are base rates, not an edge (no odds). **Next: Phase B**
  (`upsets/kalshi_elo.py`: Elo vs Kalshi closing prices; Upsets writes it, Data runs it).
- **Phase B code merged (phat-d0/Tennis_Model#60), 149 tests.** The Lead found a lookahead issue: an unjoined later
  round could sort before a joined earlier round. It's fixed by `round_monotone()`, with a test. Waiting on a
  Data run over kalshi_g0 (Apr 24 → Oct 24).
- **Phase B result (phat-d0/Tennis_Model#63, `reports/upsets_findings.md`): no edge, gate FAIL.** Elo vs Kalshi
  closing asks on early-round underdogs, out of sample: 108 bets, −15.2% (CI −38% to +7%); ATP +2.7% (61), WTA −41.0% (47).
  The market is better calibrated (log loss 0.5845 vs model 0.6157). The model over-rates underdogs (35.5% vs
  31.7% realized), and the bigger its "edge", the worse the ROI. **Upset study status: answered (no) on Kalshi.**
  The only open test is DraftKings' own prices, which needs the paid Odds API month (~$30, owner's call);
  the Lead expects no edge there either (DraftKings' margin is higher).
- **Results data (2026-10-25):** Jeff Sackmann's repos now return 404. The owner forked the archival
  mirror `phat-d0/tennis-sackmann-archive` (CC BY-NC-SA 4.0, non-commercial, attribute Sackmann; never
  commit the CSVs). It covers ATP/WTA 1968 → tournaments starting by 2026-05-25, with seeds, ranks, rounds
  and scores, but no odds. Public, so it's an anonymous git clone (~900 MB). Upsets is on Phase A (loader,
  Elo, seeded-player base rates) and Phase B (Elo vs Kalshi closing prices, run by Data). DraftKings
  history still needs the paid Odds API month (~$30), so the owner decides.
- Next: download 2013–2026, calibration table + walk-forward, `reports/upsets_findings.md`.

## Third question: penultimate-set winner (owner 2026-10-26)
Question: does the winner of the penultimate set win the match, beat the odds, and does it differ when they
were the pre-match underdog?
- **Results only (Lead, Sackmann 1991–2026, tour level):** in matches that reach a deciding set, the player who
  levelled wins the decider 53.1% (ATP bo3, n=28,828), 54.6% (ATP bo5, 3,462), 53.1% (WTA, 27,120). That's
  +~3 pp on top of ranking for both favourites (≈62%) and underdogs (≈44–47%). "All matches" (83–85%) is
  inflated by straight sets.
- **Price test:** Kalshi per-set markets (`KXATPSETWINNER-…-N`) have `close_time` = set end, which gives the
  match ask at the start of the decider. Data builds a `sets` table; Upsets writes `upsets/decider.py` +
  `upsets/penultimate.py`.
- **Kalshi price test (Data run 2026-10-26, kalshi_g0, 0 requests): the effect is real but priced in, so no edge.**
  1,423 deciders: the penultimate-set winner won 54.8% vs an average ask of 53.8% (55.2% break-even with the fee).
  ROI −0.7% at 0¢ (CI −5.0% to +3.7%), −2.4% at 1¢; other side −7.3%. Pre-match favourite who levelled: 65.8%
  vs 64.1% ask (+0.5%); underdog who levelled: 44.4% vs 44.0% (−2.4%). Excluding bad set times (14 impossible
  + 24 > 180 min): 1,385 bets, −0.9% / −2.7%. A guard is going into decider.py / match_path.py.
- **Widened by the owner (2026-10-26): "match path" time series.** For each match: the original (pre-match)
  favourite's price at the start, after each set end, and in-match min/max; the number and timing of favourite
  flips (50¢ crossings with hysteresis); and whether the original favourite wins. Aggregates by set path and by
  flips, an average-path table for a chart, set-end price calibration and ROI, and 3 example timelines (to the
  Lead only, never in git). Code: `upsets/match_path.py` (Upsets); data: Data's `sets` collector.
- **Match-path result (phat-d0/Tennis_Model#75 rerun, 2026-10-26, 0 requests):** original favourite (higher closing ask)
  wins ATP bo3 66.2% / bo5 71.8% / WTA 69.8% / ATP-Ch 69.0% / WTA125 69.4%. ~50% of matches have ≥ 1 in-play favourite
  flip; 75% of first flips come in set 1 (median ~45 min). After 2+ flips the original favourite wins ~60%; if the other
  player is market favourite at the decider start, 37% (ATP) / 40% (WTA). Deciders: the favourite won the penultimate set →
  64.9% / 66.6%; lost it → 54.9% / 58.7%. Set-end prices are well calibrated; buying at the ask + fee is about −1% to −3% (no
  reliable edge). Penultimate winner post-guard: −1.2% at 0¢ (1,359 bets). Reports: `reports/upsets_match_path.md`,
  `reports/upsets_decider.md` (Data PR). The owner got charts and 3 example timelines privately.
- Results only (Sackmann 2010–26, ranking favourite): the favourite wins 63.8% (ATP bo3) / 64.7% (WTA) / 72.2%
  (ATP bo5). After losing set 1 they win 28.3% / 26.8% / 41.4%; after winning it, 87–88%.
- **DK history code merged (phat-d0/Tennis_Model#67):** dry run ≤ 13,073 credits (95 key-events; 6 h snapshot
  cells; price ≤ 6 h before start). It waits on the owner's 20K upgrade, then a Lead OK for listings (≤ 683)
  and then for odds.

## Bet tracker (owner 2026-10-26)
Private claude.ai page "Tennis Bet Ledger": https://claude.ai/artifact/J1ZK24oNPbxTssTMpfvP6o (owner only). Logs hand-placed
bets (American/decimal/Kalshi ¢ odds, Kalshi taker fee auto-filled), settles Won/Lost/Void, and tracks P&L, ROI, record,
closing-line value, cumulative P&L, and breakdowns by book and tag. Data lives in the page's own store (`bets` collection,
read/write Editor+ only), not in git. Read-only: it never places bets.

## Tennis Odds page on GitHub Pages (owner 2026-10-26)
The owner asked for a public phone page like the soccer app, refreshed every 3 h. Plan and data contract are in `docs/site_plan.md`.
- **What it shows:** DraftKings + Pinnacle odds, margins, the fair chance, an unproven Elo, and the findings. **No Kalshi data.**
- **Credits:** capped at 600 a month, and never below the 5,000 reserve. This replaces dk_live and its 481 cap.
- **Owners:** Upsets builds `upsets/site.py`, Dashboard builds `site/`, Lead writes the workflows.
- **Owner's setup:** the `ODDS_API_KEY` Actions secret is added; Pages → Source "GitHub Actions" is still to do.
- **DK history pull (250/500s):** done. 1,646 credits spent, balance 9,258. 24 of 62 tournament-years have history:
  Beijing from 2024, Doha/Dubai from 2025, the rest 2026 only. That gives 434 round 1–2 matches; Data supplies
  results for the 12 events from Jun–Oct 2026.
- **DK 250/500 study result (#86, PRELIMINARY): no edge.**
  - Every early-round dog: −18.7% at DraftKings (417 bets), −15.6% at Pinnacle.
  - Margins: DK 4.84%, Pinnacle 2.82%.
  - Elo walk-forward: FAIL.
- **Owner 2026-10-26: plan upgraded to 5M credits/month** (still shared with soccer ≈ 5k/month and baseball), "we don't have to
  skimp". **Approved: DK history for Slams + 1000s** (Upsets), with 3 h cells instead of 6 h for prices closer to the start
  (~25–30k credits; per-job cap 40k; the 5,000 floor stays). The page's monthly cap goes from 600 to 3,000 (still every 3 h).
- **Page is live: https://phat-d0.github.io/Tennis_Model/** (2026-10-26 05:07 UTC).
  - Merged: UI #85/#92, builder #89/#90, publish #91.
  - First run: ok, 29 matches, 3 credits.
  - Refresh is every 3 h, capped at 3,000 credits a month; the balance is never published.
- **Slams + 1000s DK pull: done.** 17,563 credits, plus a 506-credit 250/500 top-up after a qualifying-week fix in `needed()`;
  balance ≈ 4.98M.
  - Preview (5,897 Sackmann-resolved bets): dogs −9.3% at DK, −5.3% at Pinnacle.
  - Margin DK 5.06% vs Pinnacle 2.71%.
  - Log loss: Pinnacle 0.5566 < DK 0.5583 < Elo 0.5867. Elo walk-forward FAIL (2,313 OOS, −14.6%).
  - `reports/upsets_dk_all.md` waits on Data's Jun–Oct results.
- **Portfolio tab** (owner asked Upsets directly; phat-d0/Tennis_Model#96): $10 automatic paper trades for 3 rules (Elo edge ≥ 5%,
  DK beats Pinnacle-fair ≥ 1%, every dog as a control), settled only by The Odds API `/scores` (2 credits a key, inside the 3,000
  cap). It covers only the tournaments `/scores` covers, so the live ledger stays empty until about Jan 2027. The ledger lives in the
  Actions cache (lost if the cache is evicted). The backtest view shows aggregates only (Sackmann-resolved). In-sample at the power
  de-vig (since #112): line 205 bets +9.2% vs +8.0% expected; model −12.7% vs −10.8%; dogs −10.4% vs −12.0%. Not a result yet.
- **Closing-price pull (C): done.** 4,297 snapshots, 42,960 credits; balance 4,938,958.
- **DK all tiers at the close (#99): no edge.** Dog ROI −11.2% against −10.9% expected at Pinnacle-fair, on 6,655 matches. DK's margin is
  5.16%, mostly on the dog. Elo walk-forward FAIL (−15.3%, 2,426 OOS bets). Drift report (#100): DK sits static in the last 3 h
  while Pinnacle moves. Name aliases are in (#95).
- **Line shopping (A, #101, merged):** the pre-registered gate PASSES (379 OOS bets, +6.4%, CLV +3.7%), but it is
  **fragile**:
  - The CI runs −4.5% to +18.1%.
  - With the books within 5 points it is +0.9%, CLV −0.2%. The profit rests on about 40 big-disagreement bets that look like stale DK lines.
  - The forward test is the Portfolio tab's "DK vs Pinnacle" strategy.
  - Not an edge until it holds up live.
- **Elo upgrades (B, #103): no edge.** Best variant (+fatigue+serve) log loss 0.5755, against 0.5859 for the current Elo and 0.5552
  for Pinnacle. Every variant is worse than Pinnacle in every season, and all lose 11.5–14.6% at DK walk-forward (CLV −9 to −10.5%).
  A QF-as-qualifying lookahead in the fatigue feature was caught and fixed. The page model is unchanged.
- **Later on 2026-10-26 (owner asks, all done):**
  - Page model switched to tuned Elo + serve/return (#106).
  - Line-shopping drawdown = luck on a thin edge (#108).
  - Private **Tennis Backtest Explorer**, every bet for 20+ strategies, owner-only: https://claude.ai/artifact/3bDnTdzVARrgthoU8GHNVC.
  - Polymarket intl Challenger/WTA 125 section on the page (#105, #107, #111; ~108 matches, 12 requests/build, no key).
  - Portfolio and the page's fair chance on the **power de-vig** (#112). Line backtest is now 205 bets, +9.2% realized / +8.0% expected (in-sample).
  - Hetzner + Tailscale deploy (#109): **LIVE 2026-10-27**. The scanner, dashboard and recorder run on `tennis-scanner` (Tailscale
    only), watching ~109 markets with Challengers + WTA 125 included. Windows browsers need secure DNS off for MagicDNS.
- **Paper trading (owner 2026-10-27): engine merged (#116), server update pending.** Automatic Kalshi paper trading replaces the
  owner's positions (`positions.json` = `[]`).
  - 4 pre-registered rules (`docs/scanner_paper.md`): P1 X0.20/Y0.90, P2 0.40/0.95, P3 0.30/0.94 live-only, P4 0.30/0.94 pre-only.
    Mode "first", 100 contracts capped by depth, fills at the ask + taker fee. Expected result: **−3 to −5¢ per contract**;
    a rule clearly > 0 over ≥ 30 settled trades would be the surprise.
  - Live engine in the scanner, ledger `data/paper/ledger.jsonl`. Nightly lookback (systemd timer ~04:00 UTC) runs the same RULES
    through `swing.simulate` over recorded books at 0¢/1¢ → `data/paper/lookback.json`. Everything stays on the server.
  - **Lead reading rule (pre-registered 2026-10-27):** start-up entries (trades with `entry_ts` = `paper.since`, i.e. matches already
    listed when paper trading began, entered at their current price) are reported on a separate line and excluded from the headline.
  - Backtest confirmed the rules match its swing sim. Dashboard **Paper tab merged** (#118; `contracts` per rule from #119): P&L by rule
    with per-contract figures, start-up entries split out, trades list, nightly lookback at 0¢/1¢ with a cumulative chart. 281 tests.
  - **Running on the server since 2026-10-27 17:34 UTC** (owner re-ran bootstrap; Paper tab checked from the owner's screenshot).
    First lookback ~04:00 UTC 10-28.
- **Incident 2026-10-27 (Scanner): Kalshi-derived paper ledger pushed to the public repo.** Commit ae08bf5 on `team/scanner` holds
  `data/paper/ledger.jsonl` (167 lines from the dry run). The file was removed in e61df0d and `data/paper/` is gitignored, but the
  commit stays reachable while the branch exists. No PR from that branch has been merged, and the repo has no forks. **Owner deleted
  `team/scanner` 2026-10-27**; Lead checked that no branch or PR ref contains ae08bf5. GitHub still serves the orphaned commit by its full
  SHA until its garbage collection (not linked from anywhere); a full purge needs GitHub Support. Scanner recreates the branch from main. The work was redone on the clean `team/scanner-paper` (#116,
  ancestry checked). Rule for every role: stage explicit paths, never `git add -A`/`.` with data present; `tests/test_scanner_paper.py`
  fails if anything under `data/` is tracked.
  - Dashboard fixes: the arb tile only counts arbs above the alert threshold; WTA 125 gets its own label.
  - OddsPapi test of DK Challenger lines waits on the owner: `ODDSPAPI_KEY` + allow oddspapi.io / api.oddspapi.io.
- **Elo upgrades (B, #103): no edge.** Best variant (+fatigue+serve) log loss 0.5755 vs current Elo 0.5859 vs Pinnacle 0.5552;
  every variant loses 11.5–14.6% at DK walk-forward. The page now runs tuned Elo + serve/return (#106).
- **Line-shopping drawdown (#108):** luck both ways on a thin edge; realized = expected over 328 bets. The Portfolio moved to the
  power de-vig (#112).
- **Challengers on the page (#111):** Polymarket intl books for ATP Challenger / WTA 125, about 12 requests a build.
- **Private Tennis Backtest Explorer** (owner-only claude.ai page): https://claude.ai/artifact/3bDnTdzVARrgthoU8GHNVC. It holds every bet
  behind these studies; the data is embedded in the page, never in git.
- **Status:** jobs A, B and C, the DK report, the Elo switch, the drawdown report, Challengers and the de-vig are done. Next:
  a durable home for the Portfolio ledger, then the line-shopping forward-test readout (Jan 2027). New research ideas need the owner.
- **Queued (owner 2026-10-26), Upsets (all three done: C #100, A #101, B #103):**
  - **(C) Closing-price snapshots.** All tiers, cap 50k credits.
  - **(A) Line-shopping test.** Bet DK only when its odds beat Pinnacle's de-vigged price by t. 0 credits, pre-registered, walk-forward,
    scored on ROI, expected ROI and CLV vs Pinnacle's close.
  - **(B) Elo upgrades.** Margin of victory, inactivity decay, K/surface tuning, fatigue, serve/return. Judged on log loss vs Pinnacle and
    walk-forward. The public page's model changes only if a variant wins out of sample (Lead approves).

## How to continue in a new session
Read `CLAUDE.md`, this file, and your brief in `docs/team/`. Check open PRs into `main` and the
`team/*` branches. The Lead's session ID and the role session IDs are in `docs/team/lead.md`.
