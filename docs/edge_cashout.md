# Cash-out (take-profit) study: pre-registration

**Registered 2026-10-28, before any cash-out number was computed.** Owner's question: "when is the
optimal time to cash out early, and what's the cash-out strategy?" Scope: **take-profit exits only**;
otherwise every position is held to settlement. No stop-losses. The results will go in
`reports/backtest_cashout.md` (aggregates only; Kalshi data is never committed). Any change to this
design after the first run gets a dated entry under "Amendments", with the reason.

## Question
For the same entries, what is an early cash-out worth compared with holding?

    Δ = P&L(sell at the bid when the exit rule triggers) − P&L(hold to settlement)

Δ is 0 for entries whose rule never triggers. Results are reported per contract.

## Entries (selection-neutral)
Neither entry picks a side, so any Δ comes from the exit and not from the entry.
- **E1:** buy **both** players at the match's first aligned observation with phase `pre`.
- **E2:** buy **both** players at the first aligned observation with phase `live`.

`live` means after `scheduled_start`, which can be before the first ball when play is delayed. Matches
with no `scheduled_start` (phase `unknown`) are excluded.

- Size: `backtest.contracts_per_entry` (10, the same as the findings report), capped by ask depth when
  it is known.
- Fill: ask + slippage, plus the Kalshi taker fee rounded up per order (`FeeModel.fee`).
- An entry needs 0 < ask < 1. Each side is its own position. The two sides of a match are correlated,
  so CIs resample whole matches.
- Every result is also split by entry-price band: < 20¢, 20–40, 40–60, 60–80, ≥ 80¢.

## Exit rules
At the first row **strictly after** the entry, the position is sold if its net sale value per contract
clears the rule:

    net bid = (bid − slippage) − fee(bid − slippage, n) / n     (taker fee, rounded up per order)

| Family | Rule | Values |
|---|---|---|
| Absolute | net bid ≥ all-in entry + T | T ∈ {3, 5, 10, 15, 20, 30}¢ |
| Relative (longshots) | net bid ≥ k × all-in entry | k ∈ {1.5, 2, 3} |

- **Depth:** when the bid size is known (recorded books), a trigger also needs bid size ≥ n, the same
  as the lock's depth rule. Candles have no size, so the bid is assumed fillable in full.
- **Hold P&L:** n × settle_side − entry cost. `settle_a/settle_b` are 1/0, or the fair price for a match
  that never started.
- **No lookahead:** a trigger uses only that row (an as-of join of quotes at or before it). Settlement is
  used only for the hold leg. A test will prove that truncating future quotes doesn't change an earlier
  exit.

## Metrics
At 0¢ and 1¢ slippage, per (entry type × rule), overall and by entry band:
- trigger rate;
- mean Δ per contract (over triggered positions and over all entries), with a 95% match-clustered
  bootstrap CI;
- SD of P&L per contract, hold vs cash-out rule (variance reduction);
- worst-decile (P10) P&L per contract, hold vs rule;
- exit phase split (pre vs live) and minutes from entry to exit.
- **Set end vs mid-set:** this needs the recorder's `score/` table, which isn't in the candle set. If
  recorded extracts become available it will be reported as **descriptive only** (small, recent sample),
  never gated.

## Gate: "cash-out adds value"
Per entry type, choose the rule (one of the 9) on earlier months only: the best total Δ at 1¢ slippage
with ≥ 10 training triggers, training positions settled before the test month. Then apply it unchanged
to the next month. The machinery is the existing walk-forward (`swinglock/backtest/walkforward.py`),
with Δ in place of P&L. **PASS** only if all of these hold:
- OOS Δ > 0 in ≥ ⌈0.75 × folds⌉ folds at 1¢ (3 of 4; 4 of 5);
- total OOS Δ > 0 at 0¢ and 1¢;
- ≥ 30 OOS triggers;
- the no-lookahead test passes.

## Pre-registered expectation
If prices are calibrated (the match-path study found set-end prices calibrated), holding is worth
about the mid at the trigger moment, and cashing out gets bid − fee. So:

    E[Δ | trigger] ≈ −(half-spread + taker fee) ≈ −1¢ to −3¢ per contract

Cashing out should cost a little and reduce variance (lower SD, better P10). Expected verdict:
**FAIL**. A clearly positive Δ would mean prices overreact after a rise.

## Sanity check: cash-out = swing lock (holds by construction on our data)
- **Prices.** The normalizer builds both sides from the same two markets:
  - bid(A) = max(YES bid A, 1 − YES ask B)
  - ask(B) = min(YES ask B, 1 − YES bid A)

  So **bid(A) ≡ 1 − ask(B)** on every row with both values (recorded books use the same function). The
  run will confirm this on the data (max |bid(A) + ask(B) − 1| and the share of rows that pass). It is
  a check on the pipeline, not on the market.
- **Fees.** The fee is symmetric: fee(p, n) = fee(1 − p, n). So selling n of A at b gives n·b − fee.
  Locking instead (buying n of B at 1 − b, holding both to a $1 payout, or to fair prices that sum to
  $1) gives n − n(1 − b) − fee, the same amount.
- **Thresholds.** With slippage s and fill f = ask(B) + s = 1 − (b − s):

      net bid ≥ entry + T   ⇔   entry + f + fee(f)/n ≤ 1 − T

  So **an absolute take-profit at T is the swing lock at Y = 1 − T**. The swing grid's Y ∈ {0.90 … 0.99}
  covered T ∈ {1 … 10}¢, on entries that were *selected* (first ask ≤ X).
- **What's new here:**
  1. selection-neutral entries;
  2. Δ against holding the same position, instead of P&L in absolute terms;
  3. larger T (15–30¢) and the relative k rules.
- **Differences, outside the gate:** a cash-out frees capital at once while a lock ties it up until
  settlement; and the depth needed is bid size on A rather than ask size on B, which are the same
  orders under this construction.

## Data
- The research set: 13,019 candle matches with bids (ATP/WTA + Challenger/WTA 125, 2026-04-24 → 10-24,
  crossed-candle guard on), run locally by the Data role. No new Kalshi pulls.
- Recorder extracts, for the depth and set-end split, only if they're provided.
- Candle caveats apply: 1-minute closes, no depth, carry ≤ 1,800 s. The bid has the same staleness as
  the ask.

## Amendments
### 2026-10-28 (before any run): set-end proxy, Level exits, DOG50
Asked for by the Lead and the owner after registration. No cash-out number had been computed.

1. **Set end vs mid-set uses Kalshi set-winner markets, not the recorder's `score/` table** (the VPS is
   unreachable from cloud sessions).
   - A live exit counts as **at set end** if it falls within ±3 min of a set-winner `close_time` for
     that match (`sets.parquet`, KXATPSETWINNER / KXWTASETWINNER; close_time ≈ set end, median −1 min).
     A live exit outside every window counts as **mid-set**.
   - Kalshi lists only the sets before the decider, so the end of the decider (the match end) is never
     tagged.
   - Only ATP/WTA have set markets. Matches with no set rows (all Challenger/WTA 125) are reported as
     a separate **no set data** group.
   - Pre-match exits stay `pre`.
   - **Descriptive only, never gated.**
2. **New exit family, Level:** net bid ≥ L, with L ∈ {0.40, 0.50, 0.60}.
   - It applies only to positions with all-in entry < L, which keeps it a take-profit. Positions bought
     at or above L simply hold.
   - The gate's candidate set grows from 9 to 12 rules; walk-forward selection covers the extra choices.
3. **Owner's strategy, DOG50**, tested as a full strategy (entry + exit):
   - **Entry:** E1 and E2 sides with ask < 20¢.
   - **Exit:** net bid ≥ 0.50 (the L = 0.50 rule); otherwise hold to settlement.
   - **Report:** absolute P&L per contract and ROI (total P&L / total entry cost), Δ vs hold, trigger
     rate. Split by entry band < 10¢ / 10–20¢ and by entry type, at 0¢ and 1¢, with match-clustered CIs.
   - **DOG30** (ask < 30¢, adds a 20–30¢ band) is reported, **descriptive only**.
   - **DOG50 gate, on absolute P&L.** It's a fixed rule, so there is no selection and every month is
     out-of-sample. E1 and E2 positions are pooled, and CIs resample whole matches. PASS only if all hold:
     - P&L > 0 in ≥ ⌈0.75 × months⌉ months at 1¢;
     - total P&L > 0 at 0¢ and 1¢;
     - ≥ 30 triggers;
     - ≥ 4 months.
   - **Expectation:** if the price is a martingale, P(reach 50¢ from p0) ≈ p0 / 0.5. So "cash out at 50¢
     or hold" has EV ≈ p0, which is break-even before costs. Add the dog overpricing already measured
     (Kalshi early-round dogs −15.7%, DraftKings −18.7%) and spread + fee on two trades, and we expect:
     - a clearly negative absolute ROI;
     - a trigger rate ≈ 2·p0 (≈ 20–35%);
     - Δ vs hold small, of either sign.

     **Expected verdict: FAIL.**
4. **Bid staleness** (reported, not gated): the share of triggers whose exit bid had not changed for
   more than 60 s, read off a carried candle (`frac_stale_bid`). A trigger on an old bid is less
   reliable. bid(A) is built from the same two market quotes as ask(B), so its age is align's `age_b`
   (and bid(B)'s is `age_a`).

### 2026-10-28, second amendment (before any run): dog exit-level curve and DOGL
The owner wants to cash out a heavy dog "when it's breaking even (50-50) or even winning", and to see the
risk trade-off of that choice. No cash-out number had been computed.

1. **Exit-level curve.**
   - **Positions:** dog entries, i.e. E1 + E2 sides with ask < 20¢ (and separately < 30¢).
   - **Exits:** sell at net bid ≥ L, L ∈ {0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80, 0.90}, or
     **hold** (never sell). As before, a level applies only when it is above the all-in entry.
   - **Report, per L, at 0¢ and 1¢:**
     - trigger rate;
     - absolute P&L per contract and ROI, with match-clustered CIs;
     - Δ vs hold;
     - **SD and P10 of P&L per contract** (the risk side of the trade-off);
     - `frac_stale_bid`.

     The table reads as "the cost and risk of each exit level". Descriptive.
2. **DOGL gate** (dogs < 20¢): walk-forward over the 10 choices (9 levels + hold).
   - **Selection:** on earlier months only (positions settled before the test month), by **total absolute
     P&L at 1¢**. A level is eligible only with ≥ 10 training triggers. **"Hold" has no exit, so it is always
     eligible.**
   - **Test:** the choice runs unchanged on the next month.
   - **PASS rule:** the same as DOG50: ≥ 4 folds; P&L > 0 in ≥ ⌈0.75 × folds⌉ folds at 1¢; total > 0 at 0¢
     and 1¢; sample ≥ 30. Because a fold may pick "hold", the sample check counts **≥ 30 OOS positions**
     (OOS triggers are reported alongside).
   - DOG50 stays a fixed rule, unchanged.
3. **Expectation.**
   - By optional stopping, if prices are a martingale every L has the same EV before costs, ≈ the entry
     price.
   - A higher L triggers less often (≈ p0 / L), so it pays the exit spread and fee less often. **Holding is
     cheapest.**
   - A lower L reduces variance: higher P10, lower SD.
   - Expected result:
     - every L loses, mostly from dog overpricing;
     - Δ vs hold is slightly negative and shrinks toward 0 as L rises;
     - **DOGL FAIL**.
   - A clearly positive Δ at L ≈ 0.5–0.6 would mean comebacks are overpriced, i.e. the owner's idea works.

### 2026-10-28, third amendment (before any run): MISMATCH50
The owner sees ranking mismatches (e.g. ATP #20 vs #200, tour and Challenger level) "go to 50-50 pretty often" and
wants "buy the underdog, cash out at 50-50" tracked as a portfolio. No MISMATCH50 number had been computed.

1. **Rank** = the **pre-match Elo rank**, a proxy computed only from results before each match and supplied by the
   Upsets role as a parquet (`match_id, rank_a, rank_b`; CLI `--ranks`). Real ATP/WTA ranks for Apr–Oct 2026 are not
   in our data. It is labelled a proxy in every output.
2. **MISMATCH50 entry:** in matches where the worse-ranked player's rank is ≥ 4× the better-ranked player's rank, and
   the better player is ranked ≤ 100, buy the **worse-ranked** player at E1 and at E2, at any price (the price is
   recorded).
   - **Exit:** sell when net bid ≥ 0.50, otherwise hold to settlement.
   - As with every level rule, the exit applies only when the all-in entry is below 50¢. A worse-ranked player who is
     already the market favourite simply holds.
   - Ties and matches without a rank are left out.
3. **Report**, at 0¢ and 1¢ with match-clustered CIs:
   - **Reach-50 rate vs the price-implied rate.** Among entries bought below 50¢ all-in, compare the share that hit the
     exit with the average of p0 / b*. Here p0 is the entry ask and b* is the smallest whole-cent bid that nets 50¢ after
     the fee, plus slippage. Under a martingale, P(reach b*) = p0 / b*. Using the ask for p0 makes the implied rate
     generous. This is the direct test of "pretty often".
   - **Per-contract metrics:** P&L per contract, ROI, Δ vs hold, SD, P10.
   - **Splits:** by tour level (`tier`), and by rank-ratio bucket (< 2, 2–4, 4–8, ≥ 8) for every worse-ranked player
     (any ratio, any better rank) as context.
   - **Overlap with DOG50:** the share of MISMATCH50 entries bought under 20¢.
4. **Gate:** the DOG50 fixed-rule gate, on absolute P&L, monthly, every month out of sample. It needs ≥ 4 months,
   ≥ ⌈0.75 × months⌉ positive at 1¢, total > 0 at 0¢ and 1¢, and ≥ 30 triggers.
5. **Expectation.** The rank is already in the price. Dogs under 20¢ reached a 50¢ net only 21.7% (ATP/WTA) and 18.5%
   (Challenger) of the time, against a higher price-implied rate. So expect:
   - reach-50 at or below the price-implied rate;
   - negative ROI;
   - **FAIL**.

   A reach rate clearly above the implied rate *and* positive Δ vs hold would mean ranking mismatches are under-priced
   in-play, i.e. the owner's observation is an edge.

### 2026-10-28, fourth amendment (before any run): MISMATCH50-U (unranked players)
Owner request: include unranked players too. Data's MISMATCH50 run was in progress; no number for unranked players
existed.

1. **MISMATCH50-U:** in matches where one player is ranked ≤ 100 and the other is **unranked** (no pre-match Elo rank:
   NaN in the rank file), buy the unranked player at E1 and E2, at any price.
   - **Exit:** sell at net bid ≥ 0.50 (entries below 50¢ all-in only, as for every level rule), else hold.
   - **Metrics:** the same as MISMATCH50, including reach-50 vs the price-implied rate.
   - **Gate:** the same fixed-rule gate.
2. **Assumption, labelled in every output:** an unranked player is treated as ranked below the whole active pool.
   They're usually lower-level players, but not always.
3. **Report by unranked reason, in separate rows** (from `reason_a` / `reason_b` in the rank file, written by Upsets;
   "unknown" if the column is missing):
   - (i) too few rated matches (< 10);
   - (ii) inactive, no match in 365 days. This could be a comeback from injury, so the proxy is weakest here;
   - (iii) name not matched to the results data (a new player or a spelling gap).

   **Also report the entry-price distribution per reason** (P10–P90, the share under 20¢, the share over 50¢). If the
   market prices them as heavy dogs, that supports the assumption.
4. **Kept apart from MISMATCH50**, so the registered test is unchanged. MISMATCH50 still uses only fully ranked matches.
5. **Expectation:** the same as MISMATCH50. Reach-50 at or below the implied rate, negative ROI, **FAIL**. Reason (ii)
   may differ: if comeback players are mispriced, it would show as a reach rate above the implied rate in that row only,
   which would need its own pre-registered test.

### 2026-10-28, fifth amendment (POST HOC, after E1 results were seen): E1r robustness check
Data found that at a match's **first** pre-match observation the book is mostly empty: the median ask_a + ask_b is
$1.84 (ATP/WTA, 4,677 matches) and $1.88 (Challenger/WTA 125, 8,304 matches). E1 therefore buys listing-time
placeholder offers, usually 75–97¢, on both players. **Every E1 result so far measures that empty book, not the
strategy.** This covers the E1 gate, the E1 share of DOG50/DOGL and MISMATCH50 E1. E2 entries come from formed books
and are unaffected.

- **E1r** = the first pre-match row where ask_a + ask_b ≤ $1.05, i.e. a two-sided book within 5¢ of fair.
- It is re-run for DOG50, MISMATCH50 and MISMATCH50-U, plus every rule's summary, in the same Data run as
  MISMATCH50-U. The run also reports how many matches ever show such a book before the start.
- **Descriptive only, never gated:** the E1 results had already been seen when this was defined. The registered gate
  verdicts stand unchanged (all FAIL), and the original E1 rows stay in the reports, marked as a listing-book artefact.
