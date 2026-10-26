"""Polymarket Challenger / WTA 125 block (upsets/polymarket.py, upsets/site.py) on a fake session."""

import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import requests

from upsets import polymarket as pm
from upsets.names import norm_name
from upsets import site

NOW = pd.Timestamp("2026-10-26 10:00", tz="UTC")
TIERS = {"atp": {"brest": ["Challenger", "Hard"]}, "wta": {"queretaro": ["WTA 125", "Hard"]}}


def event(eid, series, title, players, tokens, start="2026-10-26 15:00:00+00", accepting=True, extra=()):
    ml = {"sportsMarketType": "moneyline", "acceptingOrders": accepting, "closed": False,
          "outcomes": json.dumps(players), "clobTokenIds": json.dumps(tokens), "gameStartTime": start}
    other = {"sportsMarketType": "set_winner", "acceptingOrders": True, "closed": False,
             "outcomes": json.dumps(players), "clobTokenIds": json.dumps(["x1", "x2"]), "gameStartTime": start}
    return {"id": eid, "seriesSlug": series, "title": title, "markets": [ml, other, *extra]}


EVENTS = [
    event(1, "atp", "Brest: Hugo Gaston vs Daniil Glinka", ["Hugo Gaston", "Daniil Glinka"], ["t1", "t2"]),
    event(2, "wta", "Queretaro: Tatjana Maria vs Carlota Garibay", ["Tatjana Maria", "Carlota Garibay"], ["t3", "t4"],
          start="2026-10-26 08:00:00+00"),
    event(3, "atp", "Erste Bank Open: Alexander Zverev vs Martin Landaluce", ["A", "B"], ["t5", "t6"]),   # tour-level
    event(4, "atp-doubles", "Brest (Doubles): A/B vs C/D", ["A/B", "C/D"], ["t7", "t8"]),
    event(5, "itf", "M15 Heraklion: A vs B", ["A", "B"], ["t9", "t10"]),
    event(6, "atp", "Brest: Old Match vs Played", ["Old", "Played"], ["t11", "t12"], accepting=False),
    event(7, "atp", "Brest: Long Ago vs Started", ["Long", "Ago"], ["t13", "t14"], start="2026-10-26 05:00:00+00"),
    event(8, "atp", "Ningbo: Mili Poljicak vs Yuta Shimizu", ["Mili Poljicak", "Yuta Shimizu"], ["t15", "t16"]),
]
BOOKS = {
    # worst-first, as the CLOB returns them; two orders at the best ask add up
    "t1": {"bids": [{"price": "0.61", "size": "5"}, {"price": "0.64", "size": "17"}],
           "asks": [{"price": "0.72", "size": "230"}, {"price": "0.68", "size": "5"}, {"price": "0.68", "size": "3"}]},
    "t2": {"bids": [{"price": "0.30", "size": "8"}], "asks": []},
    "t3": {"bids": [], "asks": [{"price": "0.97", "size": "40"}]},
}


class Resp:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url https://clob.polymarket.com/books?x=1", response=self)


class FakePm:
    def __init__(self, events=EVENTS, fail_books=False, page=100):
        self.events, self.fail_books, self.page, self.calls = events, fail_books, page, []

    def get(self, url, params=None, headers=None, timeout=None):
        assert headers and headers.get("User-Agent")
        assert url == f"{pm.GAMMA}/events" and params["tag_id"] == 864 and params["closed"] == "false"
        self.calls.append(("get", params["offset"]))
        return Resp(self.events[params["offset"]:params["offset"] + self.page])

    def post(self, url, json=None, headers=None, timeout=None):
        assert headers and headers.get("User-Agent") and url == f"{pm.CLOB}/books"
        self.calls.append(("post", len(json)))
        if self.fail_books:
            return Resp({}, status=403)
        return Resp([{"asset_id": x["token_id"], **BOOKS.get(x["token_id"], {"bids": [], "asks": []})} for x in json])


def test_best_reads_max_bid_min_ask_and_sums_the_level():
    q = pm.best({"asset_id": "t1", **BOOKS["t1"]})
    assert q == {"bid": 0.64, "bid_size": 17.0, "ask": 0.68, "ask_size": 8.0}
    assert pm.best({"bids": [], "asks": []}) == {"bid": None, "bid_size": None, "ask": None, "ask_size": None}


def test_matches_keep_named_challenger_and_125_only():
    rows, unknown = pm.matches(EVENTS, TIERS, NOW)
    assert [r["event_id"] for r in rows] == ["2", "1", "8"]          # by start; Ningbo via the curated EXTRA list
    assert unknown == ["atp:Erste Bank Open"]                     # tour-level under its sponsor name: left out
    by = {r["event_id"]: r for r in rows}
    assert by["1"]["tournament"] == "Brest Challenger" and by["1"]["tier"] == "Challenger" and by["1"]["tour"] == "ATP"
    assert by["2"]["tournament"] == "Queretaro 125" and by["2"]["tier"] == "WTA 125"
    assert by["1"]["commence_time"] == "2026-10-26T15:00:00Z"
    assert by["1"]["player_1"] == "Hugo Gaston" and by["1"]["_tokens"] == ["t1", "t2"]


def test_tier_table_from_sackmann_drops_tour_level_cities():
    sack = pd.DataFrame({"season": 2025, "date": pd.Timestamp("2025-05-01"), "tour": ["atp", "atp", "atp", "wta", "wta"],
                         "tournament": ["Brest CH", "Seoul CH", "Seoul", "Queretaro 125", "Ningbo"],
                         "level": ["C", "C", "A", "C", "P"], "surface": "Hard"})
    t = pm.tier_table(sack)
    assert t["atp"] == {"brest": ["Challenger", "Hard"]}           # Seoul also hosts an ATP 250 in this data
    assert t["wta"] == {"queretaro": ["WTA 125", "Hard"]}


def test_challengers_object_and_request_count(monkeypatch):
    monkeypatch.setattr(pm, "PAGE", 3)
    monkeypatch.setattr(pm, "GAP_S", 0.0)
    s = FakePm(page=3)
    seen = []

    def model_fn(f):
        seen.append(f)
        return pd.DataFrame({"model_p1": [0.6, None, None], "model_n1": [40, None, 5], "model_n2": [30, None, 50]})
    ch, n, unknown = pm.challengers(s, NOW, TIERS, model_fn)
    assert n == len(s.calls) == 3 + 1                               # 3 gamma pages (3, 3, 2 events) + 1 book call
    assert ch["source"] == "polymarket_intl" and ch["status"] == "ok" and ch["fetched_at"] == "2026-10-26T10:00:00Z"
    m = {x["event_id"]: x for x in ch["matches"]}
    assert set(m["1"]) == {"event_id", "tournament", "tour", "tier", "commence_time", "player_1", "player_2",
                           "p1", "p2", "model_p1", "model_n1", "model_n2"}
    assert m["1"]["p1"] == {"bid": 0.64, "bid_size": 17.0, "ask": 0.68, "ask_size": 8.0}
    assert m["1"]["p2"] == {"bid": 0.3, "bid_size": 8.0, "ask": None, "ask_size": None}
    assert m["8"]["p1"]["bid"] is None and m["8"]["p1"]["ask"] is None   # no book returned
    assert list(seen[0]["tour"]) == ["wta", "atp", "atp"] and list(seen[0]["surface"][:2]) == ["Hard", "Hard"]
    assert pd.isna(seen[0]["surface"][2])
    assert m["2"]["model_p1"] == 0.6 and m["1"]["model_p1"] is None and m["1"]["model_n1"] is None


def test_matches_page_fixture_contract():
    """Same keys as Dashboard's fixture (tests/test_site_data/challengers.json)."""
    fx = json.loads((Path(__file__).parent / "test_site_data" / "challengers.json").read_text())
    ch, _, _ = pm.challengers(FakePm(), NOW, TIERS)
    assert set(ch) == set(fx)
    for m in ch["matches"]:
        assert set(m) == set(fx["matches"][0])
        assert set(m["p1"]) == set(fx["matches"][0]["p1"]) == set(m["p2"])


def test_site_block_error_keeps_last_and_never_leaks_url(tmp_path):
    rt = {"tiers": TIERS}
    ok = site.challenger_block(FakePm(), tmp_path, NOW, rt)
    assert ok["status"] == "ok" and len(ok["matches"]) == 3
    bad = site.challenger_block(FakePm(fail_books=True), tmp_path, NOW + pd.Timedelta(hours=3), rt)
    assert bad["status"] == "error: HTTPError 403"
    assert "http" not in bad["status"] and bad["matches"] == ok["matches"] and bad["fetched_at"] == ok["fetched_at"]
    first = site.challenger_block(FakePm(fail_books=True), tmp_path / "empty", NOW, rt)
    assert first["matches"] == [] and first["status"].startswith("error")


def test_no_kalshi():
    src = Path(pm.__file__).read_text()
    assert "kalshi" not in src.lower()
    code = "import sys, upsets.polymarket; print([m for m in sys.modules if 'kalshi' in m.lower()])"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


def test_unknown_surface_uses_overall_rating():
    """A NaN surface (as a DataFrame stores None) must mean "unknown", not a surface named NaN."""
    ratings = pd.DataFrame({"tour": "atp", "id": ["1", "1", "2", "2"], "surface": ["Hard", "Clay", "Hard", "Clay"],
                            "elo": [1800.0, 1800.0, 1500.0, 1500.0], "n": 50, "selo": [1900.0, 1700.0, 1400.0, 1600.0],
                            "spw": 0.62, "rpw": 0.38})
    players = pd.DataFrame({"tour": "atp", "id": ["1", "2"], "name": ["Hugo Gaston", "Daniil Glinka"],
                            "key": [norm_name("Hugo Gaston"), norm_name("Daniil Glinka")], "last": "2026-05-01"})
    cal = site.model.Logit(coef=np.array([0.0, 1.0, 0.0, 0.0]),
                           mean=np.zeros(3), scale=np.ones(3))
    rt = {"ratings": ratings, "players": players, "cal": cal, "mean_spw": {"atp": 0.62}}
    f = pd.DataFrame({"player_1": ["Hugo Gaston"] * 2, "player_2": ["Daniil Glinka"] * 2, "tour": "atp",
                      "surface": [None, "Clay"]})
    p = site._probs(f, f["tour"], f["surface"], pd.Series(3, index=f.index), rt, NOW)
    p_overall = site.elo_plus.page_prob({"elo": 1800, "selo": 1800, "spw": .62, "rpw": .38},
                                        {"elo": 1500, "selo": 1500, "spw": .62, "rpw": .38}, 0.62, 3, cal)
    assert p.at[0, "model_p1"] == pytest.approx(p_overall, abs=1e-4)
    assert p.at[1, "model_p1"] < p.at[0, "model_p1"]               # on clay the surface ratings are closer
