"""Live scan loop (REST polling) and CLI.

    python -m swinglock.scanner              # loop forever at scanner.poll_seconds
    python -m swinglock.scanner --once       # one discovery + one scan, then exit

Per poll: one `GET /markets/orderbooks` per 50 matches (both legs in one call). Discovery
(`GET /events` per series, with milestones) refreshes every `scanner.discovery_seconds`
(default 300). Series fee types are fetched once at startup. Requests are spaced at least
`scanner.min_request_interval` apart, and the poll interval stretches so the average rate stays at
or under `scanner.max_rps` (default 0.5 req/s, under a quarter of the observed unauthenticated
limit): with 250 open matches a tick is 6 calls, so polls are 12 s apart instead of 5 s.
"""

from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import ROOT, kalshi_fees, load_config
from ..fees import FeeModel
from ..positions import load_positions
from .client import KalshiReadClient
from .engine import Engine, Settings, holdings_from_positions
from .market import MatchPair, match_quote, pairs_from_events
from .output import AlertSink, StateWriter
from .paper import PaperBook, load_settlements, save_settlements, settlement_from_markets

log = logging.getLogger("swinglock.scanner")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _path(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


class Scanner:
    def __init__(self, cfg: dict[str, Any], client: KalshiReadClient, *, positions_path: Path,
                 sink: AlertSink, state: StateWriter, now: Callable[[], datetime] = utcnow,
                 paper: PaperBook | None = None, settlements_path: Path | None = None):
        self.cfg = cfg
        self.sc = cfg.get("scanner", {})
        self.client = client
        self.positions_path = positions_path
        self.sink = sink
        self.state = state
        self.now = now
        self.engine = Engine(Settings.from_config(cfg))
        self.fees: dict[str, FeeModel] = {}
        self.pairs: list[MatchPair] = []
        self._discovered_at: datetime | None = None
        self._positions_mtime: float | None = None
        self._positions = []
        self._stretched = False
        self.paper = paper                       # independent of positions.json
        self.settlements_path = settlements_path

    def load_fees(self) -> None:
        for s in self.sc.get("series", []):
            try:
                meta = self.client.series(s)
                self.fees[s] = kalshi_fees(self.cfg, meta["fee_type"], float(meta.get("fee_multiplier", 1)))
            except Exception as e:     # unknown fee type or API error: skip the series, loudly
                log.error("series %s skipped: %s", s, e)

    def discover(self) -> None:
        pairs = []
        for s in self.fees:
            events, milestones = self.client.open_events(s)
            pairs += pairs_from_events(events, milestones)
        self.pairs = pairs
        self._discovered_at = self.now()
        log.info("discovered %d open matches", len(pairs))
        if self.paper:
            self.settle_paper()

    def settle_paper(self) -> None:
        """Settle paper trades whose match left the open list (one GET /markets per 50 matches)."""
        pending = self.paper.unsettled({p.match_id for p in self.pairs})
        if not pending:
            return
        markets = self.client.markets([t for pair in pending.values() for t in pair])
        cache = load_settlements(self.settlements_path) if self.settlements_path else {}
        for match_id, tickers in pending.items():
            pay = settlement_from_markets(markets, tickers)
            if pay is not None:
                self.paper.settle(match_id, *pay, self.now())
                cache[match_id] = list(pay)
        if self.settlements_path:
            save_settlements(self.settlements_path, cache)

    def positions(self):
        try:
            mtime = self.positions_path.stat().st_mtime
        except FileNotFoundError:
            self._positions, self._positions_mtime = [], None
            return self._positions
        if mtime != self._positions_mtime:
            self._positions = load_positions(self.positions_path)
            self._positions_mtime = mtime
            log.info("loaded %d position rows from %s", len(self._positions), self.positions_path)
        return self._positions

    def tick(self):
        now = self.now()
        every = self.sc.get("discovery_seconds", 300)
        if self._discovered_at is None or (now - self._discovered_at).total_seconds() >= every:
            self.discover()
        tickers = [t for p in self.pairs for t in (p.ticker_a, p.ticker_b)]
        books = self.client.orderbooks(tickers) if tickers else {}
        quote_ts = self.now()
        quotes = {p.match_id: q for p in self.pairs if (q := match_quote(p, books)) is not None}
        holdings = holdings_from_positions(self.positions(), {p.match_id: p for p in self.pairs})
        result = self.engine.step(self.pairs, quotes, self.fees, holdings, quote_ts, quote_ts)
        if self.paper:
            self.paper.step(self.pairs, quotes, self.fees, quote_ts)
        self.sink.emit(result.alerts)
        self.state.write(result, quote_ts, self.paper.summary() if self.paper else None)
        return result

    def run(self, once: bool = False, sleep: Callable[[float], None] = time.sleep,
            max_ticks: int | None = None) -> None:
        if not self.fees:
            self.load_fees()
        poll = float(self.sc.get("poll_seconds", 5))
        max_rps = float(self.sc.get("max_rps", 0.5))
        ticks, failures = 0, 0
        while True:
            start = time.monotonic()
            before = getattr(self.client, "requests_made", 0)
            try:
                self.tick()
                failures = 0
            except Exception:
                failures += 1
                log.exception("scan tick failed (%d in a row)", failures)
            ticks += 1
            if once or (max_ticks is not None and ticks >= max_ticks):
                return
            interval = self.interval(poll, getattr(self.client, "requests_made", 0) - before, max_rps)
            if interval > poll and not self._stretched:
                log.info("poll stretched to %.0fs to stay under %.2f req/s", interval, max_rps)
            self._stretched = interval > poll
            self.state.poll_seconds = round(interval, 1)   # so the dashboard's staleness check is honest
            backoff = min(interval * 2 ** min(failures, 6), 300) if failures else interval
            sleep(max(0.0, backoff - (time.monotonic() - start)))

    @staticmethod
    def interval(poll: float, requests: int, max_rps: float) -> float:
        """Seconds per tick: the configured poll, stretched so the average request rate stays at or
        under `scanner.max_rps` (many open matches mean several orderbooks calls per tick)."""
        return max(poll, requests / max_rps) if max_rps > 0 else poll


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Read-only Kalshi tennis arb / swing-lock scanner")
    ap.add_argument("--config", default=None)
    ap.add_argument("--positions", default=None, help="positions.json/csv (default: scanner.positions_file)")
    ap.add_argument("--state", default="data/live/state.json")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--no-paper", action="store_true", help="disable paper trading")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    sc = cfg.get("scanner", {})
    pc = cfg.get("paper") or {}
    scanner = Scanner(
        cfg, KalshiReadClient(min_interval=float(sc.get("min_request_interval", 1.0))),
        positions_path=_path(args.positions or sc.get("positions_file", "positions.json")),
        sink=AlertSink(_path(sc.get("alert_log", "data/alerts.log"))),
        state=StateWriter(_path(args.state), sc.get("poll_seconds", 5), extra={
            # the dashboard counts an arb as open only above the alert threshold
            "min_arb_profit_per_contract": Settings.from_config(cfg).min_arb_profit_per_contract}),
        paper=None if args.no_paper else PaperBook(
            ledger_path=_path(pc.get("ledger", "data/paper/ledger.jsonl")),
            slippage=float(cfg.get("execution", {}).get("slippage", 0.0))),
        settlements_path=_path(pc.get("settlements", "data/paper/settlements.json")),
    )
    scanner.run(once=args.once)
