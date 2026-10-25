# Early-round upsets: findings

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

## Phase B: Elo vs Kalshi closing prices
Not run yet.
