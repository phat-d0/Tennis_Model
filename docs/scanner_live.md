# Scanner: live scan loop (v1, REST polling)

Read-only. It never places orders: there is no order code, the client only does GET and refuses any
`/portfolio` path, and `tests/test_scanner.py::test_no_order_placement_anywhere_in_package` fails if
any write verb, order or portfolio endpoint, or request signing shows up anywhere in `swinglock/`.

## Run
```
python -m swinglock.scanner            # loop at scanner.poll_seconds (5 s)
python -m swinglock.scanner --once     # one scan, then exit
  --positions positions.json  --state data/live/state.json  --config config.yaml  -v
```
Output: alerts go to the console and to `data/alerts.log` (`<ts> [arb|lock] <message>`);
`data/live/state.json` is rewritten atomically every poll in the CLAUDE.md live-state format (newest
200 alerts, newest first, kept across restarts).

## What it does each poll
1. At startup: `GET /series/{ticker}` for each `scanner.series` to get `fee_type`/`fee_multiplier`.
   A series with an unknown fee type is skipped with an error log rather than guessed.
2. Every `scanner.discovery_seconds` (default 300): `GET /events?status=open&with_nested_markets=true&with_milestones=true`
   per series. Each two-market, mutually exclusive event becomes an A/B pair (A = first ticker
   alphabetically). Milestone `start_date` sets `phase` (pre/live; unknown with no milestone).
3. Every poll: one `GET /markets/orderbooks` per 50 matches (both legs in one call).
   `ask(A) = min(YES ask on A, NO ask on B)` with the size of that level; `bid(A) = max(YES bid on A, NO bid on B)`.
   Ties go to the deeper leg. `ask_source` in alerts says which leg (`yes:<ticker>` / `no:<ticker>`).
4. Alerts:
   - **arb**: `locks.true_arb` at both best asks, sized to the smaller resting depth and capped at
     `execution.max_contracts_per_trade`, per-series fees plus `execution.slippage`. Fires when profit > 0
     and profit/contract ≥ `scanner.min_arb_profit_per_contract`.
   - **lock**: `positions.json` rows (side = `A`/`B`, a market ticker = YES on it, or a player name)
     are summed into a `Holding` per event; `locks.lock_quote` buys the short side at its effective ask.
     Fires when locked P&L ≥ `scanner.min_lock_profit`. If the ask's depth is short of the contracts
     needed, the alert says `DEPTH SHORT` (cost is priced at the best level only).
   - One alert per episode per (type, match). Re-alerts on improvement ≥ max($0.05, 25 % of the last
     alerted value). An episode ends after 30 s without the opportunity, so a flickering book doesn't spam.
     These three are optional config keys (`scanner.realert_min_improvement`, `realert_min_improvement_pct`,
     `episode_gap_seconds`) with those defaults in code.

## API budget
Requests are spaced ≥ 1 s apart (`scanner.min_request_interval`) and retried with exponential backoff
(2, 4, … 60 s) on 429/5xx, since 429s carry no Retry-After. Each poll makes one orderbooks call per 50
matches, and the poll interval stretches so the average stays at or under `scanner.max_rps` (default
0.5 req/s). On 2026-10-24, with 96 matches, that was 2 calls per 5 s poll. On 2026-10-26, with 252
matches, it was 6 calls per 12 s poll. A failing tick doubles the wait (up to 5 min).

Measured 2026-10-26 (scanner and recorder on one IP, 6 min): scanner 0.50 req/s and recorder
0.45 req/s, with 9 × 429 out of 342 requests, all retried. The unauthenticated limit is
undocumented. It looks closer to about 1 req/s sustained than to the ~4 req/s burst seen at first.

First live check, 2026-10-24 09:14 UTC: 96 open matches discovered across the six series;
best combined ask was exactly $1.00 (no arb before fees, none after).

## Known limits (v1)
- Arb and lock costs use the best ask level only (no walking the book); depth beyond it isn't priced.
- The two legs of one side are not combined at the same price (one order, one leg).
- WebSocket needs a signed key, so this is REST polling only. The Kalshi client lives in
  `swinglock/scanner/client.py` until Data's shared client lands in `swinglock/collectors/`.
