"""Minimal read-only Kalshi REST client for the live scanner.

Temporary: kept inside `swinglock/scanner/` until the Data role's shared client lands in
`swinglock/collectors/`, so the Lead can consolidate later.

Read-only by construction: the only HTTP verb is GET, and any path that touches the
portfolio (orders, fills, balance) is refused before a request is made.

Rate limits: unauthenticated REST returned 429 after ~8 rapid calls (docs/research/kalshi_api.md
§5), with no Retry-After header. We space requests at least `min_interval` seconds apart
(1 s default, about a quarter of the observed limit) and back off exponentially on 429/5xx.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from typing import Any

import requests

log = logging.getLogger(__name__)

BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
MAX_TICKERS_PER_ORDERBOOKS = 100


class KalshiReadClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        min_interval: float = 1.0,
        max_retries: int = 5,
        timeout: float = 10.0,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.base_url = base_url.rstrip("/")
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._last = float("-inf")
        self.requests_made = 0

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if "portfolio" in path.lower():
            raise PermissionError(f"read-only client refuses portfolio path {path!r}")
        url = f"{self.base_url}/{path.lstrip('/')}"
        delay = 2.0
        for attempt in range(self.max_retries + 1):
            wait = self._last + self.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()
            self.requests_made += 1
            try:
                r = self.session.get(url, params=params, timeout=self.timeout)
            except requests.RequestException as e:
                if attempt == self.max_retries:
                    raise
                log.warning("GET %s failed (%s); retrying in %.0fs", path, e, delay)
            else:
                if r.status_code == 429 or r.status_code >= 500:
                    if attempt == self.max_retries:
                        r.raise_for_status()
                    log.warning("GET %s -> %s; backing off %.0fs", path, r.status_code, delay)
                else:
                    r.raise_for_status()
                    return r.json()
            self._sleep(delay)
            delay = min(delay * 2, 60.0)
        raise RuntimeError("unreachable")

    # ---- endpoints -------------------------------------------------------

    def series(self, series_ticker: str) -> dict[str, Any]:
        return self.get(f"/series/{series_ticker}")["series"]

    def open_events(self, series_ticker: str) -> tuple[list[dict], list[dict]]:
        """All open events of a series with nested markets, plus their milestones."""
        events, milestones, cursor = [], [], None
        while True:
            params = {"series_ticker": series_ticker, "status": "open", "with_nested_markets": "true",
                      "with_milestones": "true", "limit": 200}
            if cursor:
                params["cursor"] = cursor
            page = self.get("/events", params)
            events += page.get("events") or []
            milestones += page.get("milestones") or []
            cursor = page.get("cursor")
            if not cursor:
                return events, milestones

    def markets(self, tickers: Iterable[str]) -> list[dict]:
        """Market objects (status, result, settlement_value_dollars) for up to 100 tickers per call."""
        tickers, out = list(tickers), []
        for i in range(0, len(tickers), MAX_TICKERS_PER_ORDERBOOKS):
            chunk = tickers[i:i + MAX_TICKERS_PER_ORDERBOOKS]
            out += self.get("/markets", {"tickers": ",".join(chunk), "limit": 1000}).get("markets") or []
        return out

    def orderbooks(self, tickers: Iterable[str]) -> dict[str, dict]:
        """{ticker: orderbook_fp} for many markets, 100 tickers per request."""
        tickers = list(tickers)
        out: dict[str, dict] = {}
        for i in range(0, len(tickers), MAX_TICKERS_PER_ORDERBOOKS):
            chunk = tickers[i:i + MAX_TICKERS_PER_ORDERBOOKS]
            page = self.get("/markets/orderbooks", {"tickers": chunk})
            for ob in page.get("orderbooks") or []:
                out[ob["ticker"]] = ob.get("orderbook_fp") or {}
        return out
