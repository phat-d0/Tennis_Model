# Early-round upsets: findings

**Answer (2026-10-26): no edge.** Seeds lose early often (~30% of round 1–2 matches against
unseeded players), but prices already reflect it. On Kalshi closing prices, an Elo model of upset
probability predicts *worse* than the market. Betting the underdogs it likes loses money out of
sample, and the bigger the model's claimed edge, the worse the bets. Gate: **FAIL**. The next
real test (DraftKings' own prices) needs DraftKings odds history, which means a paid month of The
Odds API: the owner's call.

## Phase A: base rates from results only (2026-10-25)

**Answer so far:** seeds do lose early often, but about as often as their opponents' strength
says. In rounds 1–2 of tour-level events in 2010–2025, a seed playing an unseeded opponent lost
**29.7% (ATP) / 30.1% (WTA)** of the time, and **42% (ATP) / 46% (WTA)** of seeds were out by
round 2. Elo (pre-match, from 1990) expected 27.5% / 28.4%. The ~2 pp gap is mostly Elo
underrating qualifiers, so it shows a weakness of Elo, not a mispricing. There are no odds in this
data, so it can't say whether a bookmaker misprices these matches. The one price test we have (the
Kalshi preview, `reports/upsets_kalshi_preview.md`) found underdogs *over*priced. "Many upsets" is
what correct prices predict, not an edge.

Data: Jeff Sackmann's tennis_atp / tennis_wta match files (CC BY-NC-SA 4.0), archival fork
`phat-d0/tennis-sackmann-archive`, tournaments starting by 2026-05-25. Full tables:
`reports/upsets_seed_base_rates.md` (`python -m upsets.seeds --root <archive>`). Data notes:
`docs/upsets_data.md`.

### Seed loses (seed vs unseeded, rounds 1–2, void matches left out)
| Tour | Band | Matches | Seed lost | Elo expected | Gap |
|---|---|---|---|---|---|
| ATP | 1–4 | 4,702 | 23.9% | 20.3% | +3.6 pp |
| ATP | 5–8 | 5,750 | 33.5% | 31.1% | +2.3 pp |
| ATP | 9–16 | 2,983 | 29.7% | 28.8% | +0.9 pp |
| ATP | 17–32 | 2,369 | 32.1% | 31.4% | +0.6 pp |
| WTA | 1–4 | 4,793 | 25.9% | 23.1% | +2.8 pp |
| WTA | 5–8 | 5,004 | 32.6% | 31.6% | +1.0 pp |
| WTA | 9–16 | 3,047 | 29.8% | 29.0% | +0.8 pp |
| WTA | 17–32 | 2,357 | 33.5% | 31.7% | +1.8 pp |

Standard errors are 0.6–1.0 pp per row. Seeds 5–8 lose more than 9–16 because most of their
matches are at 250/500 events, where the seeds are weaker relative to the field.

| Tour | Level | Matches | Seed lost | Elo expected | Gap |
|---|---|---|---|---|---|
| ATP | Slam | 3,560 | 20.7% | 22.8% | −2.1 pp |
| ATP | 1000 | 3,155 | 29.9% | 27.1% | +2.8 pp |
| ATP | Other (250/500) | 9,089 | 33.2% | 29.5% | +3.7 pp |
| WTA | Slam | 3,529 | 23.2% | 23.9% | −0.8 pp |
| WTA | 1000 | 1,695 | 32.0% | 28.6% | +3.4 pp |
| WTA | Other | 9,977 | 32.2% | 30.0% | +2.2 pp |

- At Slams (best-of-5 for ATP), seeds lose *less* often than Elo says. Elo ignores the format.
- Against qualifiers and lucky losers, seeds lose 26.2% (ATP) / 27.1% (WTA) vs Elo's 21.0% / 23.0%.
  Against everyone else the gap is +1.5 / +1.0 pp. Qualifiers arrive with match play that Elo
  under-weights.
- Elo built on tour-level files alone is clearly worse: it underrates qualifiers even more, and its
  fitted logit slope is 0.72 (over-confident) vs 0.90 when qualifying/Challenger/ITF matches are
  included. Log loss 0.574 → 0.561 (ATP). The default now includes them.
- By surface, the rates are flat: 29–31% on hard, clay and grass for both tours. They rise slowly over
  time: ATP 25–29% (2010–16) → 30–35% (2017–25); WTA 27–30% (2010–15) → 29–33% (2016–25).

### What this means for the betting question
A gap between the actual rate and Elo is not a gap vs the bookmaker. The market sees qualifier form,
format, injuries and draws that Elo doesn't. The test that counts is model vs price (Phase B, Kalshi
closing asks; DraftKings needs paid Odds API history). Elo's known blind spots (qualifiers, best-of-5)
are things a market would already price.

## Phase B: Elo vs Kalshi closing prices (2026-10-26)

**Answer: the model is worse than the market, so there's no edge.** Gate FAIL.

Run by the Data role on `kalshi_g0` (Kalshi ATP + WTA match markets, Apr 24 → Oct 24 2026; 1-min
candles, no depth) with `python -m upsets.kalshi_elo`. Bet = buy the early-round underdog (lower
closing ask) at the ask with Kalshi's taker fee when model p − break-even ≥ threshold. The
threshold for each month is chosen on earlier months only. Model = Sackmann Elo carried forward
with Kalshi results, calibrated on pre-window Sackmann rounds 1–2 (Elo logit, × best-of-5).
Aggregates only.

### Joins
- 4,537 of 4,694 Kalshi matches (96.7%) have both players matched to Sackmann ids.
- 704 matches are joined to a Sackmann row, so they carry real seeds and ranks. Sackmann ends with
  tournaments starting by 2026-05-25, so joins cover Apr 24 → early June. Winners agree in 99.7%.
- Only 9 joined rows had to be moved later to keep round order.

### Out of sample (walk-forward by month)
| Slice | Bets | ROI 0¢ | 95% CI | ROI 1¢ |
|---|---|---|---|---|
| All | 108 | −15.2% | −38.1% to +7.0% | −17.7% |
| ATP | 61 | +2.7% | | |
| WTA | 47 | −41.0% | | |

- 2 of the last 4 months were positive.
- Every month chose 0.15, the top of the grid: the selection was chasing the largest edges and still lost.

### Fixed thresholds over all months (in-sample, diagnostic)
| Rule | Bets | ROI 0¢ |
|---|---|---|
| Every early-round underdog | 2,095 | −4.3% |
| edge ≥ 0.00 | | −8.5% |
| edge ≥ 0.02 | | −12.6% |
| edge ≥ 0.05 | | −16.1% |
| edge ≥ 0.08 | | −19.5% |
| edge ≥ 0.10 | | −15.0% |
| edge ≥ 0.15 | | −7.9% |

Filtering by the model's edge makes things worse than betting every underdog. Where the model
disagrees with the market, the market is right more often.

### Who prices better (2,054 settled early-round matches)
| | Log loss | Mean p(underdog) |
|---|---|---|
| Market (asks normalized) | **0.5845** | 31.4% |
| Elo model | 0.6157 | 35.5% |
| Realized upset rate | | 31.7% |

- The market is better calibrated on both tours.
- The model is too high on underdogs in every price bin. For dogs priced ≤ 15¢ it says 16.3%; they
  won 8.8%, and the market said 10.1%.

### Seeded favourite vs unseeded underdog (real seeds, Apr 24 → early June)
| Rule | Bets | ROI 0¢ | 95% CI |
|---|---|---|---|
| Every such underdog | 188 | −2.7% | −26% to +22% |
| edge ≥ 0.05 | 65 | −23.7% | |

### Why
- **The market knows things Elo doesn't.** Injuries, recent form, fatigue from the week before,
  conditions, and a favourite's motivation at a small event all move prices and outcomes. Elo
  sees only past wins and losses. A long-shot underdog the market prices at 10¢ is usually long for a
  reason, and Elo, which shrinks toward 50%, rates them too high. That's why the model's
  biggest "edges" are its worst bets.
- **Elo goes stale after early June.** Sackmann's data ends in early June. After that, ratings move
  only on Kalshi's ATP/WTA matches: no Challenger/ITF or qualifying results, and only the matches
  Kalshi listed. This makes the model weaker over the summer and autumn, but it doesn't explain
  the April–June overlap: seeded-favourite bets there lost too.
- **Kalshi's underdogs are already overpriced** (preview: −15.7% for every dog against a ≥ 75¢ favourite).
  Even well-chosen dogs start ~4% behind after the fee and the ask.

### Caveats
- One season-half of Kalshi data, candles without depth, and WTA/ATP splits on ~50 OOS bets each:
  ATP +2.7% on 61 bets is noise. The 95% CI of the whole OOS set still reaches +7%.
- A small lookahead hole was found after this run. An unjoined Kalshi match inside Sackmann's span
  could see a later-round Sackmann result timed before it. It touched at most 3 of 13 such
  in-sample diagnostic bets and 0 OOS bets, so the gate result is unchanged. Those matches are
  now no-read: no Elo update, no bet.
- This is Kalshi, not DraftKings. DraftKings' sportsbook margin on tennis (~4–6%) is a higher bar
  than Kalshi's fee + spread, so an edge is less likely there, not more.
