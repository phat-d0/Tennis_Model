"""DraftKings pre-match match-winner odds for ATP Challenger / WTA 125 from OddsPapi (owner decision 2026-11-05).

The page's odds.json gets a `challengers_dk` block: one row per upcoming Challenger / WTA 125 singles match that
DraftKings prices, labelled "DraftKings (via OddsPapi), pre-match". Shown inside our page next to our model and
Polymarket, never as a standalone feed (OddsPapi's terms forbid redistributing its data as a standalone product).

Key and quota (free plan: 250 billable requests a month, every billable call counts, errors included):
- the key comes from the env var ODDSPAPI_KEY and travels in the `apiKey` query parameter, so no URL, response body or
  exception text is ever logged; errors read "HTTP <code> on <path>";
- `/v4/account` is unmetered but echoes the key: only `request_count` and `request_limit` are read from it;
- before any billable call the block reads `/v4/account` and stays on its cached copy if request_count >= QUOTA_STOP;
- a refresh happens at most every REFRESH_H hours; in between the cached copy (displayed fields only, in the build
  cache, never committed) is served with its fetched_at, so the page shows its age;
- calls are spaced GAP_S apart (FIXTURES_GAP_S after `/v4/fixtures`), at most MAX_CALLS billable calls a refresh.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pandas as pd
import requests

from . import polymarket
from .odds import devig_power

BASE = "https://api.oddspapi.io/v4"
KEY_ENV = "ODDSPAPI_KEY"
TENNIS = 12
BOOK = "draftkings"
MATCH_WINNER = "121"                      # DK match winner (two outcomes)
OUTCOME_1, OUTCOME_2 = "121", "122"       # participant1, participant2
QUOTA_STOP = 220
REFRESH_H = 12.0
GAP_S = 1.1
FIXTURES_GAP_S = 2.1
WINDOW_H = 47                             # /v4/fixtures by sport needs from/to under 48 h apart
MAX_CALLS = 5                             # billable calls a refresh: 1 fixtures + up to 4 odds (12 tournaments)
PER_ODDS_CALL = 3                         # tournamentIds per /v4/odds-by-tournaments call
SOURCE = "draftkings_via_oddspapi"
LABEL = "DraftKings (via OddsPapi), pre-match"
CREDIT = "DraftKings Challenger and WTA 125 odds: OddsPapi (oddspapi.io)"
CACHE_FILE = "oddspapi.json"


class OddsPapiError(RuntimeError):
    """An HTTP or network failure, described by status code and path only (the URL holds the key)."""


class Client:
    def __init__(self, key: str, session=None, sleep=time.sleep):
        if not key:
            raise ValueError(f"{KEY_ENV} is not set")
        self._key = key
        self.session = session or requests.Session()
        self.sleep = sleep
        self.billable = 0
        self._next_gap = 0.0

    def _get(self, path: str, params: dict | None = None, billable: bool = True, gap: float = GAP_S):
        if self._next_gap:
            self.sleep(self._next_gap)
        try:
            r = self.session.get(f"{BASE}{path}", params={**(params or {}), "apiKey": self._key}, timeout=30)
        except requests.RequestException as e:   # its text can hold the request URL, key included
            raise OddsPapiError(f"{type(e).__name__} on {path}") from None
        finally:
            if billable:
                self.billable += 1
            self._next_gap = gap
        if r.status_code >= 400:
            raise OddsPapiError(f"HTTP {r.status_code} on {path}")
        try:
            return r.json()
        except ValueError:
            raise OddsPapiError(f"bad JSON on {path}") from None

    def account(self) -> dict:
        """Unmetered. The body echoes the key: only the two quota fields leave this method."""
        body = self._get("/account", billable=False)
        return {"request_count": _int(_find(body, "request_count")), "request_limit": _int(_find(body, "request_limit"))}

    def fixtures(self, now: pd.Timestamp) -> list[dict]:
        return self._get("/fixtures", {"sportId": TENNIS, "from": _z(now), "to": _z(now + pd.Timedelta(hours=WINDOW_H)),
                                       "statusId": 0, "hasOdds": "true", "bookmakers": BOOK},
                         gap=FIXTURES_GAP_S) or []

    def odds(self, tournament_ids: list) -> list[dict]:
        out = self._get("/odds-by-tournaments", {"tournamentIds": ",".join(str(t) for t in tournament_ids),
                                                 "bookmaker": BOOK})
        return out if isinstance(out, list) else [out] if out else []


def _find(body, field: str):
    """The first value of `field` anywhere in a JSON body (the quota fields' nesting isn't documented)."""
    if isinstance(body, dict):
        if field in body:
            return body[field]
        body = list(body.values())
    if isinstance(body, list):
        for v in body:
            hit = _find(v, field)
            if hit is not None:
                return hit
    return None


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _z(t: pd.Timestamp) -> str:
    return t.tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


# --- tiers ---------------------------------------------------------------------------------------

def tour_of(f: dict) -> str | None:
    """'atp' for an ATP Challenger singles fixture, 'wta' for a WTA 125, from OddsPapi's category / tournament names
    (a pre-filter only: the tier itself comes from polymarket.tier_of, the #111 rule)."""
    text = f"{f.get('categoryName') or ''} {f.get('tournamentName') or ''}".lower()
    if "doubles" in text or "itf" in text:
        return None
    if "challenger" in text:
        return "atp"
    if "125" in text and "wta" in text:
        return "wta"
    return None


def city_of(name: str) -> str:
    """'Charlottesville, USA' / 'ATP Challenger Charlottesville' / 'Cali (Qualifying)' -> 'charlottesville' / 'cali'."""
    n = re.sub(r"\(.*?\)", " ", str(name or "")).split(",")[0].lower()
    n = re.sub(r"\b(atp|wta|challenger|125k?|men|women|singles|qualifying|qualification|ii|2)\b", " ", n)
    return " ".join(n.split())


# --- rows ----------------------------------------------------------------------------------------

def _price(market: dict, outcome: str) -> tuple[float | None, str | None]:
    o = ((market or {}).get("outcomes") or {}).get(outcome) or {}
    p = ((o.get("players") or {}).get("0")) or {}
    if not p.get("active", True):
        return None, None
    try:
        v = float(p.get("price"))
    except (TypeError, ValueError):
        return None, None
    return (v if v > 1 else None), p.get("changedAt")


def rows(fixtures: list[dict], odds: list[dict], tiers: dict | None, now: pd.Timestamp
         ) -> tuple[list[dict], list[str]]:
    """Displayed rows (Challenger / WTA 125 singles, pre-match, both DK prices live) and the names of atp/wta-looking
    events of unknown tier, which are left out and logged, never guessed."""
    by_id = {str(o.get("fixtureId")): o for o in odds or []}
    out, unknown = [], set()
    for f in fixtures or []:
        tour = tour_of(f)
        if tour is None or f.get("statusId") not in (0, None):
            continue
        name = str(f.get("tournamentName") or "")
        tier, surface = polymarket.tier_of(tour, city_of(name), tiers)
        if tier is None:
            unknown.add(f"{tour}:{name}")
            continue
        try:
            start = pd.Timestamp(f.get("startTime"))
        except (TypeError, ValueError):
            continue
        start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
        if start <= now:
            continue
        book = ((by_id.get(str(f.get("fixtureId"))) or {}).get("bookmakerOdds") or {}).get(BOOK) or {}
        if book.get("suspended"):
            continue
        market = (book.get("markets") or {}).get(MATCH_WINNER) or {}
        if market and not market.get("marketActive", True):
            continue
        (o1, c1), (o2, c2) = _price(market, OUTCOME_1), _price(market, OUTCOME_2)
        if o1 is None or o2 is None:
            continue
        changed = max((pd.Timestamp(c) for c in (c1, c2) if c), default=None)
        fair = float(devig_power([o1], [o2])[0])
        quali = "qualif" in name.lower()
        city = city_of(name).title()
        out.append({"event_id": str(f.get("fixtureId")),
                    "tournament": f"{city} {'Challenger' if tour == 'atp' else '125'}" + (" (qualifying)" if quali else ""),
                    "tour": tour.upper(), "tier": tier, "commence_time": _z(start),
                    "player_1": f.get("participant1Name"), "player_2": f.get("participant2Name"),
                    "draftkings": {"odds_1": o1, "odds_2": o2, "last_update": _z(changed) if changed is not None else None,
                                   "margin": round(1 / o1 + 1 / o2 - 1, 4)},
                    "fair_1": round(fair, 4), "dk_implied_1": round(1 / o1, 4), "_surface": surface})
    out.sort(key=lambda r: (r["commence_time"], r["tournament"]))
    return out, sorted(unknown)


# --- block ---------------------------------------------------------------------------------------

def _read(cache: Path) -> dict | None:
    try:
        return json.loads((cache / CACHE_FILE).read_text())
    except (OSError, ValueError):
        return None


def _empty() -> dict:
    return {"source": SOURCE, "label": LABEL, "credit": CREDIT, "fetched_at": None, "matches": []}


def _serve(cached: dict | None, status: str) -> dict:
    doc = dict(cached) if cached else _empty()
    doc["status"] = status
    return doc


def block(cache: Path, now: pd.Timestamp, tiers: dict | None, model_fn=None, key: str | None = None,
          session=None, sleep=time.sleep, log=print) -> dict:
    """odds.json `challengers_dk`. Never raises; never logs a URL, a body or the key."""
    key = key if key is not None else os.environ.get(KEY_ENV)
    cached = _read(cache)
    if not key:
        log(f"[challengers_dk: {KEY_ENV} not set; block skipped]")
        return _serve(cached, "no_key")
    if cached and cached.get("fetched_at") and \
            now - pd.Timestamp(cached["fetched_at"]) < pd.Timedelta(hours=REFRESH_H):
        return _serve(cached, "cached")
    client = Client(key, session=session, sleep=sleep)
    try:
        acct = client.account()
        used = acct["request_count"]
        if used is None or used >= QUOTA_STOP:
            log(f"[challengers_dk: quota guard, {used} of {acct['request_limit']} requests used; cached copy served]")
            return _serve(cached, "quota_guard")
        fx = client.fixtures(now)
        candidates = [f for f in fx if tour_of(f) is not None]
        tids = sorted({f.get("tournamentId") for f in candidates if f.get("tournamentId") is not None}, key=str)
        groups = [tids[i:i + PER_ODDS_CALL] for i in range(0, len(tids), PER_ODDS_CALL)][: MAX_CALLS - 1]
        if len(tids) > PER_ODDS_CALL * (MAX_CALLS - 1):
            log(f"[challengers_dk: {len(tids)} tournaments, only the first {PER_ODDS_CALL * (MAX_CALLS - 1)} fetched]")
        odds = []
        for g in groups:
            odds += client.odds(g)
        out, unknown = rows(candidates, odds, tiers, now)
    except Exception as e:    # OddsPapiError carries only a code and a path; anything else: its class name only
        msg = str(e) if isinstance(e, OddsPapiError) else type(e).__name__
        log(f"[challengers_dk: {msg}; {client.billable} billable requests; cached copy served]")
        return _serve(cached, f"error: {msg}")
    model = None
    if model_fn is not None and out:
        try:
            model = model_fn(pd.DataFrame({"player_1": [r["player_1"] for r in out],
                                           "player_2": [r["player_2"] for r in out],
                                           "tour": [r["tour"].lower() for r in out],
                                           "surface": [r["_surface"] for r in out]}))
        except Exception as e:   # the model column is optional; the prices still show
            log(f"[challengers_dk: model unavailable ({type(e).__name__})]")
    for i, r in enumerate(out):
        r.pop("_surface")
        for k in ("model_p1", "model_n1", "model_n2"):
            v = None if model is None else model.at[i, k]
            r[k] = None if v is None or pd.isna(v) else (round(float(v), 4) if k == "model_p1" else int(v))
    doc = {**_empty(), "fetched_at": _z(now), "matches": out}
    cache.mkdir(parents=True, exist_ok=True)
    (cache / CACHE_FILE).write_text(json.dumps(doc))
    log(f"[challengers_dk: {len(out)} matches, {client.billable} billable requests "
        f"({used + client.billable} this month); {len(unknown)} events of unknown tier left out: "
        f"{', '.join(unknown) or 'none'}]")
    return {**doc, "status": "ok"}
