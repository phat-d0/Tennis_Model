# Fallen favourite: pre-registration

**Registered 2026-10-28, before any fallen-favourite number was computed.** The owner's question (via the Lead): for
the original favourite, banded 60–80% and ≥ 80%, **does buying it when its price drops to 50¢ beat buying it at
the start?** Code: `swinglock/backtest/favdip.py`. Results will go in `reports/backtest_favdip.md` (aggregates only;
Kalshi data is never committed). Any change to this design after the first run gets a dated entry under
"Amendments", with the reason.

Data: the research groups g0 (ATP/WTA) and g12 (Challenger/WTA 125), 1-minute candles carried forward
(≤ 1,800 s), as-of aligned with 60 s staleness. 0 Kalshi requests. Data runs it after the merge.

## Definitions
**Formed books only.** A row has a formed book when ask_a + ask_b ≤ $1.05. Listing-time placeholder books
(median ask_a + ask_b $1.84 / $1.88 at a match's first pre-match row; see docs/edge_cashout.md amendment 5)
are never used, either to pick the favourite or to enter.

- **Original favourite:** the player with the higher ask at the **last pre-match row with a formed book**
  (phase `pre`, i.e. before `scheduled_start`). A tie means no favourite, and the match is excluded. So are matches
  with no formed pre-match row or no `scheduled_start`.
- **Band** by that ask: **60–80** = [0.60, 0.80) and **80–97** = [0.80, 0.97] (gated). **50–60** = [0.50, 0.60) is
  context only and isn't gated. Favourites above 0.97 are excluded.
- **START:** buy the favourite at that row's ask. Hold to settlement.
- **DIP50:** buy the favourite at the **first live row** (phase `live`, after `scheduled_start`) with a formed
  book where its ask is ≤ 0.50. Hold to settlement. If the dip never happens, there's no entry.
- **Descriptive only:** DIP45 and DIP40 (the same rule at ≤ 0.45 and ≤ 0.40). DIP50 is also split by whether the
  dip came before or after the end of set 1. Set 1 ends at the Kalshi set-winner `close_time` of `set_no` 1. This
  is ATP/WTA only; Challenger/WTA 125 has no set markets, and those rows are labelled "no set-1 data".

## Fills, sizing and settlement
- Fill at ask + slippage (0¢ and 1¢), plus the Kalshi taker fee rounded up per order. **Never mid or last.**
- 10 contracts (`backtest.contracts_per_entry`), capped by the ask depth when it's known. A row with known
  depth ≤ 0, or an ask outside (0, 1), is not an entry. For a dip, the search moves on to the next qualifying row.
- P&L = contracts × settlement − entry cost. The settlement is 1/0 or the fair price for a not-started match
  (`settle_a/settle_b`), as in every other study.
- No lookahead. The favourite and both entries use only their own aligned row. Settlement is used only for P&L.

## Report
By band × tier (ATP/WTA vs Challenger/WTA 125), at 0¢ and 1¢. CIs are 95% bootstraps that resample whole matches.
- **START:** n; win rate (mean settlement) vs mean entry ask and mean all-in price (calibration); ROI; P&L per
  contract.
- **DIP50** (and DIP45/DIP40, descriptive):
  - the share of favourites that ever dip to the level;
  - n; win rate vs mean entry ask and all-in; ROI; P&L per contract.
- **Paired:** DIP50 vs START on the matches where the dip happened (same favourite, both entries), per contract.
  **This pairing selects START's bad matches** (the favourite was losing when it dipped). The owner's comparison
  is the unconditional ROI of each rule above; the paired table is context.
- **Minutes from `scheduled_start` to the dip:** median and quartiles.
- **The DIP50 set-1 split** (descriptive).

## Gate
DIP50 **per gated band** (60–80 and 80–97, each band pooling the tiers in the run) is a fixed rule (no parameter
is chosen), on absolute P&L, by calendar month of the match's first observation. Every month is out of sample.
The rule PASSes only if all of these hold:
- ≥ 4 months;
- positive in ≥ ⌈0.75 × months⌉ months at 1¢;
- total P&L > 0 at both 0¢ and 1¢;
- ≥ 30 entries (each entry is a trade).

START is a baseline and isn't gated. DIP45, DIP40, the 50–60 band and the set-1 split aren't gated.

## Expectation (registered before any run)
- Earlier work found underdogs overpriced, so favourites at the start may be close to fair. START ROI is
  expected to be about −2% to +1%.
- Set-end prices were calibrated (match-path study, phat-d0/Tennis_Model#73), so a 50¢ fallen favourite should win
  about 50%. Paying the spread and the fee then gives DIP50 an ROI of about −3% to −6%.
- **Expected verdict: FAIL** in both gated bands and both groups.
- What would count as the owner's idea working: a DIP50 win rate clearly above its all-in price (the CI of ROI
  above zero) in either gated band. That would mean fallen favourites are underpriced.

## Amendments
_(none yet)_
