# Early-round upsets (ATP + WTA): plan and status

**Owner question (2026-10-25):** seeded players often lose early in tournaments. Can a model
forecast upset probabilities well enough to beat DraftKings' odds on the underdog?

## What counts as a yes
"Many upsets" isn't an edge by itself: a 30% underdog *should* win 30% of the time. A bet has an
edge only if the underdog wins more often than DraftKings' price implies **after the book's margin**
(roughly 4–6% on tennis moneylines). Two questions, in order:

1. **Calibration:** in rounds 1–2 with a top-32 favourite, do underdogs win more often than the
   de-vigged market says, and does betting every one of them make money at a real book's price?
   This is the cheapest test of the hypothesis as stated.
2. **Model:** does market + Elo (overall and per surface) + ranking predict upsets better than the
   market alone, by enough to pay the margin out of sample?

Prior research, stated up front: tennis closing odds are well calibrated, and the
favourite–longshot bias usually makes underdogs *over*priced, so betting every dog loses. We
report the result either way.

## Data
| Source | What | Access | Status |
|---|---|---|---|
| tennis-data.co.uk | ATP (2001+) and WTA (2007+) results, round, ranks, set scores, retirements, **closing odds** from Bet365, Pinnacle, best and average | Free yearly xlsx files (`python -m upsets.download`) | **Blocked**: the environment's network policy denies `www.tennis-data.co.uk` |
| The Odds API, live | DraftKings Sportsbook h2h (`bookmakers=draftkings,pinnacle`), 1 credit per call per tournament key | `ODDS_API_KEY` | **Blocked**: key not in the environment; budget not set |
| The Odds API, historical | DraftKings history: Slams since 2020–21, most 1000s since 2024–25; 10 credits per snapshot | same key, paid plan | Needs owner OK on credits (estimate below) |

Tennis on The Odds API is tour-level only (Slams, 1000s, a few 500/250s; no Challenger/ITF), which
fits this question: seeded favourites are at those events.

**DraftKings history estimate:** 2 snapshots a day over rounds 1–2 (≈ 4 days) of each covered event:
4 Slams × 2 tours × 4 days × 2 × 10 credits ≈ 640 credits a year; 1000s ≈ 9 × 2 × 3 × 2 × 10 ≈
1,080 a year. 2020–2026 total ≈ **5–8k credits**. Until then, Bet365 closing odds stand in for
DraftKings (with a 3% haircut on winnings, since DK usually prices worse).

## Method (code in `upsets/`, settings in `config.yaml` → `upsets:`)
- `load.py`: tennis-data → one row per match; void rule = walkover, or retirement/disqualification
  before set 1 is complete (DraftKings' rule).
- `elo.py`: pre-match Elo, overall and per surface (FiveThirtyEight K-factor), ATP and WTA kept
  apart; a test proves a match's own result never affects its ratings.
- `features.py`: favourite = shorter Pinnacle price (else average, else Bet365), so framing never
  uses the result; market probability de-vigged with the power method.
- `model.py`: L2 logistic regression on market logit, Elo diff, surface Elo diff, log rank ratio,
  best-of-5, early round.
- `backtest.py`: season walk-forward. Fit on seasons before Y (after a 2-season Elo burn-in), bet the
  underdog in season Y when p_model × odds − 1 ≥ threshold; the threshold for Y is chosen on earlier
  test seasons only. 1-unit stakes at closing odds; voids return the stake. Baselines: market-only
  model and "bet every candidate".
- **Gate:** ≥ 3 of the last 4 test seasons positive at the 3% haircut, total out-of-sample P&L > 0 at
  0% and 3%, ≥ 200 out-of-sample bets, plus the no-lookahead tests.

Run: `python -m upsets.download` then `python -m upsets.run` → `reports/upsets_findings.md`.

## Synthetic check (2026-10-25, not real data)
On a synthetic market with correct odds and a 5% margin (2 tours × 8 seasons × 1,500 matches), the
"model" made +32.8u on 241 bets at 0% haircut (ROI +13.6%, **95% CI −13.7% to +43.6%**) and placed
no bets at 3%. Betting every candidate dog lost 1.3% at 3%. Lesson: underdog bets at ~5.0 odds are
noisy, and a few hundred bets can show +14% by luck. That's why the gate wants ≥ 200 bets, positive
seasons, and a haircut. A planted 6-point underpricing of underdogs is found (test).

## Betting
Research only. No automated bet placement: DraftKings has no betting API and its terms ban bots,
and the project rule is read-only. If the gate passes, the live step is an alert list ("today's
early-round underdogs where the model's edge at DraftKings' current price clears the threshold")
for the owner to bet by hand, at 1 credit per tournament key per poll.

## Next steps
1. Owner: allow `www.tennis-data.co.uk` in the environment's network settings; add `ODDS_API_KEY`
   with a tennis credit budget and floor.
2. Lead: download 2013–2026, run the calibration table and walk-forward, write
   `reports/upsets_findings.md` (bad results included).
3. If it's close or positive: owner OK for ~5–8k credits of DraftKings history to re-test at DK's
   actual prices; then the live alert list.
