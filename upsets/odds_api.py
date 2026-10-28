"""DraftKings Sportsbook tennis odds via The Odds API (read-only; the owner's paid, shared key).

Costs (docs/research/odds_api.md): /sports and /events are free; /odds = 1 credit per region
block (<= 10 bookmakers) per call; /historical/.../odds = 10 credits per snapshot. Every call
checks the quota headers, refuses to go below `floor`, and appends the spend to `spend_log`
(copy totals into docs/data_inventory.md). The key comes from ODDS_API_KEY and never
appears in logs. Only the Data and Upsets roles run paid calls, within the WORK_PLAN budget.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import unicodedata
from pathlib import Path

import pandas as pd
import requests

BASE = "https://api.the-odds-api.com/v4"
DEFAULT_BOOKS = ("draftkings", "pinnacle")

# Odds API key suffix -> Sackmann tournament names (both tours); dk_history and the odds page (site) use it
KEY_NAMES = {
    "aus_open_singles": ["Australian Open"], "french_open": ["Roland Garros"],
    "wimbledon": ["Wimbledon"], "us_open": ["Us Open", "US Open"],
    "indian_wells": ["Indian Wells Masters", "Indian Wells"], "miami_open": ["Miami Masters", "Miami"],
    "madrid_open": ["Madrid Masters", "Madrid"], "italian_open": ["Rome Masters", "Rome"],
    "canadian_open": ["Canada Masters", "Montreal", "Toronto"],
    "cincinnati_open": ["Cincinnati Masters", "Cincinnati"],
    "shanghai_masters": ["Shanghai Masters"], "paris_masters": ["Paris Masters"],
    "monte_carlo_masters": ["Monte Carlo Masters"], "china_open": ["Beijing"],
    "wuhan_open": ["Wuhan"], "dubai": ["Dubai"], "qatar_open": ["Doha"],
    # 250/500 keys (in scope only with levels including "other")
    "barcelona_open": ["Barcelona"], "halle_open": ["Halle"], "hamburg_open": ["Hamburg"],
    "japan_open": ["Tokyo"], "munich": ["Munich"], "queens_club_champ": ["Queen's Club"],
    "pan_pacific_open": ["Tokyo"],
    "washington_open": ["Washington"], "bad_homburg_open": ["Bad Homburg"],
    "charleston_open": ["Charleston"], "german_open": ["Berlin"], "guadalajara_open": ["Guadalajara"],
    "monterrey_open": ["Monterrey"], "ningbo_open": ["Ningbo"], "singapore_open": ["Singapore"],
    "strasbourg": ["Strasbourg"], "stuttgart_open": ["Stuttgart"],
}


class BudgetError(RuntimeError):
    pass


class OddsApi:
    def __init__(self, floor: int, key: str | None = None, session=None,
                 spend_log: str | Path = "data/odds_api_spend.log"):
        self.key = key or os.environ.get("ODDS_API_KEY")
        if not self.key:
            raise RuntimeError("ODDS_API_KEY is not set")
        self.floor = floor
        self.session = session or requests.Session()
        self.spend_log = Path(spend_log)
        self.remaining: float | None = None
        self.spent = 0.0

    def _get(self, path: str, params: dict | None = None, expected_cost: int = 0):
        if expected_cost:
            if self.remaining is None:
                self.sports()  # free call that reports the balance
            if self.remaining - expected_cost < self.floor:
                raise BudgetError(f"{path}: {expected_cost} credits would go below floor {self.floor} "
                                  f"(remaining {self.remaining:.0f})")
        try:
            r = self.session.get(f"{BASE}{path}", params={**(params or {}), "apiKey": self.key}, timeout=30)
        except requests.RequestException as e:   # its text holds the request URL, key included: never re-raise it
            raise type(e)(f"{type(e).__name__} on {path}") from None
        last = float(r.headers.get("x-requests-last", 0) or 0)
        if "x-requests-remaining" in r.headers:
            self.remaining = float(r.headers["x-requests-remaining"])
        self.spent += last
        if last:
            self.spend_log.parent.mkdir(parents=True, exist_ok=True)
            with open(self.spend_log, "a") as f:
                rem = "?" if self.remaining is None else f"{self.remaining:.0f}"
                f.write(f"{dt.datetime.now(dt.UTC).isoformat(timespec='seconds')}\t{path}\t{last:.0f}\t{rem}\n")
        try:
            r.raise_for_status()
        except requests.HTTPError:                 # requests' own message holds the URL, key included
            raise requests.HTTPError(f"HTTP {getattr(r, 'status_code', '?')} on {path}", response=r) from None
        return r.json()

    def sports(self, all_sports: bool = False) -> list[dict]:
        return self._get("/sports", {"all": "true"} if all_sports else None)

    def tennis_keys(self) -> list[str]:
        return sorted(s["key"] for s in self.sports() if s["key"].startswith("tennis_") and s.get("active"))

    def events(self, sport: str) -> list[dict]:
        return self._get(f"/sports/{sport}/events")

    def odds(self, sport: str, bookmakers=DEFAULT_BOOKS) -> list[dict]:
        cost = -(-len(bookmakers) // 10)
        return self._get(f"/sports/{sport}/odds", {"markets": "h2h", "oddsFormat": "decimal",
                                                    "bookmakers": ",".join(bookmakers)}, cost)

    def scores(self, sport: str, days_from: int = 3) -> list[dict]:
        """Live and recently completed events with scores; 2 credits with daysFrom (1 without)."""
        return self._get(f"/sports/{sport}/scores", {"daysFrom": days_from, "dateFormat": "iso"},
                         2 if days_from else 1)

    def historical_events(self, sport: str, when: str) -> dict:
        """Events listed at ISO time `when`: {"timestamp", "data": [...]}; 1 credit, 0 if none."""
        return self._get(f"/historical/sports/{sport}/events", {"date": when}, 1)

    def historical_odds(self, sport: str, when: str, bookmakers=DEFAULT_BOOKS) -> dict:
        """Snapshot closest to (at or before) ISO time `when`: {"timestamp", "data": [...]}."""
        cost = 10 * -(-len(bookmakers) // 10)
        return self._get(f"/historical/sports/{sport}/odds", {
            "date": when, "markets": "h2h", "oddsFormat": "decimal",
            "bookmakers": ",".join(bookmakers)}, cost)


def parse_h2h(events: list[dict], snapshot_ts: str | None = None) -> pd.DataFrame:
    """Odds API events -> one row per (event, bookmaker) with both players' decimal odds."""
    rows = []
    for e in events:
        p1, p2 = e["home_team"], e["away_team"]
        for b in e.get("bookmakers", []):
            for m in b.get("markets", []):
                if m["key"] != "h2h":
                    continue
                price = {o["name"]: o["price"] for o in m["outcomes"]}
                if p1 in price and p2 in price:
                    rows.append({"snapshot_ts": snapshot_ts, "event_id": e["id"], "sport_key": e["sport_key"],
                                 "commence_time": e["commence_time"], "player_1": p1, "player_2": p2,
                                 "book": b["key"], "odds_1": price[p1], "odds_2": price[p2],
                                 "last_update": m.get("last_update", b.get("last_update"))})
    df = pd.DataFrame(rows)
    for c in ("commence_time", "last_update", "snapshot_ts"):
        if c in df:
            df[c] = pd.to_datetime(df[c], utc=True)
    return df


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def td_key(name: str) -> str:
    """tennis-data style "De Minaur A." -> "de minaur a"."""
    return re.sub(r"[.\s]+", " ", _ascii(name)).strip()


def full_name_keys(name: str) -> set[str]:
    """Full name "Alex de Minaur" -> every "surname initial" reading: {"de minaur a", "minaur a"}.
    tennis-data gives surname + first initial, and multi-word surnames make the split ambiguous."""
    parts = _ascii(name).replace(".", " ").split()
    if len(parts) < 2:
        return {" ".join(parts)}
    return {f"{' '.join(parts[k:])} {parts[0][0]}" for k in range(1, len(parts))}
