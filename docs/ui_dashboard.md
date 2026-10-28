# Dashboard (UI)

A read-only live page over the scanner's `data/live/state.json`. No trading buttons, no
venue API calls from the browser, no external CDNs, no build step.

## Run
```bash
python -m swinglock.dashboard --state data/live/state.json   # what the scanner writes
python -m swinglock.dashboard --sample                       # bundled sample + sample lookback, no network
# --lookback FILE (default: <state dir>/../paper/lookback.json, i.e. data/paper/lookback.json)
# options: --host 127.0.0.1 (default) --port 8000
```
Open http://127.0.0.1:8000/. On the VPS keep the default `127.0.0.1` bind and reach it through
an SSH tunnel (`ssh -L 8000:127.0.0.1:8000 vps`) or a VPN; there is no login on the page.

## Files
| File | What |
|---|---|
| `swinglock/dashboard/server.py` | `ThreadingHTTPServer`: `/` page, `/app.js`, `/style.css`, `/state.json` and `/lookback.json` (re-read per request). Missing file → 503, half-written/invalid JSON → 502; the page keeps its last good copy |
| `swinglock/dashboard/static/` | `index.html`, `app.js`, `style.css` |
| `swinglock/dashboard/sample_state.json` | Sample matching the CLAUDE.md contract: an open arb (Faria/Brunold), a side with no ask, the Krueger/Li worked example as a position (11.44 @ 42.7¢, 27.62 @ 54.3¢ → buy 16.18 Krueger @ 42.7¢, cost $7.19 with Kalshi fees, locked +$0.55), an unprofitable lock, a balanced holding, one alert of each type. Numbers come from `swinglock.locks` |
| `swinglock/dashboard/check_page.js` | Playwright (Node) check: phone 390×844 + laptop 1280×800, light + dark; fails on page/console errors, external requests, horizontal overflow; optional screenshots |
| `tests/test_dashboard.py` | Contract check of the sample, worked-example numbers vs the core math, server routes/errors, self-contained static files, browser checks incl. search/phase filters and a 100-match state (skipped without node + playwright) |

## What the page shows
- Header: venue, status pill (Live / Stale / Offline), data time and age (ticks every second).
- **Stale warning** when `generated_at` is older than 3 × `poll_seconds` (or missing, or far in
  the future = a clock problem). **Offline** banner when `/state.json` can't be loaded.
- Summary tiles: markets, live now, arbs open, locks available.
- Alerts, newest first (by `ts`), coloured by type (arb / lock / cross venue).
- **Arb rule:** a row is an open arb (green row, ARB badge, "Arbs open" tile) only when `arb_profit / arb_contracts` is at
  least the scanner's alert threshold: `state.min_arb_profit_per_contract` if the scanner sends it, otherwise config.yaml's
  default of 0.005 $/contract. A positive profit below it (e.g. 19.34 ct for $0.09) gets a muted "break-even" tag and
  isn't counted.
- **Tier labels** come from `series`, because the scanner's `tier` says "challenger" for both: ATP, WTA, ATP Challenger,
  WTA 125, ITF Men, ITF Women.
- Markets: players, tier, phase, ask A, ask B, depth A / B, combined, combined + fees, arb
  contracts and profit. Sort by combined + fees (default, cheapest first), combined, arb profit,
  tier or phase. **Search** (player, tier, series or ticker; every word must match) and a **phase
  filter** (All / Live / Pre-match / Unknown, with counts; remembered per device) narrow the list,
  and the header shows "N of M matches". The contract has no "ended" phase: ended or suspended
  matches lose their asks and drop into the **No market** group, a collapsed list at the bottom
  of every match without an ask on both sides. Filters apply to markets only; positions and
  alerts always show in full so a lock is never hidden by a search. Row highlighted green when `arb_profit > 0`, amber when a position on that match
  has a lock with `locked_pnl > 0`.
- Positions: held A/B (contracts @ avg), P&L if A / if B, contracts to buy (side, ask, "not enough
  depth" flag when `depth_ok` is false), cost, locked P&L. Profitable locks highlighted and listed first.
- Polls `/state.json` every `poll_seconds` (capped at 30s); re-polls when the tab regains focus.
- Theme: Auto (follows the device) / Light / Dark, remembered in localStorage.

## Paper tab
**Layout (owner 2026-10-28, copied from the soccer app's Portfolio):** three levels, like folders.
- **Home:** a "Portfolios" list with one full-width row per portfolio: **Swing-lock** (P1–P4) and **Cash-out** (C0–C4).
  Each row shows the name, a "Pre-registered" pill, its strategies, and on the right its P&L (settled + sold + locked,
  start-up entries left out) with "N final or locked · M open". Below: the hypothetical label and the nightly lookback's
  run line.
- **Portfolio** (tap a row; "‹ Paper" goes back): title and pill, a one-line description, the "Hypothetical, no orders" label
  with the pre-registered expectation, then **Strategies**, one row per rule. A row shows its rule in words, its start-up
  count, a "Lookback:" line (P&L, per contract, trades at 0¢), and on the right its live P&L with per contract and trades
  (cash-out: Δ vs C0, or "control"). Below them, everything the old single page had, for that portfolio: the summary
  table (totals and start-up rows), all its trades with status chips and a rule filter, and its nightly lookback table,
  chart and daily numbers.
- **Strategy** (tap a rule; "Paper › <portfolio>" goes back): the rule's id and rule in words, then a **Live paper /
  Backtest** toggle. Live paper shows that rule's summary row and start-up row, and its trades. Backtest shows that rule's
  lookback rows (0¢ and 1¢) and its chart line.
- Tapping the Paper tab again from a deeper level returns home. The Live tab is unchanged.

A "Live | Paper" switch under the header (`#paper` in the URL). The Paper view reads `state.paper` and `/lookback.json`
(both from Scanner; contract approved with phat-d0/Tennis_Model#116, docs/scanner_paper.md):
- **Banner:** a "Hypothetical, no orders" label and "Expected result (pre-registered): about −3 to −5¢ per contract. A rule
  clearly above zero over ≥ 30 settled trades would be the surprise.", plus the note that fills are optimistic.
- **P&L by rule:** trades, open / locked / settled, lock rate, **settled P&L** and **locked-but-unsettled P&L** in separate
  columns, **P&L per contract** (settled + locked P&L ÷ contracts on those trades; open trades have no P&L yet) and
  capital, plus an "All rules" total.
- **Start-up entries:** trades with `entry_ts == paper.since` (opened at the first poll, possibly mid-match) are left out
  of the headline rows and the total. They get their own rows under a separate heading, and a "start-up" badge in
  the trade list. The section is labelled "Start-up entries (entered at the price when paper trading began; excluded)". The
  numbers are computed from `paper.trades`; when that list is at its 200 cap, a note says the split may be incomplete. If a rule has more trades than the list carries (it's
  capped at 200), that rule falls back to the scanner's `by_rule` totals, with no split and no per-contract figure, and
  a note says so.
- **Cash-out portfolio** (owner request 2026-10-28; Scanner's C0–C4, `group: "cashout"`): its own section under the
  swing rules, "Cash-out portfolio (pre-registered 2026-10-28)", with the pre-registered expectation (Δ C1 vs C0 about −1 to
  −3¢ per contract). For each rule: trades, open / exited / final, exit rate, final P&L (settled + sold), P&L per contract,
  capital, **Δ vs C0 per contract** and the **spread of outcomes** (standard deviation of P&L per contract over final
  trades, with the min-to-max range). Δ pairs each entry with the control's identical entry (same match, side and E1/E2)
  once both are final, so C2's 20–30¢ entries (no C0 twin) don't count. Start-up rows are kept apart, with each rule's own
  `since` (older state files fall back to `paper.since`). Exited trades show "sold @ X¢ bid", the time and the cash after
  the fee, plus an E1/E2 badge; the trades list gets an "Exited" chip. The lookback adds a cash-out table (per contract and
  Δ vs C0 at 0¢ and 1¢) and a separate cumulative chart, so the swing chart keeps the swing rules only.
- **Trades:** status chips (All / Open / Locked / Settled, with counts) and a rule filter. Each trade shows the entry, the
  lock (or "not locked"), and P&L: the amount if each player wins while open, the locked P&L ("pays at settlement")
  once locked, and the final P&L plus the winner once settled.
- **Nightly lookback:**
  - run time, data range and match counts;
  - per rule at 0¢ and 1¢: trades, locked (rate), P&L, P&L per trade, **P&L per contract** (needs a `contracts` total in
    each by_rule row, added by phat-d0/Tennis_Model#119; an older file shows dashes and a note), win rate, locked / unlocked P&L;
  - a **cumulative P&L chart by settlement day** (inline SVG, one line per rule), with the daily numbers in a
    collapsible table;
  - a warning when the run is over 36 h old.
- **Missing pieces:** no `paper` key (scanner on `--no-paper`) or no lookback yet, each with a message. The server
  answers **204** for a lookback file that doesn't exist yet, so the browser logs no error before the first nightly run.
- **Redraws:** the view only redraws when its data changes, so an open filter menu isn't reset by the 5 s poll.
- **Tests:** `tests/test_dashboard.py` also runs Scanner's own code on its synthetic fixtures (tests/test_scanner_paper.py)
  and checks that the key sets match and that the page renders that output. A field rename on either side fails CI.

## Re-checking
```bash
python -m pytest -q tests/test_dashboard.py
python -m swinglock.dashboard --sample --port 8766 &
node swinglock/dashboard/check_page.js http://127.0.0.1:8766/ /tmp/shots swiatek   # screenshots + filter check
```
Screenshots of the sample (fresh timestamp, plus one stale) and a 100-match phone view filtered to
Live + "faria" are in `docs/ui_screenshots/`.

## Notes for Scanner
- The page treats `arb_profit > 0` as "arb live" and `lock.locked_pnl > 0` as "lock live";
  it does not apply thresholds itself, so the scanner should only report what it means.
- `combined_with_fees` is shown as cost per matched contract incl. fees at the arb size
  (the sample uses `true_arb(...).cost / contracts`). If Scanner means something else, say so.
- Write `state.json` atomically (temp file + rename); a half-written file shows as a 502 and the
  page keeps the previous data, but the rename avoids it entirely.
