> PRELIMINARY: Kalshi 1-min candles, Apr–Oct 2026, aggregates only; run by Data 2026-10-26.

# Match path: does the original favourite make it out? (Kalshi)

Original favourite = higher closing pre-match ask. p = ask-implied probability (ask_fav + 1 − ask_other)/2. Flip = the market favourite changes (p crosses 0.45/0.55 and stays ≥ 2 min). Set snapshots at set close + 90 s. 1-min candles; aggregates only.

## Coverage

| Tour | Matches | Fair-price settlement | With set rows | Retirement (fair-price set) | Unreliable set close | Set path usable | Deciders (guard failed) |
|---|---|---|---|---|---|---|---|
| ATP | 2,215 | 37 | 2,164 | 75 (excluded) | 97 | 2,052 | 685 (38) |
| ATP-Ch | 6,583 | 82 | 0 | 0 (excluded) | 0 | 0 | 0 (0) |
| WTA | 2,272 | 38 | 2,187 | 90 (excluded) | 125 | 2,054 | 731 (28) |
| WTA team | 53 | 0 | 0 | 0 (excluded) | 0 | 0 | 0 (0) |
| WTA125 | 1,636 | 31 | 0 | 0 (excluded) | 0 | 0 | 0 (0) |

Set paths: complete 2,530, decider 1,416, incomplete (sets missing, e.g. bo5 at 1–1 with set 3 unlisted) 160, inconsistent with the settlement 0; only complete and decider paths are used.

In-play cleaning (both legs ≤ 5 min old, cut at the last set close + 5 min or + 180 min for a decider, nothing after p first reaches 0.99/0.01): in-play min changed in 118 matches, flip count in 68; favourite wins with a raw min < 0.10 that the cleaning removed: 4.

Win rates leave out fair-price match settlements (not started); ROI keeps them at their settle price.

## Original favourite: win rate

| Slice | Matches | Fav won | SE |
|---|---|---|---|
| ATP bo3 | 1,760 | 66.2% | 1.1% |
| ATP bo5 | 379 | 71.8% | 2.3% |
| ATP-Ch bo3 | 6,501 | 69.0% | 0.6% |
| WTA bo3 | 2,181 | 69.8% | 1.0% |
| WTA team bo3 | 53 | 49.1% | 6.9% |
| WTA125 bo3 | 1,605 | 69.4% | 1.2% |

By set path (favourite's view; ATP/WTA with usable sets):

| Format | Path | Matches | Share | Fav won |
|---|---|---|---|---|
| ATP bo3 | LL | 305 | 18.2% | 0.0% |
| ATP bo3 | LWL | 107 | 6.4% | 0.0% |
| ATP bo3 | LWW | 201 | 12.0% | 100.0% |
| ATP bo3 | WLL | 154 | 9.2% | 0.0% |
| ATP bo3 | WLW | 186 | 11.1% | 100.0% |
| ATP bo3 | WW | 726 | 43.2% | 100.0% |
| ATP bo5 | LLL | 21 | 9.9% | 0.0% |
| ATP bo5 | LLWL | 1 | 0.5% | 0.0% |
| ATP bo5 | LLWWL | 1 | 0.5% | 0.0% |
| ATP bo5 | LLWWW | 3 | 1.4% | 100.0% |
| ATP bo5 | LWLL | 1 | 0.5% | 0.0% |
| ATP bo5 | LWLWW | 3 | 1.4% | 100.0% |
| ATP bo5 | LWWLL | 6 | 2.8% | 0.0% |
| ATP bo5 | LWWLW | 2 | 0.9% | 100.0% |
| ATP bo5 | LWWW | 10 | 4.7% | 100.0% |
| ATP bo5 | WLLL | 12 | 5.6% | 0.0% |
| ATP bo5 | WLLWL | 3 | 1.4% | 0.0% |
| ATP bo5 | WLLWW | 3 | 1.4% | 100.0% |
| ATP bo5 | WLWLL | 7 | 3.3% | 0.0% |
| ATP bo5 | WLWLW | 4 | 1.9% | 100.0% |
| ATP bo5 | WLWW | 13 | 6.1% | 100.0% |
| ATP bo5 | WWLLL | 4 | 1.9% | 0.0% |
| ATP bo5 | WWLLW | 1 | 0.5% | 100.0% |
| ATP bo5 | WWLW | 11 | 5.2% | 100.0% |
| ATP bo5 | WWW | 107 | 50.2% | 100.0% |
| WTA bo3 | LL | 352 | 17.1% | 0.0% |
| WTA bo3 | LWL | 124 | 6.0% | 0.0% |
| WTA bo3 | LWW | 243 | 11.8% | 100.0% |
| WTA bo3 | WLL | 151 | 7.4% | 0.0% |
| WTA bo3 | WLW | 213 | 10.4% | 100.0% |
| WTA bo3 | WW | 971 | 47.3% | 100.0% |

Deciders, by who won the penultimate set:

| Format | Penultimate set | Matches | Fav won |
|---|---|---|---|
| ATP bo3 | favourite lost it | 319 | 54.9% |
| ATP bo3 | favourite won it | 296 | 64.9% |
| ATP bo5 | favourite lost it | 20 | 30.0% |
| ATP bo5 | favourite won it | 12 | 75.0% |
| WTA bo3 | favourite lost it | 344 | 58.7% |
| WTA bo3 | favourite won it | 359 | 66.6% |

## Favourite flips (in play)

| Format | Matches | ≥ 1 flip | 0 | 1 | 2 | 3+ | Fav won if ≥ 1 flip | if 2+ flips | if the other player was market fav at the decider start | First flip: median min (IQR) |
|---|---|---|---|---|---|---|---|---|---|---|
| ATP bo3 | 1,760 | 50.1% | 49.9% | 22.7% | 13.0% | 14.3% | 33.1% (881) | 60.5% (481) | 36.6% (145) | 47 (26–77) |
| ATP bo5 | 379 | 42.5% | 57.5% | 16.6% | 9.5% | 16.4% | 34.8% (161) | 56.1% (98) | 25.0% (12) | 78 (37–127) |
| ATP-Ch bo3 | 6,501 | 47.8% | 52.2% | 20.2% | 12.7% | 14.9% | 36.0% (3,106) | 62.1% (1,791) | — (0) | 44 (25–74) |
| WTA bo3 | 2,181 | 48.5% | 51.5% | 18.7% | 13.2% | 16.6% | 38.6% (1,057) | 62.6% (649) | 39.9% (193) | 44 (25–76) |
| WTA team bo3 | 53 | 54.7% | 45.3% | 43.4% | 5.7% | 5.7% | 13.8% (29) | 66.7% (6) | — (0) | 7 (4–21) |
| WTA125 bo3 | 1,605 | 50.0% | 50.0% | 19.8% | 15.0% | 15.3% | 39.4% (803) | 64.8% (486) | — (0) | 52 (26–100) |

Set in which the first flip happened (usable sets):

| Format | Set 1 | Set 2 | Set 3 | Set 4 | Set 5 |
|---|---|---|---|---|---|
| ATP bo3 | 75.0% | 11.4% | 13.6% | 0.0% | 0.0% |
| ATP bo5 | 45.0% | 23.8% | 21.9% | 5.6% | 3.8% |
| WTA bo3 | 76.0% | 11.8% | 12.3% | 0.0% | 0.0% |

## Average path of the original favourite's price (for a line chart)

Mean p at the pre-match close and after each listed set (close + 90 s), by final outcome; a set column uses only matches still in play at that set end (n in brackets).

| Format | Outcome | Matches | Pre | Min in play | Max in play | After set 1 | After set 2 | After set 3 | After set 4 |
|---|---|---|---|---|---|---|---|---|---|
| ATP bo3 | fav lost | 595 | 63.4% | 4.3% | 75.9% | 43.8% (564) | 50.6% (261) | — | — |
| ATP bo3 | fav won | 1,165 | 69.0% | 52.6% | 97.8% | 79.1% (1,104) | 65.3% (386) | — | — |
| ATP bo5 | fav lost | 107 | 66.9% | 4.7% | 81.0% | 60.2% (56) | 42.1% (56) | 51.3% (35) | 46.2% (21) |
| ATP bo5 | fav won | 272 | 74.2% | 58.7% | 98.1% | 83.6% (157) | 87.4% (144) | 80.4% (50) | 65.7% (16) |
| ATP-Ch bo3 | fav lost | 2,016 | 63.6% | 4.2% | 76.5% | — | — | — | — |
| ATP-Ch bo3 | fav won | 4,485 | 70.9% | 54.7% | 98.1% | — | — | — | — |
| WTA bo3 | fav lost | 659 | 64.1% | 4.5% | 76.7% | 43.3% (621) | 50.7% (275) | — | — |
| WTA bo3 | fav won | 1,522 | 71.3% | 53.6% | 98.2% | 80.6% (1,410) | 66.7% (453) | — | — |
| WTA team bo3 | fav lost | 27 | 59.3% | 3.2% | 61.8% | — | — | — | — |
| WTA team bo3 | fav won | 26 | 62.6% | 55.6% | 98.4% | — | — | — | — |
| WTA125 bo3 | fav lost | 491 | 63.9% | 3.8% | 76.6% | — | — | — | — |
| WTA125 bo3 | fav won | 1,114 | 71.9% | 54.2% | 98.2% | — | — | — | — |

## Price test at each set end

Calibration: the original favourite's live p vs how often they won; ROI of buying them (or the original underdog) at the ask + Kalshi fee, 100 contracts. Only matches still in play at that set end (e.g. bo3 after set 2 = 1–1 only).

| Format | After set | p bin | Matches | Mean p | Fav won | Buy fav ROI 0¢ (95% CI) | ROI 1¢ | Buy dog ROI 0¢ |
|---|---|---|---|---|---|---|---|---|
| ATP bo3 | 1 | (0.0, 0.2] | 117 | 13.0% | 12.0% | -16.6% (-53.7% to +26.8%) | -22.3% | -0.2% |
| ATP bo3 | 1 | (0.2, 0.4] | 312 | 30.6% | 29.5% | -9.6% (-25.1% to +6.0%) | -12.3% | -1.3% |
| ATP bo3 | 1 | (0.4, 0.6] | 164 | 47.9% | 48.8% | -2.9% (-18.4% to +11.8%) | -4.8% | -5.8% |
| ATP bo3 | 1 | (0.6, 0.8] | 225 | 73.1% | 71.6% | -4.6% (-12.5% to +3.0%) | -5.8% | -1.3% |
| ATP bo3 | 1 | (0.8, 1.0] | 850 | 90.1% | 89.1% | -2.4% (-4.6% to -0.1%) | -3.4% | -0.3% |
| ATP bo3 | 2 | (0.0, 0.2] | 29 | 15.2% | 0.0% | -100.0% (-100.0% to -100.0%) | -100.0% | +16.7% |
| ATP bo3 | 2 | (0.2, 0.4] | 62 | 29.1% | 38.7% | +24.6% (-14.9% to +63.7%) | +20.6% | -15.8% |
| ATP bo3 | 2 | (0.4, 0.6] | 207 | 52.1% | 53.1% | -2.3% (-14.4% to +10.0%) | -4.0% | -6.8% |
| ATP bo3 | 2 | (0.6, 0.8] | 265 | 67.9% | 66.0% | -5.6% (-13.9% to +1.8%) | -6.9% | -0.6% |
| ATP bo3 | 2 | (0.8, 1.0] | 84 | 88.1% | 91.7% | +2.7% (-4.4% to +8.8%) | +1.6% | -36.0% |
| ATP bo5 | 1 | (0.2, 0.4] | 12 | 33.7% | 25.0% | -30.0% (-100.0% to +40.6%) | -32.0% | +9.7% |
| ATP bo5 | 1 | (0.4, 0.6] | 27 | 51.6% | 25.9% | -51.8% (-79.5% to -17.8%) | -52.7% | +46.4% |
| ATP bo5 | 1 | (0.6, 0.8] | 57 | 71.6% | 68.4% | -7.1% (-23.3% to +8.7%) | -8.3% | +4.1% |
| ATP bo5 | 1 | (0.8, 1.0] | 117 | 90.6% | 92.3% | +0.7% (-4.7% to +5.4%) | -0.3% | -26.3% |
| ATP bo5 | 2 | (0.0, 0.2] | 18 | 12.1% | 11.1% | -16.5% (-100.0% to +107.8%) | -22.7% | -0.1% |
| ATP bo5 | 2 | (0.2, 0.4] | 10 | 29.5% | 10.0% | -68.1% (-100.0% to +8.5%) | -69.1% | +24.3% |
| ATP bo5 | 2 | (0.4, 0.6] | 32 | 50.1% | 40.6% | -22.4% (-52.5% to +11.1%) | -23.9% | +14.0% |
| ATP bo5 | 2 | (0.6, 0.8] | 18 | 70.8% | 66.7% | -8.3% (-39.1% to +20.7%) | -9.5% | +6.9% |
| ATP bo5 | 2 | (0.8, 1.0] | 122 | 94.7% | 95.1% | -0.4% (-4.5% to +2.8%) | -1.4% | -19.6% |
| ATP bo5 | 3 | (0.0, 0.2] | 6 | 11.8% | 16.7% | +27.3% (-100.0% to +362.7%) | +17.9% | -6.8% |
| ATP bo5 | 3 | (0.2, 0.4] | 12 | 32.1% | 25.0% | -27.0% (-100.0% to +44.1%) | -29.2% | +7.2% |
| ATP bo5 | 3 | (0.4, 0.6] | 8 | 50.7% | 37.5% | -29.2% (-77.8% to +37.7%) | -30.5% | +21.1% |
| ATP bo5 | 3 | (0.6, 0.8] | 19 | 71.1% | 42.1% | -42.3% (-71.0% to -12.6%) | -43.0% | +87.6% |
| ATP bo5 | 3 | (0.8, 1.0] | 40 | 90.1% | 87.5% | -4.0% (-15.6% to +5.1%) | -5.0% | +13.0% |
| ATP bo5 | 4 | (0.0, 0.2] | 3 | 11.2% | 33.3% | +169.1% (-100.0% to +528.9%) | +148.0% | -25.9% |
| ATP bo5 | 4 | (0.2, 0.4] | 6 | 26.9% | 33.3% | +16.1% (-100.0% to +139.3%) | +12.0% | -10.9% |
| ATP bo5 | 4 | (0.4, 0.6] | 13 | 51.7% | 15.4% | -71.4% (-100.0% to -30.4%) | -71.9% | +67.8% |
| ATP bo5 | 4 | (0.6, 0.8] | 10 | 70.0% | 60.0% | -16.7% (-59.6% to +26.4%) | -17.8% | +24.7% |
| ATP bo5 | 4 | (0.8, 1.0] | 5 | 91.1% | 100.0% | +8.8% (+4.3% to +13.7%) | +7.7% | -100.0% |
| WTA bo3 | 1 | (0.0, 0.2] | 131 | 13.4% | 13.0% | -11.9% (-49.8% to +28.0%) | -17.8% | -0.9% |
| WTA bo3 | 1 | (0.2, 0.4] | 331 | 30.3% | 30.5% | -5.8% (-20.6% to +10.6%) | -8.7% | -3.2% |
| WTA bo3 | 1 | (0.4, 0.6] | 225 | 49.4% | 44.4% | -14.1% (-27.1% to -1.4%) | -15.8% | +5.0% |
| WTA bo3 | 1 | (0.6, 0.8] | 279 | 72.4% | 77.4% | +4.2% (-2.8% to +10.6%) | +2.8% | -23.5% |
| WTA bo3 | 1 | (0.8, 1.0] | 1,065 | 91.5% | 91.6% | -0.9% (-2.7% to +0.9%) | -1.9% | -13.0% |
| WTA bo3 | 2 | (0.0, 0.2] | 22 | 14.6% | 22.7% | +42.2% (-65.2% to +153.4%) | +33.5% | -10.9% |
| WTA bo3 | 2 | (0.2, 0.4] | 94 | 30.9% | 36.2% | +9.3% (-18.9% to +36.9%) | +6.0% | -10.3% |
| WTA bo3 | 2 | (0.4, 0.6] | 217 | 51.5% | 49.8% | -7.6% (-20.2% to +5.6%) | -9.2% | -1.4% |
| WTA bo3 | 2 | (0.6, 0.8] | 260 | 69.2% | 71.5% | +0.4% (-7.6% to +7.9%) | -1.0% | -13.3% |
| WTA bo3 | 2 | (0.8, 1.0] | 135 | 87.2% | 88.9% | +0.5% (-5.7% to +6.0%) | -0.6% | -21.3% |

## Penultimate-set winner at the decider start

Buy the player who won the penultimate set (who just levelled) at the ask + fee as of the last listed set's close + 90 s.

| Format | Who levelled | Matches | Levelling player won | Mean ask | ROI 0¢ (95% CI) | ROI 1¢ |
|---|---|---|---|---|---|---|
| ATP bo3 | all | 615 | 54.6% | 53.3% | -0.2% (-7.1% to +6.0%) | -2.0% |
| ATP bo3 | pre-match favourite | 296 | 64.9% | 63.1% | +0.6% (-7.0% to +8.3%) | -1.0% |
| ATP bo3 | pre-match underdog | 319 | 45.1% | 44.2% | -1.2% (-12.9% to +9.9%) | -3.3% |
| ATP bo5 | all | 32 | 71.9% | 58.8% | +19.7% (-8.4% to +47.5%) | +17.7% |
| ATP bo5 | pre-match favourite | 12 | 75.0% | 66.8% | +10.1% (-24.7% to +45.5%) | +8.5% |
| ATP bo5 | pre-match underdog | 20 | 70.0% | 53.9% | +26.7% (-9.8% to +66.6%) | +24.5% |
| WTA bo3 | all | 702 | 54.3% | 54.7% | -3.2% (-9.4% to +2.8%) | -4.9% |
| WTA bo3 | pre-match favourite | 359 | 66.6% | 65.3% | -0.1% (-6.9% to +6.7%) | -1.5% |
| WTA bo3 | pre-match underdog | 343 | 41.4% | 43.6% | -8.2% (-18.7% to +3.4%) | -10.2% |

## Notes

- **ATP bo3, after set 2, p in (0, 0.2]: 0 of 29 favourites won** (mean p 15.2%). At those prices about 4 wins would be expected, and 0 of 29 by chance is roughly a 1% event. The WTA cell at the same point is 22 matches with 22.7% won. A likely cause is set-2 `close_time` values that are a few minutes late but still pass the 15-minute guard. The "1–1 + 90 s" snapshot would then sit well into the decider, after the favourite had already gone a break or more down. This hasn't been verified. It could be checked by comparing those 29 snapshots with each decider's length. It doesn't change any conclusion here.
- Example timelines are not part of this report (they go to the owner only).
