"""Wikipedia seeds for the live "Seed loses early" strategy (upsets/wiki_seeds.py, upsets/site.seed_facts).
The draw fixture is synthetic (see tests/upsets_fixtures/wikipedia/README.md)."""

import json
from pathlib import Path

import pandas as pd
import pytest
import requests

from upsets import portfolio as pf
from upsets import site, wiki_seeds as ws
from upsets.names import name_key

FX = (Path(__file__).parent / "upsets_fixtures" / "wikipedia" / "synthetic_draw.wikitext").read_text()
NOW = pd.Timestamp("2031-08-25 10:00", tz="UTC")
USO = "tennis_atp_us_open"


def test_parse_seeds_and_qualifiers():
    got = ws.parse(FX)
    assert got["seeds"] == {name_key("Marco Alpha"): 1, name_key("Pablo Beta"): 2,
                            name_key("Chris Gamma"): 3, name_key("Jean-Luc Delta"): 4}
    assert got["qualifiers"] == sorted([name_key("Sam Epsilon"), name_key("Felix Eta")])   # Q and LL, not WC


@pytest.mark.parametrize("text", [
    "no seeds here",
    FX.replace("# {{flagicon|FRA}} [[Jean-Luc Delta]] (quarterfinals)\n", ""),          # 3 seeds: odd count
    FX.replace("[[Chris Gamma]]", "Chris Gamma"),                                       # a seed with no link
])
def test_parse_refuses_unclean_lists(text):
    assert ws.parse(text) is None


def test_titles():
    assert ws.titles(USO, 2031) == ["2031 US Open – Men's singles", "2031 US Open – Singles"]
    assert ws.titles("tennis_wta_us_open", 2031)[0] == "2031 US Open – Women's singles"
    assert ws.titles("tennis_atp_paris_masters", 2031) == []


class Wiki:
    def __init__(self, pages=None, fail=False):
        self.pages, self.fail, self.calls = pages or {}, fail, []

    def get(self, url, params=None, headers=None, timeout=None):
        assert url == ws.API and headers["User-Agent"].startswith("tennis-odds-page")
        self.calls.append(params["page"])

        class R:
            status_code = 503 if self.fail else 200

            def raise_for_status(s):
                if s.status_code >= 400:
                    raise requests.HTTPError("503 for url https://en.wikipedia.org/x", response=s)

            def json(s, page=params["page"]):
                if page in self.pages:
                    return {"parse": {"wikitext": self.pages[page]}}
                return {"error": {"code": "missingtitle"}}
        return R()


def test_seeds_for_caches_and_falls_back_to_second_title(tmp_path):
    w = Wiki({"2031 US Open – Singles": FX})
    got, note = ws.seeds_for(w, tmp_path, USO, 2031)
    assert got["seeds"][name_key("Marco Alpha")] == 1 and "parsed" in note
    assert w.calls == ["2031 US Open – Men's singles", "2031 US Open – Singles"]
    again, note = ws.seeds_for(Wiki(fail=True), tmp_path, USO, 2031)      # cached: no request at all
    assert again == got and note == "cached"


def test_seeds_for_failures_are_not_cached_and_never_leak_urls(tmp_path):
    got, note = ws.seeds_for(Wiki(fail=True), tmp_path, USO, 2031)
    assert got is None and note == "fetch failed (HTTPError 503)"
    got, note = ws.seeds_for(Wiki({"2031 US Open – Men's singles": "no seeds"}), tmp_path, USO, 2031)
    assert got is None and "no clean seed list" in note and not (tmp_path / "wiki_seeds.json").exists()
    assert ws.seeds_for(Wiki(), tmp_path, USO, 2031)[1] == "no article"


def match(eid, p1, p2, hours=5, dk=(1.3, 3.6), pin=(1.32, 3.5)):
    return {"event_id": eid, "sport_key": USO, "tournament": "ATP US Open", "tour": "ATP",
            "commence_time": site._iso(NOW + pd.Timedelta(hours=hours)), "player_1": p1, "player_2": p2,
            "draftkings": {"odds_1": dk[0], "odds_2": dk[1]}, "pinnacle": {"odds_1": pin[0], "odds_2": pin[1]},
            "fair_1": None, "model_p1": 0.7}


def snaps(rows):
    return pd.DataFrame([{"event_id": e, "sport_key": USO, "commence_time": pd.Timestamp(t, tz="UTC"),
                          "player_1": a, "player_2": b} for e, t, a, b in rows])


def test_seed_facts_round_proxy_and_strategies(tmp_path):
    w = Wiki({"2031 US Open – Men's singles": FX})
    ms = [match("m1", "Marco Alpha", "Sam Epsilon"),        # seed 1 vs a qualifier, seed's first match
          match("m2", "Tom Zeta", "Pablo Beta"),            # seed 2 vs a wildcard; seed already played twice
          match("m3", "Marco Alpha", "Chris Gamma"),        # two seeds: no bet
          match("m4", "Juan Theta", "Tom Zeta")]            # no seed: no bet
    hist = snaps([("a", "2031-08-21 15:00", "Pablo Beta", "X"), ("b", "2031-08-23 15:00", "Y", "Pablo Beta"),
                  ("old", "2030-08-28 15:00", "Marco Alpha", "Z")])                       # last year's event: ignored
    facts = site.seed_facts(w, tmp_path, hist, ms, NOW)
    assert set(facts) == {"m1", "m2"}
    assert facts["m1"] == {"seed_side": 1, "seed": 1, "qual": True, "round_ok": True}
    assert facts["m2"]["seed_side"] == 2 and facts["m2"]["round_ok"] is False and not facts["m2"]["qual"]
    assert w.calls == ["2031 US Open – Men's singles"]                                  # one request per event
    trades = pf.update([], ms, NOW, None, facts)
    seed = {t["id"]: t for t in trades if t["strategy"] in ("seed", "seed_q")}
    assert set(seed) == {"seed:m1", "seed_q:m1"}                                          # m2 fails the round proxy
    t = seed["seed:m1"]
    assert t["side"] == 2 and t["player"] == "Sam Epsilon" and t["odds"] == 3.6
    assert t["opponent_seed"] == 1 and t["qualifier"] is True
    assert all("opponent_seed" not in x for x in trades if x["strategy"] not in ("seed", "seed_q"))


def test_backtest_seed_rows_use_the_preregistered_rule():
    from upsets import portfolio_backtest as pb
    import numpy as np
    sack = pd.DataFrame({"date": pd.to_datetime(["2025-05-01", "2025-06-01"]), "season": 2025, "tour": "atp",
                         "level_group": "slam", "round_idx": [1, 2], "void": False, "w_seed": [np.nan, 3],
                         "l_seed": [2, np.nan], "w_entry": ["Q", None], "l_entry": [None, None]})
    priced = pd.DataFrame({"sack_row": [0, 1], "commence": pd.to_datetime(["2025-05-02", "2025-06-02"]),
                           "odds_w_draftkings": [4.0, 1.3], "odds_l_draftkings": [1.25, 3.6],
                           "odds_w_pinnacle": [4.2, 1.32], "odds_l_pinnacle": [1.27, 3.7]})
    by = pb.seed_bets(priced, sack)
    assert len(by["seed"]) == 2 and list(by["seed_q"]["sack_row"]) == [0]
    assert by["seed"]["date"].iloc[0] == pd.Timestamp("2025-05-02")
    agg = pb.aggregate(by["seed"], "rule")
    assert agg["bets"] == 2 and agg["roi"] == pytest.approx((3.0 - 1.0) / 2)
