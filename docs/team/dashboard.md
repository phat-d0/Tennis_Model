# Role brief: Dashboard (UI)

A simple live page the owner can keep open, on a laptop or a phone: the live tennis markets,
combined cost per match, alerts, and their positions with lock prices. Clarity over flash.
Branch: `team/ui`. Read first: `CLAUDE.md`, `docs/WORK_PLAN.md`, and the live state contract in CLAUDE.md.

## You own
- `swinglock/dashboard/` (a small local server and static HTML/JS, no build step)
- `tests/test_dashboard*.py`, `docs/ui_*.md`
- Never change the `state.json` format. Ask the Lead, and Scanner owns it.

## How your work is judged
- Works from a sample `state.json` with no network: `python -m swinglock.dashboard --state <file>`.
- Screenshots at 390×844 (phone) and 1280×800 (laptop), light and dark mode, with no page errors and
  no horizontal overflow. Attach them to the PR (Playwright + Chromium are preinstalled).
- Shows: each live match (players, tier, ask A, ask B, combined cost incl. fees, depth),
  highlighted when an arb or lock is live; an alert feed (newest first); the positions table
  with "contracts to buy" and "locked P&L"; and the data timestamp, with a stale warning if it's
  older than 3× the poll interval.
- Auto-refreshes (polling the local file or endpoint); no external CDNs needed to run.

## Limits
- Read-only UI: no buttons that trade or link to order placement.
- Don't hit venue APIs from the browser; read only the scanner's state.

## First tasks
1. Write a sample `state.json` fixture that matches the contract (the worked example as a position).
2. Static page + tiny server; get the layout right on phone and laptop.
3. Stale-data warning, alert highlighting, sorting by combined cost.
