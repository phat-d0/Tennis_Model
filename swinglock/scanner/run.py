"""Live scan loop (REST polling) and CLI.

    python -m swinglock.scanner              # loop forever at scanner.poll_seconds
    python -m swinglock.scanner --once       # one discovery + one scan, then exit

Per poll: one `GET /markets/orderbooks` per 50 matches (both legs in one call). Discovery
(`GET /events` per series, with milestones) refreshes every `scanner.discovery_seconds`
(default 300). Series fee types are fetched once at startup. With the client's 1 s minimum
spacing that stays well under a quarter of the observed unauthenticated limit.
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

log = logging.getLogger("swinglock.scanner")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _path(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


class Scanner:
    def __init__(self, cfg: dict[str, Any], client: KalshiReadClient, *, positions_path: Path,
                 sink: AlertSink, state: StateWriter, now: Callable[[], datetime] = utcnow):
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
        self.sink.emit(result.alerts)
        self.state.write(result, quote_ts)
        return result

    def run(self, once: bool = False, sleep: Callable[[float], None] = time.sleep,
            max_ticks: int | None = None) -> None:
        if not self.fees:
            self.load_fees()
        poll = float(self.sc.get("poll_seconds", 5))
        ticks, failures = 0, 0
        while True:
            start = time.monotonic()
            try:
                self.tick()
                failures = 0
            except Exception:
                failures += 1
                log.exception("scan tick failed (%d in a row)", failures)
            ticks += 1
            if once or (max_ticks is not None and ticks >= max_ticks):
                return
            backoff = min(poll * 2 ** min(failures, 6), 300) if failures else poll
            sleep(max(0.0, backoff - (time.monotonic() - start)))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Read-only Kalshi tennis arb / swing-lock scanner")
    ap.add_argument("--config", default=None)
    ap.add_argument("--positions", default=None, help="positions.json/csv (default: scanner.positions_file)")
    ap.add_argument("--state", default="data/live/state.json")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    sc = cfg.get("scanner", {})
    scanner = Scanner(
        cfg, KalshiReadClient(min_interval=float(sc.get("min_request_interval", 1.0))),
        positions_path=_path(args.positions or sc.get("positions_file", "positions.json")),
        sink=AlertSink(_path(sc.get("alert_log", "data/alerts.log"))),
        state=StateWriter(_path(args.state), sc.get("poll_seconds", 5)),
    )
    scanner.run(once=args.once)
