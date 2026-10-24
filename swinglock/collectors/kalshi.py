"""Read-only Kalshi REST client: throttle, retries, cursor paging, raw JSON cache.

Every response is saved under `raw_dir/<path>/<hash of params>.json.gz` (an envelope with
the url, params, fetch time and the response). A later call with the same path and params reads
the file instead of the network, so a rerun of the backfill doesn't re-download anything.
Pass `max_age_s` for listings that change over time (e.g. "settled events"); immutable data
(candles of settled markets) is cached forever.

Public market data needs no auth. The unauthenticated rate limit is undocumented: a 429 came
after ~8 rapid calls, without a Retry-After header (docs/research/kalshi_api.md §5). So the
client keeps a minimum gap between requests, backs off exponentially on 429, and widens the
gap each time it gets one. There is no order code here, by project rule.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

import requests

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
log = logging.getLogger(__name__)


class KalshiError(RuntimeError):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}: {body[:300]}")
        self.status = status


class KalshiClient:
    def __init__(self, base_url: str = BASE_URL, raw_dir: str | Path | None = "data/raw/kalshi",
                 min_interval_s: float = 0.5, max_interval_s: float = 5.0, max_retries: int = 6,
                 timeout_s: float = 30.0, session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.base_url = base_url.rstrip("/")
        self.raw_dir = Path(raw_dir) if raw_dir else None
        self.min_interval_s = self.base_interval_s = min_interval_s
        self.max_interval_s = max_interval_s
        self.max_retries = max_retries
        self.timeout_s = timeout_s
        self.session = session or requests.Session()
        self.session.headers.setdefault("Accept", "application/json")
        self._sleep, self._clock = sleep, clock
        self._last = -1e18
        self.requests_made = 0   # network calls, retries included
        self.rate_limited = 0    # 429s received
        self.cache_hits = 0
        self._ok_streak = 0

    # -- cache -------------------------------------------------------------------------
    def cache_path(self, path: str, params: dict[str, Any] | None) -> Path | None:
        if self.raw_dir is None:
            return None
        key = json.dumps(sorted((params or {}).items()), default=str)
        digest = hashlib.sha1(key.encode()).hexdigest()[:20]
        return self.raw_dir / path.strip("/") / f"{digest}.json.gz"

    def _read_cache(self, p: Path | None, max_age_s: float | None) -> dict | None:
        if p is None or not p.exists():
            return None
        if max_age_s is not None and time.time() - p.stat().st_mtime > max_age_s:
            return None
        try:
            with gzip.open(p, "rt") as f:
                return json.load(f)["response"]
        except (OSError, EOFError, ValueError, KeyError):
            return None  # partial/corrupt file: refetch

    def _write_cache(self, p: Path | None, url: str, params: dict | None, data: dict) -> None:
        if p is None:
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        env = {"url": url, "params": params or {},
               "fetched_at": datetime.now(timezone.utc).isoformat(), "response": data}
        tmp = p.with_name(p.name + ".tmp")
        with gzip.open(tmp, "wt") as f:
            json.dump(env, f)
        tmp.replace(p)  # atomic, so an interrupted run never leaves a half file

    # -- network -----------------------------------------------------------------------
    def _throttle(self) -> None:
        wait = self._last + self.min_interval_s - self._clock()
        if wait > 0:
            self._sleep(wait)
        self._last = self._clock()

    def get(self, path: str, params: dict[str, Any] | None = None, *, cache: bool = True,
            max_age_s: float | None = None) -> dict:
        """GET base_url+path. Cached responses are reused unless cache=False or older than max_age_s."""
        p = self.cache_path(path, params) if cache else None
        hit = self._read_cache(p, max_age_s)
        if hit is not None:
            self.cache_hits += 1
            return hit
        url = self.base_url + path
        backoff = 2.0
        for attempt in range(self.max_retries + 1):
            self._throttle()
            self.requests_made += 1
            try:
                r = self.session.get(url, params=params, timeout=self.timeout_s)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise
                log.warning("network error on %s (%s); retry in %.0fs", path, e, backoff)
                self._sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if r.status_code == 429:
                    self.rate_limited += 1
                    self._ok_streak = 0
                    # Widen the steady-state gap so we stop tripping the limit.
                    self.min_interval_s = min(self.min_interval_s * 1.5, self.max_interval_s)
                if attempt == self.max_retries:
                    raise KalshiError(r.status_code, r.url, r.text)
                log.warning("HTTP %s on %s; retry in %.0fs", r.status_code, path, backoff)
                self._sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            if r.status_code != 200:
                raise KalshiError(r.status_code, r.url, r.text)
            data = r.json()
            self._ok_streak += 1
            if self._ok_streak >= 50 and self.min_interval_s > self.base_interval_s:
                # Ease back toward the configured gap after a clean run of requests.
                self.min_interval_s = max(self.base_interval_s, self.min_interval_s / 1.25)
                self._ok_streak = 0
            if cache:
                self._write_cache(self.cache_path(path, params), url, params, data)
            return data
        raise AssertionError("unreachable")

    def paginate(self, path: str, params: dict[str, Any], key: str, **kw) -> Iterator[dict]:
        """Yield items of `key` across cursor pages (empty/null cursor ends it)."""
        params = dict(params)
        seen: set[str] = set()
        while True:
            page = self.get(path, params, **kw)
            yield from page.get(key) or []
            cur = page.get("cursor")
            if not cur or cur in seen:
                return
            seen.add(cur)
            params["cursor"] = cur

    # -- endpoints (all public, read-only) ---------------------------------------------
    def historical_cutoff(self) -> dict:
        return self.get("/historical/cutoff", cache=False)

    def series(self, ticker: str, max_age_s: float | None = 86400) -> dict:
        return self.get(f"/series/{ticker}", max_age_s=max_age_s)["series"]

    def series_fee_changes(self, ticker: str, max_age_s: float | None = 86400) -> list[dict]:
        d = self.get("/series/fee_changes", {"series_ticker": ticker, "show_historical": "true"},
                     max_age_s=max_age_s)
        return d.get("series_fee_change_arr") or []

    def events(self, series_ticker: str, status: str | None = None, nested: bool = True,
               max_age_s: float | None = 6 * 3600, **extra) -> Iterator[dict]:
        params = {"series_ticker": series_ticker, "limit": 200, **extra}
        if status:
            params["status"] = status
        if nested:
            params["with_nested_markets"] = "true"
        return self.paginate("/events", params, "events", max_age_s=max_age_s)

    def historical_markets(self, series_ticker: str, max_age_s: float | None = 6 * 3600,
                           **extra) -> Iterator[dict]:
        params = {"series_ticker": series_ticker, "limit": 1000, **extra}
        return self.paginate("/historical/markets", params, "markets", max_age_s=max_age_s)

    def milestones(self, max_age_s: float | None = 6 * 3600, **filters) -> Iterator[dict]:
        params = {"limit": 500, **filters}
        return self.paginate("/milestones", params, "milestones", max_age_s=max_age_s)

    def batch_candles(self, tickers: list[str], start_ts: int, end_ts: int,
                      period: int = 1) -> dict[str, list[dict]]:
        """Live (post-cutoff) markets, several tickers per call. Max 10,000 candles total."""
        d = self.get("/markets/candlesticks", {"market_tickers": ",".join(tickers),
                                               "start_ts": int(start_ts), "end_ts": int(end_ts),
                                               "period_interval": period})
        return {m["market_ticker"]: m.get("candlesticks") or [] for m in d.get("markets") or []}

    def historical_candles(self, ticker: str, start_ts: int, end_ts: int,
                           period: int = 1) -> list[dict]:
        """Markets settled before the historical cutoff. Field names lack _dollars/_fp."""
        d = self.get(f"/historical/markets/{ticker}/candlesticks",
                     {"start_ts": int(start_ts), "end_ts": int(end_ts), "period_interval": period})
        return d.get("candlesticks") or []

    def orderbooks(self, tickers: list[str], depth: int = 10) -> dict[str, dict]:
        """Live books for up to 100 tickers in one call (never cached: it's a snapshot)."""
        d = self.get("/markets/orderbooks", {"tickers": list(tickers), "depth": depth}, cache=False)
        return {o["ticker"]: o.get("orderbook_fp") or {} for o in d.get("orderbooks") or []}
