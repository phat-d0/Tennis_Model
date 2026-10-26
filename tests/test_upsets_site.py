"""Odds page builder (upsets/site.py) on a fake Odds API session and a tiny synthetic Sackmann archive."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import requests

from upsets import site

NOW = pd.Timestamp("2026-10-27 10:00", tz="UTC")
KEY = "test-key-123"
COLS = ["tourney_id", "tourney_name", "surface", "draw_size", "tourney_level", "tourney_date",
        "match_num", "winner_id", "winner_seed", "winner_entry", "winner_name", "loser_id",
        "loser_seed", "loser_entry", "loser_name", "score", "best_of", "round",
        "winner_rank", "winner_rank_points", "loser_rank", "loser_rank_points"]
NAMES = {1: "Bu Yunchaokete", 2: "Alex Alpha", 3: "Marco Rossi", 4: "Marco Rossi", 5: "Nick Newbie"}


def write_archive(root: Path) -> Path:
    """ATP 2025: players 1-4 and fillers 10-19 play 30+ matches each; 5 plays 3. Player 1 wins
    everything, so the model favours him."""
    rows, num = [], 0
    pool = [1, 2, 3, 4] + list(range(10, 20))

    def add(w, l, name="Filler Open", surface="Clay", level="A", date=20250106):
        nonlocal num
        num += 1
        rows.append(dict(zip(COLS, [f"2025-{num}", name, surface, 32, level, date, num, w, None, None,
                                    NAMES.get(w, f"Filler {w}"), l, None, None, NAMES.get(l, f"Filler {l}"),
                                    "6-3 6-3", 3, "R32", 10, 1000, 50, 500])))
    for rep in range(3):
        for i, a in enumerate(pool):
            for b in pool[i + 1:]:
                w, l = (a, b) if a == 1 or (b != 1 and (a + b + rep) % 2) else (b, a)
                add(w, l, date=20250106 + rep * 100)
    for opp in (10, 11, 12):
        add(opp, 5)
    add(1, 2, name="Paris Masters", surface="Hard", level="M", date=20251027)
    (root / "atp").mkdir(parents=True)
    pd.DataFrame(rows, columns=COLS).to_csv(root / "atp" / "atp_matches_2025.csv", index=False)
    return root


class Resp:
    def __init__(self, data, last=0, remaining=9000, status=200):
        self.data, self.status_code = data, status
        self.headers = {"x-requests-last": str(last), "x-requests-remaining": str(remaining)}

    def json(self):
        return self.data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} for url ...apiKey={KEY}", response=self)


def ev(eid, key, hours, p1, p2, books=None):
    e = {"id": eid, "sport_key": key, "commence_time": site._iso(NOW + pd.Timedelta(hours=hours)),
         "home_team": p1, "away_team": p2}
    if books is not None:
        e["bookmakers"] = [{"key": b, "last_update": site._iso(NOW), "markets": [{
            "key": "h2h", "outcomes": [{"name": p1, "price": o1}, {"name": p2, "price": o2}]}]}
            for b, (o1, o2) in books.items()]
    return e


PARIS, WTA, LATER = "tennis_atp_paris_masters", "tennis_wta_ningbo_open", "tennis_atp_later_open"


class FakeApi:
    """/sports, /events free; /odds 1 credit. Paris has 2 matches within 36 h, Ningbo 1 (sooner), and
    a third key only has a match 48 h out."""

    def __init__(self, remaining=9000, fail=False):
        self.remaining, self.fail, self.paths = remaining, fail, []
        self.events = {
            PARIS: [ev("e1", PARIS, 5, "Yunchaokete Bu", "Alex Alpha",
                       {"draftkings": (1.5, 2.6), "pinnacle": (1.55, 2.7)}),
                    ev("e2", PARIS, 6, "Marco Rossi", "Nick Newbie", {"draftkings": (1.8, 1.95)})],
            WTA: [ev("w1", WTA, 2, "Anna One", "Beth Two", {"pinnacle": (2.0, 1.9)})],
            LATER: [ev("l1", LATER, 48, "Carl Three", "Dan Four", {"draftkings": (2.0, 1.8)})],
        }

    def get(self, url, params=None, timeout=None):
        assert params["apiKey"] == KEY
        path = url.split("/v4", 1)[1]
        self.paths.append(path)
        if self.fail:
            return Resp({}, status=500, remaining=self.remaining)
        if path == "/sports":
            return Resp([{"key": k, "title": t, "active": True} for k, t in (
                (PARIS, "ATP Paris Masters"), (WTA, "WTA Ningbo Open"), (LATER, "ATP Later"))]
                + [{"key": "soccer_epl", "title": "EPL", "active": True}], remaining=self.remaining)
        key, what = re.match(r"/sports/([^/]+)/(events|odds)", path).groups()
        if what == "events":
            return Resp([{k: v for k, v in e.items() if k != "bookmakers"} for e in self.events.get(key, [])],
                        remaining=self.remaining)
        self.remaining -= 1
        return Resp(self.events.get(key, []), last=1, remaining=self.remaining)

    def odds_calls(self):
        return [p for p in self.paths if p.endswith("/odds")]


@pytest.fixture
def dirs(tmp_path):
    return {"out": tmp_path / "out", "cache": tmp_path / "cache", "archive": write_archive(tmp_path / "sack")}


def run(dirs, api, key=KEY, now=NOW, **kw):
    kw.setdefault("month_cap", 600)
    return site.build(dirs["out"], dirs["cache"], dirs["archive"], now=now, key=key, session=api, **kw)


def test_ok_json_shape_model_and_names(dirs):
    api = FakeApi()
    doc = run(dirs, api)
    assert doc == json.loads((dirs["out"] / "odds.json").read_text())
    assert not any(KEY.encode() in f.read_bytes() for f in [*dirs["cache"].rglob("*"), dirs["out"] / "odds.json"]
                   if f.is_file())
    assert doc["status"] == "ok"
    assert set(doc) == {"generated_at", "odds_fetched_at", "status", "credits", "ratings_through",
                        "tournaments", "matches"}
    # soonest first, the 48 h key is never paid for
    assert api.odds_calls() == [f"/sports/{WTA}/odds", f"/sports/{PARIS}/odds"]
    assert doc["credits"] == {"left": None, "used_this_month": 2, "month_cap": 600}   # balance not public
    assert json.loads((dirs["cache"] / "ledger.json").read_text())["left"] == 8998
    assert doc["ratings_through"] == "2025-10-27"
    assert doc["tournaments"] == [{"sport_key": PARIS, "title": "ATP Paris Masters", "tour": "ATP"},
                                  {"sport_key": WTA, "title": "WTA Ningbo Open", "tour": "WTA"}]
    m = {x["event_id"]: x for x in doc["matches"]}
    assert set(m) == {"e1", "e2", "w1"}
    e1 = m["e1"]
    assert set(e1) == {"event_id", "sport_key", "tournament", "tour", "commence_time", "player_1", "player_2",
                       "draftkings", "pinnacle", "fair_1", "dk_implied_1", "model_p1", "model_n1", "model_n2"}
    assert e1["draftkings"]["margin"] == pytest.approx(1 / 1.5 + 1 / 2.6 - 1, abs=1e-4)
    assert e1["fair_1"] == pytest.approx((1 / 1.55) / (1 / 1.55 + 1 / 2.7), abs=1e-4)   # Pinnacle de-vig
    assert e1["dk_implied_1"] == pytest.approx(1 / 1.5, abs=1e-4)
    # "Yunchaokete Bu" (Odds API order) = Sackmann "Bu Yunchaokete"; he won every match
    assert e1["model_p1"] > 0.6 and e1["model_n1"] >= 20 and e1["model_n2"] >= 20
    # e2: "Marco Rossi" is two Sackmann players -> null; no Pinnacle -> fair from DraftKings
    assert m["e2"]["pinnacle"] is None and m["e2"]["model_p1"] is None
    assert m["e2"]["fair_1"] == pytest.approx((1 / 1.8) / (1 / 1.8 + 1 / 1.95), abs=1e-4)
    # w1: WTA names not in the archive -> null; no DraftKings quote
    assert m["w1"]["draftkings"] is None and m["w1"]["dk_implied_1"] is None and m["w1"]["model_p1"] is None


def test_shape_matches_page_fixture(dirs):
    """Same keys as the page's contract fixture (tests/test_site_data/odds.json)."""
    fx = json.loads((Path(__file__).parent / "test_site_data" / "odds.json").read_text())
    doc = run(dirs, FakeApi())
    assert set(doc) == set(fx) and set(doc["credits"]) == set(fx["credits"])
    assert set(doc["tournaments"][0]) == set(fx["tournaments"][0])
    for m in doc["matches"]:
        assert set(m) == set(fx["matches"][0])
    full = next(m for m in doc["matches"] if m["draftkings"] and m["pinnacle"])
    assert set(full["draftkings"]) == set(fx["matches"][0]["draftkings"])


def test_min_rated_matches(dirs):
    api = FakeApi()
    api.events = {PARIS: [ev("e3", PARIS, 3, "Alex Alpha", "Nick Newbie", {"draftkings": (1.2, 4.5)})]}
    m = run(dirs, api)["matches"][0]
    assert m["model_p1"] is None and m["model_n2"] == 3 and m["model_n1"] >= 20


def test_no_key_uses_cache(dirs, monkeypatch):
    run(dirs, FakeApi())
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    api = FakeApi()
    doc = run(dirs, api, key=None, now=NOW + pd.Timedelta(hours=1))
    assert api.paths == [] and doc["status"] == "no_key"
    assert len(doc["matches"]) == 3 and doc["odds_fetched_at"] == site._iso(NOW)
    assert doc["credits"]["used_this_month"] == 2


def test_floor_blocks_paid_calls(dirs):
    api = FakeApi(remaining=5000)
    doc = run(dirs, api, floor=5000)
    assert doc["status"] == "below_floor" and api.odds_calls() == [] and doc["matches"] == []


def test_month_cap(dirs):
    dirs["cache"].mkdir()
    (dirs["cache"] / "ledger.json").write_text(json.dumps({"month": "2026-10", "used": 600, "by_day": {}}))
    api = FakeApi()
    doc = run(dirs, api)
    assert doc["status"] == "cap_reached" and api.odds_calls() == []
    # last month's spend doesn't count
    (dirs["cache"] / "ledger.json").write_text(json.dumps({"month": "2026-09", "used": 600, "by_day": {}}))
    doc = run(dirs, FakeApi())
    assert doc["status"] == "ok" and doc["credits"]["used_this_month"] == 2


def test_pacing():
    led = {"month": "2026-11", "used": 0, "by_day": {}}
    t0 = pd.Timestamp("2026-11-01 00:00", tz="UTC")            # 30 days left: 20/day over 8 runs
    assert site.run_allowance(led, 600, t0) == 3
    led = {"month": "2026-11", "used": 15, "by_day": {"2026-11-01": 15}}
    assert site.run_allowance(led, 600, pd.Timestamp("2026-11-01 22:00", tz="UTC")) == 5   # last run: the rest
    led = {"month": "2026-11", "used": 20, "by_day": {"2026-11-01": 20}}
    assert site.run_allowance(led, 600, pd.Timestamp("2026-11-01 22:00", tz="UTC")) == 0   # today used up
    led = {"month": "2026-11", "used": 590, "by_day": {}}
    assert site.run_allowance(led, 600, pd.Timestamp("2026-11-30 21:00", tz="UTC")) == 10  # never past the cap
    led = {"month": "2026-11", "used": 300, "by_day": {}}     # a busy first half can't drain the rest
    assert site.run_allowance(led, 600, pd.Timestamp("2026-11-16 21:00", tz="UTC")) == 20


def test_paced_run_fetches_soonest_only(dirs):
    dirs["cache"].mkdir()
    (dirs["cache"] / "ledger.json").write_text(json.dumps(
        {"month": "2026-10", "used": 121, "by_day": {"2026-10-27": 120}}))
    api = FakeApi()
    doc = run(dirs, api)        # (600 - 1) / 5 days left - 120 < 0
    assert doc["status"] == "paced" and api.odds_calls() == []
    api = FakeApi()
    late = pd.Timestamp("2026-10-27 22:00", tz="UTC")
    api.events = {k: [dict(e, commence_time=site._iso(late + pd.Timedelta(hours=h)))
                      for e, h in zip(v, (2, 3))] for k, v in FakeApi().events.items() if k != LATER}
    api.events[WTA][0]["commence_time"] = site._iso(late + pd.Timedelta(hours=1))
    (dirs["cache"] / "ledger.json").write_text(json.dumps(
        {"month": "2026-10", "used": 119, "by_day": {"2026-10-27": 119}}))
    run(dirs, api, now=late)    # (600 - 0) / 5 - 119 = 1 credit left today: the soonest key only
    assert api.odds_calls() == [f"/sports/{WTA}/odds"]


def test_error_status_never_leaks_key(dirs):
    doc = run(dirs, FakeApi(fail=True))
    assert doc["status"] == "error: HTTPError 500"
    assert KEY not in (dirs["out"] / "odds.json").read_text()
    for f in dirs["cache"].rglob("*"):      # nor in anything cached (no URLs, headers or bodies)
        assert not f.is_file() or KEY.encode() not in f.read_bytes()


def test_ratings_cached_by_archive(dirs, monkeypatch):
    rt = site.load_ratings(dirs["archive"], dirs["cache"])
    assert rt["surfaces"][PARIS] == "Hard" and rt["through"] == "2025-10-27"
    monkeypatch.setattr(site.sackmann, "load", lambda *a, **k: pytest.fail("ratings not cached"))
    again = site.load_ratings(dirs["archive"], dirs["cache"])
    pd.testing.assert_frame_equal(again["ratings"], rt["ratings"])
    assert site.load_ratings(dirs["archive"] / "missing", dirs["cache"]) is None


def test_no_kalshi():
    src = Path(site.__file__).read_text()
    assert not re.search(r"^\s*(from|import)\s.*kalshi", src, re.I | re.M)
    code = "import sys, upsets.site; print([m for m in sys.modules if 'kalshi' in m.lower()])"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"
