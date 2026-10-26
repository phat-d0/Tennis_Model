"""Polymarket (international) prices for ATP Challenger and WTA 125 singles: the public page's
Challengers view (docs/research/challenger_odds.md; owner accepted Polymarket's terms 2026-10-26).

Read-only public endpoints, no key, no Odds API credits:
  gamma  GET  /events?tag_id=864&active=true&closed=false (paged, 100 per page)
  CLOB   POST /books (both tokens of each match, BOOK_CHUNK tokens per call; needs a User-Agent,
              the CLOB answers 403 without one)
About 7 gamma pages + 5 book calls per build, spaced GAP_S apart.

Tier: Polymarket has no tier field; an event is "Brest: A vs B" in series atp or wta. A city counts as a
Challenger / WTA 125 only when we can name its tier: from Jeff Sackmann's results (ATP level C "Brest CH",
WTA level C "Queretaro 125"; cities that also host a tour-level event of that tour are dropped), plus the
curated EXTRA list for events Sackmann doesn't have yet. Everything else (tour-level events under their
sponsor names, unknown cities) is left out and logged, so nothing is labelled Challenger by guesswork.
"""

from __future__ import annotations

import json
import time

import pandas as pd

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
HEADERS = {"User-Agent": "tennis-odds-page/1.0 (+https://github.com/phat-d0/Tennis_Model)"}
TENNIS_TAG = 864
PAGE = 100
MAX_PAGES = 15
BOOK_CHUNK = 50
GAP_S = 0.3
SHOW_PAST_H = 3.0
TIER_NAME = {"atp": "Challenger", "wta": "WTA 125"}
# (tour, city) -> tier for events missing from the Sackmann archive (it ends May 2026); Data's reading of the
# tournament names and fields, 2026-10-26. Add new Challenger / 125 cities here when the build log lists them.
EXTRA = {("atp", "ningbo"): "Challenger", ("wta", "curitiba"): "WTA 125", ("wta", "courmayeur"): "WTA 125"}
TOUR_LEVELS = {"atp": {"A", "M", "G", "F"}, "wta": {"P", "PM", "I", "G", "F", "T1", "T2"}}


# --- tiers -----------------------------------------------------------------------------------------

def _city(name: str, tour: str) -> str:
    n = str(name).strip()
    for suffix in (" CH", " 125"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n.strip().lower()


def tier_table(sack: pd.DataFrame, since_season: int = 2023) -> dict:
    """{tour: {city: [tier, surface]}} from Sackmann results: level C cities (ATP Challengers, WTA 125s)
    that never host a tour-level event of the same tour. Surface = the city's latest one."""
    s = sack[sack["season"] >= since_season].sort_values("date")
    out = {}
    for tour in ("atp", "wta"):
        t = s[s["tour"] == tour]
        low = t[t["level"].astype(str) == "C"]
        top = {_city(n, tour) for n in t.loc[t["level"].astype(str).isin(TOUR_LEVELS[tour]), "tournament"].unique()}
        cities = {}
        for name, surf in zip(low["tournament"], low["surface"]):
            c = _city(name, tour)
            if c not in top:
                cities[c] = [TIER_NAME[tour], None if pd.isna(surf) else str(surf)]
        out[tour] = cities
    return out


def tier_of(tour: str, city: str, tiers: dict | None) -> tuple[str | None, str | None]:
    c = city.strip().lower()
    if (tour, c) in EXTRA:
        return EXTRA[(tour, c)], None
    hit = (tiers or {}).get(tour, {}).get(c)
    return (hit[0], hit[1]) if hit else (None, None)


# --- fetch -----------------------------------------------------------------------------------------

def events(session, max_pages: int = MAX_PAGES, gap_s: float = GAP_S) -> tuple[list[dict], int]:
    """Every open tennis event (gamma), paged. -> (events, requests made)."""
    out, n = [], 0
    for page in range(max_pages):
        if n:
            time.sleep(gap_s)
        r = session.get(f"{GAMMA}/events", params={"tag_id": TENNIS_TAG, "active": "true", "closed": "false",
                                                   "limit": PAGE, "offset": page * PAGE},
                        headers=HEADERS, timeout=30)
        n += 1
        r.raise_for_status()
        batch = r.json()
        out += batch
        if len(batch) < PAGE:
            break
    return out, n


def books(session, tokens: list[str], gap_s: float = GAP_S) -> tuple[dict, int]:
    """token -> (bid, bid_size, ask, ask_size) at the best level (None when that side is empty)."""
    out, n = {}, 0
    for i in range(0, len(tokens), BOOK_CHUNK):
        if n:
            time.sleep(gap_s)
        r = session.post(f"{CLOB}/books", json=[{"token_id": t} for t in tokens[i:i + BOOK_CHUNK]],
                         headers=HEADERS, timeout=30)
        n += 1
        r.raise_for_status()
        for b in r.json():
            out[str(b.get("asset_id"))] = best(b)
    return out, n


def best(book: dict) -> dict:
    """Best bid / ask and the shares at that price; the CLOB lists levels worst-first, but take max/min
    so the order doesn't matter."""
    def lv(side):
        return [(float(x["price"]), float(x["size"])) for x in book.get(side) or []]
    bids, asks = lv("bids"), lv("asks")
    q = {"bid": None, "bid_size": None, "ask": None, "ask_size": None}
    if bids:
        p = max(x[0] for x in bids)
        q["bid"], q["bid_size"] = round(p, 4), round(sum(s for x, s in bids if x == p), 2)
    if asks:
        p = min(x[0] for x in asks)
        q["ask"], q["ask_size"] = round(p, 4), round(sum(s for x, s in asks if x == p), 2)
    return q


# --- matches ---------------------------------------------------------------------------------------

def _start(m: dict) -> pd.Timestamp | None:
    t = m.get("gameStartTime") or m.get("startDate")
    try:
        ts = pd.Timestamp(t)
    except (TypeError, ValueError):
        return None
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def matches(evs: list[dict], tiers: dict | None, now: pd.Timestamp) -> tuple[list[dict], list[str]]:
    """Open Challenger / WTA 125 singles moneylines starting after now - SHOW_PAST_H.
    -> (rows without prices, the skipped atp/wta event names of unknown tier)."""
    rows, unknown = [], set()
    for e in evs:
        tour = e.get("seriesSlug")
        title = str(e.get("title") or "")
        if tour not in ("atp", "wta") or ":" not in title:
            continue
        name = title.split(":", 1)[0].strip()
        city = name.split(",")[0].strip()
        ml = [m for m in e.get("markets") or [] if m.get("sportsMarketType") == "moneyline"
              and m.get("acceptingOrders") and not m.get("closed")]
        if len(ml) != 1:
            continue
        m = ml[0]
        try:
            players, tokens = json.loads(m["outcomes"]), json.loads(m["clobTokenIds"])
        except (KeyError, TypeError, ValueError):
            continue
        start = _start(m)
        if len(players) != 2 or len(tokens) != 2 or start is None or start < now - pd.Timedelta(hours=SHOW_PAST_H):
            continue
        tier, surface = tier_of(tour, city, tiers)
        if tier is None:
            unknown.add(f"{tour}:{name}")
            continue
        quali = "qualif" in name.lower()
        rows.append({"event_id": str(e.get("id")), "tournament": f"{city} {'Challenger' if tour == 'atp' else '125'}"
                     + (" (qualifying)" if quali else ""), "tour": tour.upper(), "tier": tier,
                     "commence_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "player_1": players[0],
                     "player_2": players[1], "_tokens": tokens, "_surface": surface})
    rows.sort(key=lambda r: (r["commence_time"], r["tournament"]))
    return rows, sorted(unknown)


def challengers(session, now: pd.Timestamp, tiers: dict | None, model_fn=None) -> tuple[dict, int, list[str]]:
    """The odds.json `challengers` object (status "ok"). model_fn(frame with player_1, player_2, tour,
    surface) -> frame with model_p1, model_n1, model_n2, or None. -> (object, requests made, unknown events)."""
    evs, n1 = events(session)
    rows, unknown = matches(evs, tiers, now)
    q, n2 = books(session, [t for r in rows for t in r["_tokens"]]) if rows else ({}, 0)
    empty = {"bid": None, "bid_size": None, "ask": None, "ask_size": None}
    model = None
    if model_fn is not None and rows:
        model = model_fn(pd.DataFrame({"player_1": [r["player_1"] for r in rows],
                                       "player_2": [r["player_2"] for r in rows],
                                       "tour": [r["tour"].lower() for r in rows],
                                       "surface": [r["_surface"] for r in rows]}))
    out = []
    for i, r in enumerate(rows):
        t1, t2 = r.pop("_tokens")
        r.pop("_surface")
        r["p1"], r["p2"] = q.get(str(t1), dict(empty)), q.get(str(t2), dict(empty))
        for k in ("model_p1", "model_n1", "model_n2"):
            v = None if model is None else model.at[i, k]
            r[k] = None if v is None or pd.isna(v) else (round(float(v), 4) if k == "model_p1" else int(v))
        out.append(r)
    return {"source": "polymarket_intl", "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "status": "ok",
            "matches": out}, n1 + n2, unknown
