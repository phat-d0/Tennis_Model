"""OddsPapi DraftKings Challenger / WTA 125 block (upsets/oddspapi.py) on a fake session. Synthetic fixtures only."""

import json

import pandas as pd
import pytest
import requests

from upsets import oddspapi as op
from upsets import site
from upsets.odds import devig_power

NOW = pd.Timestamp("2026-11-05 10:00", tz="UTC")
TIERS = {"atp": {"charlottesville": ["Challenger", "Hard"]}, "wta": {"cali": ["WTA 125", "Clay"]}}
KEY = "SECRETKEY-abc123"


def fixture(fid, cat, tour_name, p1, p2, tid, start="2026-11-06T09:00:00.000Z", status=0):
    return {"fixtureId": fid, "participant1Id": 1, "participant2Id": 2, "sportId": 12, "tournamentId": tid,
            "statusId": status, "hasOdds": True, "startTime": start, "participant1Name": p1, "participant2Name": p2,
            "categoryName": cat, "tournamentName": tour_name}


def odds(fid, tid, o1, o2, active=True, changed="2026-11-05T08:30:00.000Z"):
    def out(price):
        return {"players": {"0": {"active": active, "price": price, "changedAt": changed}}}
    return {"fixtureId": fid, "tournamentId": tid, "bookmakerOdds": {"draftkings": {
        "suspended": False, "markets": {"121": {"marketActive": True, "outcomes": {"121": out(o1), "122": out(o2)}}}}}}


FIXTURES = [
    fixture("f1", "Challenger", "Charlottesville, USA", "Ann A", "Bob B", 101),
    fixture("f2", "WTA 125K", "Cali", "Cara C", "Dee D", 202),
    fixture("f3", "Challenger", "Nowhere", "Eve E", "Fay F", 303),             # unknown tier: left out, logged
    fixture("f4", "Challenger Doubles", "Charlottesville", "G/H", "I/J", 101),  # doubles: out
    fixture("f5", "ATP", "Paris", "K K", "L L", 404),                           # tour level: not this block
    fixture("f6", "Challenger", "Charlottesville", "M M", "N N", 101),         # inactive price: out
]
ODDS = [odds("f1", 101, 1.50, 2.55), odds("f2", 202, 2.10, 1.70), odds("f3", 303, 1.9, 1.9),
        odds("f6", 101, 1.8, 1.9, active=False)]


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class Session:
    """Records (path, params) per call. account_body echoes the key, as the real one does."""

    def __init__(self, count=6, fail=None, raise_on=None):
        self.calls, self.count, self.fail, self.raise_on = [], count, fail or {}, raise_on

    def get(self, url, params=None, timeout=None):
        path = url.split("/v4", 1)[1]
        self.calls.append((path, dict(params or {})))
        if self.raise_on == path:   # requests' own exception text carries the full URL, key included
            raise requests.ConnectionError(f"Max retries exceeded with url: {url}?apiKey={params['apiKey']}")
        if path in self.fail:
            return Resp(self.fail[path], {"message": f"bad key {params['apiKey']}"})
        if path == "/account":
            return Resp(200, {"api_key": params["apiKey"], "subscription": {"request_limit": 250,
                                                                            "request_count": self.count}})
        if path == "/fixtures":
            return Resp(200, FIXTURES)
        if path == "/odds-by-tournaments":
            ids = params["tournamentIds"].split(",")
            return Resp(200, [o for o in ODDS if str(o["tournamentId"]) in ids])
        raise AssertionError(path)

    def billable(self):
        return [c for c in self.calls if c[0] != "/account"]


def run(tmp_path, session, key=KEY, now=NOW):
    logs, sleeps = [], []
    doc = op.block(tmp_path, now, TIERS, key=key, session=session, sleep=sleeps.append, log=logs.append)
    return doc, logs, sleeps


def test_rows_tier_filter_orientation_and_power_devig(tmp_path):
    s = Session()
    doc, logs, _ = run(tmp_path, s)
    assert doc["status"] == "ok" and doc["fetched_at"] == "2026-11-05T10:00:00Z"
    m = {r["event_id"]: r for r in doc["matches"]}
    assert sorted(m) == ["f1", "f2"]
    r = m["f1"]
    assert (r["player_1"], r["player_2"], r["tour"], r["tier"]) == ("Ann A", "Bob B", "ATP", "Challenger")
    assert r["draftkings"]["odds_1"] == 1.50 and r["draftkings"]["odds_2"] == 2.55     # outcome 121 = participant1
    assert r["fair_1"] == pytest.approx(float(devig_power([1.50], [2.55])[0]), abs=1e-4)
    assert r["draftkings"]["margin"] == pytest.approx(1 / 1.5 + 1 / 2.55 - 1, abs=1e-4)
    assert m["f2"]["tournament"] == "Cali 125" and m["f2"]["tier"] == "WTA 125"
    assert doc["label"] == "DraftKings (via OddsPapi), pre-match" and "OddsPapi" in doc["credit"]
    assert any("atp:Nowhere" in line for line in logs)
    assert set(r) == {"event_id", "tournament", "tour", "tier", "commence_time", "player_1", "player_2", "draftkings",
                      "fair_1", "dk_implied_1", "model_p1", "model_n1", "model_n2"}   # displayed fields only


def test_calls_quota_guard_first_spacing_and_count(tmp_path):
    s = Session()
    _, _, sleeps = run(tmp_path, s)
    assert [c[0] for c in s.calls] == ["/account", "/fixtures", "/odds-by-tournaments"]
    assert s.calls[1][1]["bookmakers"] == "draftkings" and s.calls[1][1]["sportId"] == 12
    assert s.calls[2][1]["tournamentIds"] == "101,202,303" and s.calls[2][1]["bookmaker"] == "draftkings"
    assert sleeps == [op.GAP_S, op.FIXTURES_GAP_S]


def test_skips_without_key_and_makes_no_call(tmp_path, monkeypatch):
    monkeypatch.delenv(op.KEY_ENV, raising=False)
    s = Session()
    doc, logs, _ = run(tmp_path, s, key="")
    assert doc["status"] == "no_key" and doc["matches"] == [] and s.calls == []
    assert len(logs) == 1 and op.KEY_ENV in logs[0]
    doc = site.challenger_dk_block(s, tmp_path, NOW, None)      # the page build path, too
    assert doc["status"] == "no_key" and s.calls == []


def test_quota_guard_serves_the_cached_copy_without_a_billable_call(tmp_path):
    run(tmp_path, Session())
    s = Session(count=op.QUOTA_STOP)
    doc, logs, _ = run(tmp_path, s, now=NOW + pd.Timedelta(hours=13))
    assert doc["status"] == "quota_guard" and s.billable() == [] and len(doc["matches"]) == 2
    assert doc["fetched_at"] == "2026-11-05T10:00:00Z"                     # the page shows its age


def test_refreshes_at_most_every_12_hours(tmp_path):
    run(tmp_path, Session())
    s = Session()
    doc, _, _ = run(tmp_path, s, now=NOW + pd.Timedelta(hours=11, minutes=59))
    assert doc["status"] == "cached" and s.calls == [] and doc["fetched_at"] == "2026-11-05T10:00:00Z"
    doc, _, _ = run(tmp_path, s, now=NOW + pd.Timedelta(hours=12))
    assert doc["status"] == "ok" and doc["fetched_at"] == "2026-11-05T22:00:00Z"


@pytest.mark.parametrize("make", [lambda: Session(fail={"/fixtures": 401}),
                                  lambda: Session(fail={"/account": 500}),
                                  lambda: Session(raise_on="/odds-by-tournaments"),
                                  lambda: Session(raise_on="/account")])
def test_the_key_never_reaches_output_logs_cache_or_errors(tmp_path, make, capsys):
    run(tmp_path, Session())                       # a good refresh first: the account body echoed the key
    doc, logs, _ = run(tmp_path, make(), now=NOW + pd.Timedelta(hours=13))
    assert doc["status"].startswith("error: ")
    assert " on /" in doc["status"]                # "HTTP <code> on <path>" or "<Error> on <path>"
    text = json.dumps(doc) + "\n".join(logs) + capsys.readouterr().out + (tmp_path / op.CACHE_FILE).read_text()
    assert KEY not in text and "apiKey" not in text and "oddspapi.io/v4" not in text
    assert len(doc["matches"]) == 2                # the last good copy is served


def test_client_errors_name_code_and_path_only():
    c = op.Client(KEY, session=Session(fail={"/fixtures": 429}), sleep=lambda s: None)
    with pytest.raises(op.OddsPapiError) as e:
        c.fixtures(NOW)
    assert str(e.value) == "HTTP 429 on /fixtures" and e.value.__cause__ is None and KEY not in repr(e.value)
    assert c.billable == 1                         # an error is still a billable request
    acct = op.Client(KEY, session=Session(count=7), sleep=lambda s: None).account()
    assert acct == {"request_count": 7, "request_limit": 250}


def test_city_and_tour_names():
    assert op.city_of("Charlottesville, USA") == "charlottesville"
    assert op.city_of("ATP Challenger Bratislava II") == "bratislava"
    assert op.city_of("Cali (Qualifying)") == "cali"
    assert op.tour_of({"categoryName": "WTA 125K", "tournamentName": "Cali"}) == "wta"
    assert op.tour_of({"categoryName": "ITF Men", "tournamentName": "M25 Challenger"}) is None


def test_last_first_names_and_unnamed_fixtures_are_dropped(tmp_path):
    assert op.person("Seyboth Wild, Thiago") == "Thiago Seyboth Wild" and op.person("Ann A") == "Ann A"
    fx = [dict(FIXTURES[0], participant1Name=None)]
    out, notes = op.rows(fx, ODDS, TIERS, NOW)
    assert out == [] and notes == ["1 fixture(s) without both player names"]


def test_orientation_guard_against_polymarket():
    def dk(pairs):
        return {"matches": [{"player_1": a, "player_2": b, "fair_1": f} for a, b, f in pairs]}

    def poly(pairs):
        def q(p):
            return {"bid": p - 0.01, "ask": p + 0.01}
        return {"matches": [{"player_1": a, "player_2": b, "p1": q(p), "p2": q(1 - p)} for a, b, p in pairs]}
    names = [(f"P{i}", f"Q{i}") for i in range(6)]
    same = poly([(a, b, 0.75) for a, b in names])
    assert op.orientation_ok(dk([(a, b, 0.72) for a, b in names]), same)[0] is True
    assert op.orientation_ok(dk([(a, b, 0.28) for a, b in names]), same)[0] is False            # swapped prices
    assert op.orientation_ok(dk([(b, a, 0.28) for a, b in names]), same)[0] is True             # players listed the other way
    assert op.orientation_ok(dk([(a, b, 0.72) for a, b in names[:3]]), same)[0] is None         # too few to tell


@pytest.mark.parametrize("status,make,key", [("cached", lambda: Session(), KEY),
                                             ("quota_guard", lambda: Session(count=op.QUOTA_STOP), KEY),
                                             ("error", lambda: Session(fail={"/account": 500}), KEY),
                                             ("no_key", lambda: Session(), "")])
def test_cached_copies_never_show_matches_that_have_started(tmp_path, status, make, key, monkeypatch):
    monkeypatch.delenv(op.KEY_ENV, raising=False)
    run(tmp_path, Session())                                    # f1 and f2 both start 2026-11-06 09:00
    later = pd.Timestamp("2026-11-06 10:00", tz="UTC")          # 1 h after the start
    if status == "cached":                                     # inside the 12 h refresh: fetched 6 h before the start
        run(tmp_path, Session(), now=pd.Timestamp("2026-11-06 03:00", tz="UTC"))
    doc, _, _ = run(tmp_path, make(), key=key, now=later)
    assert doc["status"].startswith(status) and doc["matches"] == []
