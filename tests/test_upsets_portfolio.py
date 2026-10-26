"""Paper portfolio (upsets/portfolio.py + its hook in upsets/site.py), synthetic data only."""

import json
import re

import pandas as pd
import pytest

from upsets import portfolio as pf
from upsets import site

NOW = pd.Timestamp("2026-08-30 10:00", tz="UTC")
USO = "tennis_atp_us_open"


def match(eid="e1", key=USO, hours=4, dk=(1.5, 2.9), pin=(1.45, 2.95), model=0.6):
    return {"event_id": eid, "sport_key": key, "tournament": "ATP US Open", "tour": "ATP",
            "commence_time": site._iso(NOW + pd.Timedelta(hours=hours)), "player_1": "Ann", "player_2": "Bea",
            "draftkings": None if dk is None else {"odds_1": dk[0], "odds_2": dk[1]},
            "pinnacle": None if pin is None else {"odds_1": pin[0], "odds_2": pin[1]},
            "fair_1": None, "model_p1": model}


def test_pick_rules():
    s = {x["id"]: x for x in pf.STRATEGIES}
    m = match()
    assert pf.pick(s["dogs"], m) == (2, 0.0)
    # Pinnacle fair p(Bea) = (1/2.95)/(1/1.45+1/2.95) = 0.3296; DK 2.9 x 0.3296 - 1 = -4.4%: no bet
    assert pf.pick(s["line"], m) is None
    side, e = pf.pick(s["line"], match(dk=(1.5, 3.2)))          # 3.2 x 0.3296 - 1 = +5.5%
    assert side == 2 and e == pytest.approx(3.2 * (1 / 2.95) / (1 / 1.45 + 1 / 2.95) - 1)
    assert pf.pick(s["model"], match(model=0.75)) == (1, pytest.approx(0.75 * 1.5 - 1))   # +12.5%
    assert pf.pick(s["model"], match(model=0.66)) is None                               # -1%, +0.3%
    assert pf.pick(s["model"], match(model=None)) is None and pf.pick(s["dogs"], match(dk=None)) is None


def test_open_once_refresh_close_and_skip_unscored():
    trades = pf.update([], [match(model=0.75), match("e2", key="tennis_atp_paris_masters")], NOW, None)
    assert sorted(t["id"] for t in trades) == ["dogs:e1", "model:e1"]   # Paris has no /scores: no trades
    t = next(t for t in trades if t["strategy"] == "model")
    assert t["odds"] == 1.5 and t["ev"] == pytest.approx(1.5 * (1 / 1.45) / (1 / 1.45 + 1 / 2.95) - 1, abs=1e-4)
    # an hour later the price moved: no second trade, the close follows the market
    later = NOW + pd.Timedelta(hours=1)
    trades = pf.update(trades, [match(dk=(1.4, 3.1), pin=(1.38, 3.2), model=0.75)], later, None)
    assert len(trades) == 2
    t = next(t for t in trades if t["strategy"] == "model")
    p_close = (1 / 1.38) / (1 / 1.38 + 1 / 3.2)
    assert t["close"]["odds"] == 1.4 and t["clv"] == pytest.approx(1.5 * p_close - 1, abs=1e-4)
    assert t["close"]["minutes_before"] == 180
    # after the start nothing changes
    frozen = json.dumps(trades)
    pf.update(trades, [match(hours=-1, dk=(1.1, 8.0))], NOW + pd.Timedelta(hours=5), None)
    assert json.dumps(trades) == frozen


class ScoresApi:
    floor, remaining = 5000, 9000.0

    def __init__(self, events):
        self.events, self.spent, self.calls = events, 0.0, []

    def scores(self, sport, days_from=3):
        self.calls.append(sport)
        self.spent += 2
        return self.events


def test_settle_won_lost_unclear_and_void():
    trades = pf.update([], [match(model=0.75)], NOW, None)        # model: Ann @1.5, dogs: Bea @2.9
    after = NOW + pd.Timedelta(hours=8)
    api = ScoresApi([{"id": "e1", "completed": True, "last_update": "2026-08-30T16:00:00Z",
                      "scores": [{"name": "Ann", "score": "2"}, {"name": "Bea", "score": "3"}]}])
    used = []
    n = pf.settle(trades, api, after, lambda c: True, used.append)
    assert n == 1 and used == [2.0]
    by = {t["strategy"]: t for t in trades}
    assert by["model"]["status"] == "lost" and by["model"]["profit"] == -10
    assert by["dogs"]["status"] == "won" and by["dogs"]["profit"] == pytest.approx(19.0)
    # an unclear result stays open, and is void (stake back) after 4 days
    t2 = pf.update([], [match("e3")], NOW, None)
    pf.settle(t2, ScoresApi([{"id": "e3", "completed": True, "scores": None}]), after, lambda c: True, lambda c: None)
    assert t2[0]["status"] == "open"
    pf.settle(t2, None, NOW + pd.Timedelta(days=5), lambda c: True, lambda c: None)
    assert t2[0]["status"] == "void" and t2[0]["profit"] == 0.0
    # no budget: no call
    t3 = pf.update([], [match("e4")], NOW, None)
    api3 = ScoresApi([])
    assert pf.settle(t3, api3, after, lambda c: False, lambda c: None) == 0 and api3.calls == []


def test_summary_and_curve_realized_vs_expected():
    t = [{"strategy": "dogs", "status": s, "stake": 10.0, "odds": o, "ev": ev, "p_fair": p, "clv": c,
          "profit": pr, "commence_time": d, "settled_at": d}
         for s, o, ev, p, c, pr, d in [("won", 3.0, -0.05, 0.3167, 0.02, 20.0, "2026-08-30"),
                                        ("lost", 2.5, -0.04, 0.384, -0.01, -10.0, "2026-08-31"),
                                        ("open", 2.0, -0.03, 0.485, None, None, "2026-09-01")]]
    s = pf.summary(t)
    assert s["settled"] == 2 and s["open"] == 1 and s["profit"] == 10.0 and s["roi"] == 0.5
    assert s["expected"] == pytest.approx(-0.9) and s["luck"] == pytest.approx(10.9)
    assert s["clv"] == pytest.approx(0.005) and s["beat_close"] == 0.5 and s["max_drawdown"] == 10.0
    c = pf.curve(t)
    assert [x["realized"] for x in c] == [20.0, 10.0] and [x["expected"] for x in c] == [-0.5, -0.9]


def test_build_writes_portfolio_json(tmp_path):
    """End to end through site.build with a fake Odds API that also serves /scores."""
    from tests.test_upsets_site import KEY, Resp, ev, write_archive

    class Api:
        def __init__(self, now):
            self.now, self.paths = now, []

        def get(self, url, params=None, timeout=None):
            path = url.split("/v4", 1)[1]
            self.paths.append(path)
            if path == "/sports":
                return Resp([{"key": USO, "title": "ATP US Open", "active": True}])
            k, what = re.match(r"/sports/([^/]+)/(events|odds|scores)", path).groups()
            if what == "scores":
                return Resp([{"id": "u1", "completed": True, "scores": [{"name": "Yunchaokete Bu", "score": "3"},
                                                                     {"name": "Alex Alpha", "score": "1"}]}], last=2)
            e = [ev("u1", USO, 0, "Yunchaokete Bu", "Alex Alpha", {"draftkings": (2.6, 1.5), "pinnacle": (2.7, 1.55)})]
            e[0]["commence_time"] = site._iso(pd.Timestamp("2026-08-30 15:00", tz="UTC"))
            if what == "events":
                return Resp([{k2: v for k2, v in e[0].items() if k2 != "bookmakers"}])
            return Resp(e, last=1)

    dirs = {"out": tmp_path / "out", "cache": tmp_path / "cache", "archive": write_archive(tmp_path / "sack")}
    run = lambda now: site.build(dirs["out"], dirs["cache"], dirs["archive"], now=now, key=KEY,  # noqa: E731
                                 session=Api(now), month_cap=600)
    run(NOW)
    doc = json.loads((dirs["out"] / "portfolio.json").read_text())
    dogs = next(s for s in doc["strategies"] if s["id"] == "dogs")
    assert dogs["summary"]["open"] == 1 and dogs["trades"][0]["player"] == "Yunchaokete Bu"
    assert "ATP US Open" in doc["scored_tournaments"]
    run(pd.Timestamp("2026-08-30 20:00", tz="UTC"))       # 5 h after the start: settled via /scores
    doc = json.loads((dirs["out"] / "portfolio.json").read_text())
    dogs = next(s for s in doc["strategies"] if s["id"] == "dogs")
    assert dogs["summary"]["settled"] == 1 and dogs["trades"][0]["status"] == "won"
    assert dogs["summary"]["profit"] == pytest.approx(16.0)
    assert json.loads((dirs["cache"] / "ledger.json").read_text())["used"] >= 3   # odds + scores credits
    assert KEY not in (dirs["out"] / "portfolio.json").read_text()


def test_backtest_rules_and_aggregate():
    from upsets import portfolio_backtest as pb
    f = pd.DataFrame({
        "void": [False, False, True], "upset": [1, 0, 0],
        "odds_dog_dk": [3.2, 2.9, 4.0], "odds_fav_dk": [1.35, 1.42, 1.25],
        "odds_dog_pin": [3.0, 3.1, 4.2], "odds_fav_pin": [1.4, 1.38, 1.26],
        "p_model": [0.40, 0.20, 0.3],
        "date": pd.to_datetime(["2025-06-02", "2025-06-10", "2025-06-11"])})
    by = pb.bets(f)
    assert list(by["dogs"]["odds"]) == [3.2, 2.9]                 # void match left out
    # model: match 0 dog edge 0.4 x 3.2 - 1 = +28%; match 1 fav edge 0.8 x 1.42 - 1 = +13.6%
    assert list(by["model"]["side"]) == ["dog", "fav"]
    # line: match 0 dog 3.2 x fair(3.0 v 1.4) = 3.2 x 0.3182 - 1 = +1.8% >= 1%
    assert list(by["line"]["side"]) == ["dog"]
    a = pb.aggregate(by["dogs"], "rule")
    assert a["bets"] == 2 and a["roi"] == pytest.approx((2.2 - 1) / 2)
    assert a["curve"][-1]["realized"] == pytest.approx(1.2) and len(a["curve"]) == 2
    assert pb.aggregate(by["dogs"].iloc[:0], "rule") == {"rule": "rule", "bets": 0}


def test_quote_error_filter():
    s = {x["id"]: x for x in pf.STRATEGIES}
    # DK suspended-style quote 1.01 / 76.0 vs Pinnacle 1.24 / 4.52: a 20-point gap, no trade at all
    broken = match(dk=(1.01, 76.0), pin=(1.24, 4.52), model=0.5)
    assert all(pf.pick(x, broken) is None for x in s.values())
