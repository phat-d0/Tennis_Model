"""Kalshi order-book recorder: snapshot open tennis match books into daily parquet.

    python -m swinglock.collectors.recorder                    # runs until stopped (SIGTERM/SIGINT)
    python -m swinglock.collectors.recorder --duration 300     # a 5-minute test run

Every `discovery_s` it lists the open events of each series in config `scanner.series`
(`GET /events?status=open&with_nested_markets=true&with_milestones=true`). Every `poll_s` it
snapshots both legs of every open match with `GET /markets/orderbooks` (100 tickers = 50
matches per call) and keeps:

- quotes: the schema `quotes` table via kalshi_normalize.orderbooks_to_quotes (source
  "orderbook", with sizes): the effective ask/bid of each side, YES-on-A vs NO-on-B resolved;
- depth: the top `depth` levels of every bid list (YES and NO) of every market, so ask-side
  depth can be rebuilt (YES ask levels = 1 − NO bid levels);
- matches: one row per match seen (upserted), same columns as the backfill's matches table.

Output under `out_dir` (default data/recorded/kalshi/, gitignored): each flush writes a part
file `<table>/<YYYY-MM-DD>/part-<HHMMSS>.parquet` (an interrupted run loses at most one flush);
finished days are compacted into `<table>/<YYYY-MM-DD>.parquet`. Read a day or a range with
`pd.read_parquet(path)`.

Budget: one shared client throttle (`max_rps`, default 1 req/s) covers discovery and polling;
the poll interval stretches when there are more books than fit. Read-only; no order code.
"""

from __future__ import annotations

import argparse
import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from ..config import load_config
from ..schema import MATCH_COLUMNS, QUOTE_COLUMNS, conform
from .kalshi import KalshiClient, KalshiError
from .kalshi_normalize import (SCORE_COLUMNS, SCORE_KEY, competitor_sides, match_row, num,
                               orderbooks_to_quotes, score_row, ts)

log = logging.getLogger("swinglock.recorder")

TICKERS_PER_CALL = 100
DEPTH_COLUMNS = {
    "ts": "datetime64[ns, UTC]",
    "match_id": "string",
    "ticker": "string",
    "book": "string",      # "yes" | "no": which bid list (Kalshi books are bids only)
    "level": "int64",      # 0 = best bid
    "price": "float64",    # dollars
    "size": "float64",     # contracts
}
LIVE_IDS_PER_CALL = 100     # GET /live_data/batch: milestone_ids maxItems 100
SCORE_HEARTBEAT_S = 600     # write an unchanged score row at least this often
SCORE_LEAD_S = 1800         # start polling a match's score this long before its scheduled start
DEFAULTS = {"poll_s": 10.0, "discovery_s": 600.0, "flush_s": 60.0, "max_rps": 1.0, "depth": 5,
            "score_poll_s": 60.0,
            "out_dir": "data/recorded/kalshi"}


def depth_rows(at: pd.Timestamp, match_id: str, ticker: str, book: dict, depth: int) -> list[dict]:
    rows = []
    for side in ("yes", "no"):
        levels = book.get(f"{side}_dollars") or []
        for i, (p, q) in enumerate(reversed(levels[-depth:])):   # ascending list, best last
            rows.append({"ts": at, "match_id": match_id, "ticker": ticker, "book": side,
                         "level": i, "price": num(p), "size": num(q)})
    return rows


def open_matches(client: KalshiClient, series: list[str], series_meta: dict[str, dict]) -> dict[str, dict]:
    """match_id → matches row for every open two-market event of the given series."""
    out = {}
    for s in series:
        params = {"series_ticker": s, "status": "open", "with_nested_markets": "true",
                  "with_milestones": "true", "limit": 200}
        starts, milestone_ids = {}, {}
        for page in _pages(client, "/events", params):
            for m in page.get("milestones") or []:
                main = (m.get("details") or {}).get("main_game_event_ticker")
                if main and m.get("start_date"):
                    starts[main] = m["start_date"]
                if main and m.get("id") and m.get("type") == "tennis_tournament_singles":
                    milestone_ids[main] = m["id"]
            for e in page.get("events") or []:
                mk = e.get("markets") or []
                if len(mk) != 2:
                    continue
                try:
                    row = match_row(e, mk, series_meta.get(s, {"ticker": s}),
                                    scheduled_start=starts.get(e["event_ticker"]))
                except (KeyError, ValueError) as err:
                    log.warning("%s: skipped (%s)", e.get("event_ticker"), err)
                    continue
                # Extra keys for live-score polling (dropped when the matches table is written).
                ma = next(x for x in mk if x["ticker"] == row["instrument_a"])
                mb = next(x for x in mk if x["ticker"] == row["instrument_b"])
                row["_milestone_id"] = milestone_ids.get(row["match_id"])
                row["_sides"] = competitor_sides(ma, mb)
                out[row["match_id"]] = row
    return out


def _pages(client: KalshiClient, path: str, params: dict):
    params = dict(params)
    while True:
        page = client.get(path, params, cache=False)
        yield page
        cur = page.get("cursor")
        if not cur:
            return
        params["cursor"] = cur


class Recorder:
    def __init__(self, client: KalshiClient, series: list[str], out_dir: Path, poll_s: float = 10.0,
                 discovery_s: float = 600.0, flush_s: float = 60.0, depth: int = 5,
                 score_poll_s: float = 60.0,
                 clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep):
        self.client, self.series, self.out_dir = client, series, Path(out_dir)
        self.poll_s, self.discovery_s, self.flush_s, self.depth = poll_s, discovery_s, flush_s, depth
        self.score_poll_s = score_poll_s   # 0 = live-score polling off
        self.clock, self.sleep = clock, sleep
        self.matches: dict[str, dict] = {}
        self.series_meta: dict[str, dict] = {}
        self._quotes: list[pd.DataFrame] = []
        self._depth: list[dict] = []
        self._open_ids: set[str] = set()
        self._scores: list[dict] = []
        self._last_score: dict[str, tuple[tuple, float]] = {}   # match → (SCORE_KEY values, written at)
        self._score_done: set[str] = set()                       # matches seen closed/ended
        self._last_discovery = -1e18
        self._last_score_poll = -1e18
        self._last_flush = clock()
        self.snapshots = 0
        self.score_polls = 0
        self.stop = False

    # -- steps ---------------------------------------------------------------------------
    def discover(self) -> None:
        for s in self.series:
            if s not in self.series_meta:
                try:
                    self.series_meta[s] = self.client.series(s, max_age_s=86400)
                except KalshiError as err:
                    log.warning("series %s meta failed: %s", s, err)
                    self.series_meta[s] = {"ticker": s}
        found = open_matches(self.client, self.series, self.series_meta)
        self.matches.update(found)
        self._open_ids = set(found)
        self._last_discovery = self.clock()
        log.info("discovery: %d open matches", len(found))

    def poll(self) -> None:
        """One snapshot of every open match's two books."""
        ids = sorted(self._open_ids)
        legs = [(mid, self.matches[mid]["instrument_a"], self.matches[mid]["instrument_b"]) for mid in ids]
        tickers = [t for _, a, b in legs for t in (a, b)]
        books: dict[str, dict] = {}
        for i in range(0, len(tickers), TICKERS_PER_CALL):
            chunk = tickers[i:i + TICKERS_PER_CALL]
            try:
                books.update(self.client.orderbooks(chunk, depth=self.depth))
            except KalshiError as err:
                log.warning("orderbooks call failed (%s)", err)
        at = pd.Timestamp(self.clock(), unit="s", tz="UTC")
        for mid, a, b in legs:
            if a not in books or b not in books:
                continue  # leg missing from the response: no row rather than a half quote
            self._quotes.append(orderbooks_to_quotes(mid, a, b, books[a], books[b], at=at))
            self._depth += depth_rows(at, mid, a, books[a], self.depth)
            self._depth += depth_rows(at, mid, b, books[b], self.depth)
        self.snapshots += 1

    def poll_scores(self) -> None:
        """One GET /live_data/batch per 100 matches that are due (from SCORE_LEAD_S before the
        scheduled start, or always if the start is unknown) and not yet seen ended. Writes a row
        when the score/state changed, or every SCORE_HEARTBEAT_S otherwise."""
        now = self.clock()
        self._last_score_poll = now
        due = {}
        for mid in sorted(self._open_ids):
            m = self.matches[mid]
            start = m.get("scheduled_start")
            if not m.get("_milestone_id") or mid in self._score_done:
                continue
            if start is not None and pd.notna(start) and pd.Timestamp(start).timestamp() - SCORE_LEAD_S > now:
                continue
            due[m["_milestone_id"]] = mid
        ids = list(due)
        at = pd.Timestamp(now, unit="s", tz="UTC")
        for i in range(0, len(ids), LIVE_IDS_PER_CALL):
            chunk = ids[i:i + LIVE_IDS_PER_CALL]
            try:
                d = self.client.get("/live_data/batch", {"milestone_ids": chunk}, cache=False)
            except KalshiError as err:
                log.warning("live_data call failed (%s)", err)
                continue
            for live in d.get("live_datas") or []:
                mid = due.get(live.get("milestone_id"))
                if mid is None or live.get("type") != "tennis_tournament_singles":
                    continue
                row = score_row(mid, live, self.matches[mid].get("_sides") or {}, at)
                if row is None:
                    continue
                key = tuple(row[k] for k in SCORE_KEY)
                prev = self._last_score.get(mid)
                if prev is None or prev[0] != key or now - prev[1] >= SCORE_HEARTBEAT_S:
                    self._scores.append(row)
                    self._last_score[mid] = (key, now)
                if row["status"] == "closed" or row["match_status"] == "ended":
                    self._score_done.add(mid)
        self.score_polls += 1

    def flush(self) -> None:
        now = datetime.fromtimestamp(self.clock(), tz=timezone.utc)
        stamp = now.strftime("%H%M%S")
        if self._quotes:
            q = pd.concat(self._quotes, ignore_index=True)
            for day, part in q.groupby(q["ts"].dt.strftime("%Y-%m-%d")):
                _write_part(self.out_dir / "quotes" / day, stamp, conform(part, QUOTE_COLUMNS))
        if self._depth:
            d = conform(pd.DataFrame(self._depth), DEPTH_COLUMNS)
            for day, part in d.groupby(d["ts"].dt.strftime("%Y-%m-%d")):
                _write_part(self.out_dir / "depth" / day, stamp, part)
        if self.matches:
            m = conform(pd.DataFrame(list(self.matches.values())), MATCH_COLUMNS)
            self.out_dir.mkdir(parents=True, exist_ok=True)
            p = self.out_dir / "matches.parquet"
            if p.exists():  # keep matches seen in earlier runs
                old = conform(pd.read_parquet(p), MATCH_COLUMNS)
                m = pd.concat([old[~old["match_id"].isin(m["match_id"])], m], ignore_index=True)
            _atomic_parquet(m, p)
        if self._scores:
            sc = conform(pd.DataFrame(self._scores), SCORE_COLUMNS)
            for day, part in sc.groupby(sc["ts"].dt.strftime("%Y-%m-%d")):
                _write_part(self.out_dir / "score" / day, stamp, part)
        self._quotes, self._depth, self._scores = [], [], []
        self._last_flush = self.clock()
        compact_days(self.out_dir, before=now.strftime("%Y-%m-%d"))

    def run(self, duration_s: float | None = None) -> None:
        t0 = self.clock()
        while not self.stop and (duration_s is None or self.clock() - t0 < duration_s):
            start = self.clock()
            if start - self._last_discovery >= self.discovery_s:
                try:
                    self.discover()
                except KalshiError as err:
                    log.warning("discovery failed (%s); keeping the previous match list", err)
                    self._last_discovery = start
            self.poll()
            if self.score_poll_s and self.clock() - self._last_score_poll >= self.score_poll_s:
                self.poll_scores()
            if self.clock() - self._last_flush >= self.flush_s:
                self.flush()
                log.info("%d snapshots, %d requests, %d 429s, %d open matches", self.snapshots,
                         self.client.requests_made, self.client.rate_limited, len(self._open_ids))
            wait = self.poll_s - (self.clock() - start)
            if wait > 0 and not self.stop:
                self.sleep(wait)
        self.flush()


def _atomic_parquet(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_name(path.name + ".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)


def _write_part(day_dir: Path, stamp: str, df: pd.DataFrame) -> None:
    day_dir.mkdir(parents=True, exist_ok=True)
    p = day_dir / f"part-{stamp}.parquet"
    n = 1
    while p.exists():
        p = day_dir / f"part-{stamp}-{n}.parquet"
        n += 1
    _atomic_parquet(df, p)


def compact_days(out_dir: Path, before: str) -> None:
    """Merge each day directory older than `before` (YYYY-MM-DD) into <table>/<day>.parquet."""
    for table in ("quotes", "depth", "score"):
        root = Path(out_dir) / table
        if not root.exists():
            continue
        for day_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name < before):
            parts = sorted(day_dir.glob("part-*.parquet"))
            frames = [pd.read_parquet(p) for p in parts]
            target = root / f"{day_dir.name}.parquet"
            if target.exists():
                frames.insert(0, pd.read_parquet(target))
            if frames:
                df = pd.concat(frames, ignore_index=True).sort_values("ts", kind="stable")
                _atomic_parquet(df, target)
            for p in parts:
                p.unlink()
            day_dir.rmdir()


def main(argv: list[str] | None = None) -> None:
    cfg = load_config()
    rc: dict[str, Any] = {**DEFAULTS, **(cfg.get("recorder") or {})}
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", nargs="*", default=cfg["scanner"]["series"])
    ap.add_argument("--out", type=Path, default=Path(rc["out_dir"]))
    ap.add_argument("--poll", type=float, default=rc["poll_s"], help="seconds between snapshots")
    ap.add_argument("--discovery", type=float, default=rc["discovery_s"])
    ap.add_argument("--flush", type=float, default=rc["flush_s"])
    ap.add_argument("--max-rps", type=float, default=rc["max_rps"], help="request cap, all calls")
    ap.add_argument("--depth", type=int, default=rc["depth"], help="bid levels kept per book side")
    ap.add_argument("--score-poll", type=float, default=rc["score_poll_s"],
                    help="seconds between live-score polls (0 = off)")
    ap.add_argument("--duration", type=float, help="stop after this many seconds (test runs)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = KalshiClient(raw_dir=Path(cfg["data"]["raw_dir"]) / "kalshi", min_interval_s=1.0 / a.max_rps)
    rec = Recorder(client, a.series, a.out, a.poll, a.discovery, a.flush, a.depth, a.score_poll)

    def _stop(*_):
        rec.stop = True
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    rec.run(a.duration)
    log.info("stopped: %d snapshots, %d requests, %d 429s", rec.snapshots, client.requests_made,
             client.rate_limited)


if __name__ == "__main__":
    main()
