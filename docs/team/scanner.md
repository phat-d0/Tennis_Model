# Role brief: Scanner

The live part: watch open Kalshi tennis matches and alert the owner the moment a true arb
or a swing lock on their own positions is available, with the exact number of contracts
to buy and the locked P&L. **Read-only: it never places orders.** Branch: `team/scanner`.
Read first: `CLAUDE.md`, `docs/WORK_PLAN.md`, `docs/research/kalshi_api.md`,
`swinglock/locks.py`, `swinglock/positions.py`, `swinglock/schema.py`.

## You own
- `swinglock/scanner/`, `tests/test_scanner*.py`, `docs/scanner_*.md`
- The live state file format, `data/live/state.json` (see the contract in CLAUDE.md). The
  Dashboard reads it, so changes go through the Lead.
- You may import the Kalshi REST/normalizer code from `swinglock/collectors/` (owned by
  Data). Ask Data for changes rather than editing it.

## How your work is judged
- Alerts use `locks.true_arb` / `locks.lock_quote` with per-series fees and config slippage.
  The worked example (Krueger/Li) shows the right contracts to buy and the right locked P&L.
- Alert types: (1) true arb with available depth, (2) swing lock on a position from
  `positions.json`, (3) a cross-venue gap later. Each alert shows match, side, ask, depth,
  contracts to buy, cost, locked P&L, and a timestamp.
- Replay test: feed recorded/fixture quotes through the scanner loop and get the expected
  alerts, with no duplicate spam (one alert per opportunity episode, re-alert on improvement).
- A test proves there are no order-placement calls: no POST/DELETE to `/portfolio/orders`
  and no use of write-scope keys anywhere in the package.
- Stays within its API share: websocket if public channels allow, else polling at
  `scanner.poll_seconds`, staying under a quarter of the read limit.

## Limits
- No bulk history pulls (Data owns those).
- No order placement, ever. Not behind a flag, not "for later".
- You own `deploy/` too: Dockerfile + docker-compose or systemd units to run the scanner,
  Data's recorder and the dashboard on a small Linux VPS, with restart-on-failure, log rotation and
  secrets from env. Document it in `docs/scanner_deploy.md`.

## First tasks, in order of value
1. Market discovery: list open tennis match events, build A/B pairs, and get the effective ask
   for each side (YES on own market vs NO on the other) with depth from the orderbook.
2. Scan loop + alert rules + console/log output (`data/alerts.log`) + `state.json` writer.
3. Positions: map `positions.json` rows (market/side tickers) onto A/B holdings and alert on
   profitable locks above `scanner.min_lock_profit`.
4. Websocket upgrade if public, with snapshot + delta handling.
5. VPS deploy (`deploy/`), once the scan loop works.
6. Cross-venue gaps once Data has the collectors: Kalshi vs DraftKings Sportsbook (via The Odds
   API; sizing stake = N / decimal_odds; warn about retirement/void-rule mismatch) and Polymarket US.
