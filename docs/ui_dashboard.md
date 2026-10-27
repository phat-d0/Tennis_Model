# Dashboard (UI)

A read-only live page over the scanner's `data/live/state.json`. No trading buttons, no
venue API calls from the browser, no external CDNs, no build step.

## Run
```bash
python -m swinglock.dashboard --state data/live/state.json   # what the scanner writes
python -m swinglock.dashboard --sample                       # bundled sample, no network
# options: --host 127.0.0.1 (default) --port 8000
```
Open http://127.0.0.1:8000/. On the VPS keep the default `127.0.0.1` bind and reach it through
an SSH tunnel (`ssh -L 8000:127.0.0.1:8000 vps`) or a VPN; there is no login on the page.

## Files
| File | What |
|---|---|
| `swinglock/dashboard/server.py` | `ThreadingHTTPServer`: `/` page, `/app.js`, `/style.css`, `/state.json` (re-read per request). Missing file → 503, half-written/invalid JSON → 502; the page keeps its last good copy |
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
