# Upset preview on Kalshi prices (PRELIMINARY, 2026-10-25)

**Question (owner):** seeded players often lose early. Does betting the underdog in early rounds
make money?

**Answer on 6 months of Kalshi prices: no.** Betting every early-round underdog against a strong
favourite lost about **15–17%** of the money staked. The losses are on both the ATP/WTA tour and the
Challenger/WTA 125 level, and the 95% intervals sit below zero. Underdogs did win early matches, but
**less often than their price implied.** That is the favourite–longshot bias, and Kalshi's taker fee
then makes it worse. The one exception, ATP main tour (+4%), is noise: the interval runs from −18% to +29%.

## Method
- **Data:**
  - ATP/WTA: 4,695 settled Kalshi matches, closing Apr 24 → Oct 24 2026.
  - ATP Challenger / WTA 125: 8,349 settled matches over the same period.
  - Closing quotes: 96.7% and 98.4% of matches respectively.
  - Prices are 1-min candles with no depth.
- **Closing price:** the last ask per side at or before the scheduled start, at most 3 h old.
  **Underdog** = the side with the lower ask.
- **Bet:** buy 100 contracts of the underdog at the ask (also shown at ask + 1¢), with the series'
  Kalshi taker fee. Fair-price settlements of matches that never started are included.
  **No model and no fitting:** this is "bet every underdog in the bucket".
- **Early rounds:** the first two main-draw rounds, taken from Kalshi milestone round labels.
  - Qualifying rounds are reported separately.
  - Labels with no round number are excluded.
  - So are tournaments already under way when the data starts.
- **"Seeded":** Kalshi has no rankings, so a strong favourite (closing ask ≥ 75¢) stands in.
- **Code:** `upsets/kalshi_preview.py` (phat-d0/Tennis_Model#54, #55). The Data role ran it locally;
  only these aggregates leave its container. Run cost: 102 Kalshi requests, once.

## Headline: early rounds, favourite ≥ 75¢
| Slice | Bets | Underdog won | Avg dog ask | Break-even incl. fee | ROI 0¢ | 95% CI | ROI 1¢ |
|---|---|---|---|---|---|---|---|
| ATP + WTA | 688 | 15.1% | 17.4% | 18.4% | **−15.7%** | −29.3% to −0.6% | −20.3% |
| … ATP | 311 | 19.3% | 17.7% | 18.7% | +4.0% | −18.2% to +29.1% | −1.5% |
| … WTA | 377 | 11.7% | 17.2% | 18.1% | **−32.5%** | −50.1% to −15.5% | −36.2% |
| ATP Challenger + WTA 125 | 1,151 | 16.3% | 18.9% | 19.9% | **−16.7%** | −26.9% to −6.0% | −20.8% |
| … ATP Challenger | 847 | 17.1% | 19.6% | 20.7% | −16.1% | −27.9% to −3.7% | −20.2% |
| … WTA 125 | 304 | 14.1% | 16.9% | 17.9% | −18.4% | −39.9% to +4.2% | −22.9% |
| ATP + WTA, early rounds, any favourite | 2,154 | 31.0% | 31.8% | 33.2% | −4.7% | −10.3% to +1.0% | −7.5% |
| Challenger + WTA 125, early, any favourite | 3,941 | 32.7% | 33.1% | 34.5% | −4.2% | −8.4% to −0.1% | −7.0% |

By month (early rounds, favourite ≥ 75¢, ROI at 0¢):

| Month | ATP + WTA bets | ROI | Challenger + WTA 125 bets | ROI |
|---|---|---|---|---|
| 2026-05 | 157 | +4.6% | 166 | −22.1% |
| 2026-06 | 114 | −39.1% | 201 | −16.6% |
| 2026-07 | 127 | −14.7% | 248 | −22.5% |
| 2026-08 | 115 | −2.1% | 102 | +20.6% |
| 2026-09 | 98 | −51.1% | 288 | −16.3% |
| 2026-10 | 77 | +2.1% | 146 | −27.1% |

## Early rounds by underdog price
This compares how often underdogs won with their average ask (ROI at 0¢).

| Underdog ask | ATP | WTA | ATP Challenger | WTA 125 |
|---|---|---|---|---|
| ≤ 15¢ | 14.0% vs 10.4% (+27.9%, n=107) | 5.2% vs 10.1% (**−50.8%**, n=155) | 7.3% vs 11.3% (**−38.8%**, n=219) | 7.4% vs 9.7% (−28.3%, n=122) |
| 15–25¢ | 21.8% vs 20.8% (+0.6%, n=174) | 14.9% vs 21.0% (**−31.2%**, n=201) | 19.5% vs 21.0% (−10.8%, n=522) | 18.5% vs 20.9% (−13.7%, n=162) |
| 25–35¢ | 31.6% vs 30.6% (−0.0%, n=291) | 32.4% vs 30.9% (+2.5%, n=275) | 31.3% vs 30.8% (−2.1%, n=798) | 34.4% vs 30.9% (+8.5%, n=224) |
| 35–45¢ | 40.8% vs 40.8% (−1.8%, n=382) | 39.8% vs 40.6% (−4.4%, n=322) | 40.8% vs 40.5% (−2.3%, n=1,098) | 40.8% vs 40.6% (−2.6%, n=260) |
| 45–50¢ | 45.2% vs 47.7% (−5.0%, n=104) | 46.0% vs 47.9% (−6.5%, n=139) | 45.3% vs 47.8% (−7.2%, n=424) | 48.4% vs 48.1% (−1.1%, n=91) |

How to read this:
- **Near-even and mid-priced matches (25–50¢):** prices are close to fair, and the fee plus the spread
  turns them slightly negative.
- **Long shots (≤ 25¢):** these lose heavily in WTA and Challenger.
- **ATP long shots ≤ 15¢:** the +28% rests on 107 bets, and its CI runs from −30% to +89%. It's
  the kind of slice that looks good by chance when you scan many slices.
- **Qualifying rounds:** worse still. Every tour loses 8–11% overall.

## Caveats
- **Six months is short.** The by-month swings show how noisy a few hundred longshot bets are.
- **Prices:** these are Kalshi prices, not DraftKings. DraftKings' margin is usually larger, which
  would make the result worse, not better.
- **Candles:** 1-min candle asks with no depth, so a real fill may be slightly worse.
- **No rankings:** the ≥ 75¢ favourite approximates a seeded player.
- **Small anomaly:** 33 WTA matches labelled "unknown" had both closing asks above 50¢ (wide or
  stale books). They sit only in the excluded "unknown" group and don't touch the headline.

## What would change the answer
A proper test needs longer history and DraftKings' own prices:
- **Past results:** Jeff Sackmann's ATP/WTA archives (free; the owner forks them).
- **Past DraftKings odds:** The Odds API historical endpoint (paid plan, roughly one month at ~$30).
- **Then:** run the model and walk-forward in `upsets/` (docs/upsets_plan.md).

Since underdogs look overpriced here, the **favourite** side is the one worth checking there. That is
not tested yet: buying favourites at the ask also pays the spread and the fee.
