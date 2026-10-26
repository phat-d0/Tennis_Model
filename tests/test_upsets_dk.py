"""DraftKings history planner/puller + DK study, on synthetic Sackmann rows and synthetic Odds API
JSON only (no real odds in git)."""

import numpy as np
import pandas as pd
import pytest

from upsets import dk_history as dh
from upsets import dk_study as ds
from upsets import elo, sackmann
from upsets.odds_api import OddsApi

COLS = ["tourney_id", "tourney_name", "surface", "draw_size", "tourney_level", "tourney_date",
        "match_num", "winner_id", "winner_seed", "winner_entry", "winner_name", "loser_id",
        "loser_seed", "loser_entry", "loser_name", "score", "best_of", "round",
        "winner_rank", "winner_rank_points", "loser_rank", "loser_rank_points"]


def srow(tid, name, level, date, rnd, w, l, num, ws=None, ls=None, score="6-3 6-3", draw=128, bo=3):
    return dict(zip(COLS, [tid, name, "Hard", draw, level, date, num, w, ws, None, f"Player {w.upper()}",
                           l, ls, None, f"Player {l.upper()}", score, bo, rnd, 10, 1000, 50, 500]))


def sack_frame():
    """ATP + WTA 'Australian Open' 2024 sharing one tourney_id (as in Sackmann), a 2019 Slam
    (before the API's history) and a 2023 1000 (before 1000s history), plus history for Elo."""
    atp, wta = [], []
    rng = np.random.default_rng(0)
    for i in range(300):   # history 2015-2023 for the calibration fit
        a, b = f"h{i % 20}", f"h{(i * 7 + 3) % 20}"
        if a != b:
            atp.append(srow(f"h{i}", "Hist", "A", 20150105 + 10000 * (i // 40) + (i % 40) * 2,
                            "R32", a, b, i, draw=32))
    atp += [srow("2019-580", "Australian Open", "G", 20190114, "R128", "a", "b", 1),
            srow("2023-0404", "Indian Wells Masters", "M", 20230308, "R128", "a", "b", 1),
            srow("2024-580", "Australian Open", "G", 20240115, "R128", "a", "b", 1, ws=1, bo=5),
            srow("2024-580", "Australian Open", "G", 20240115, "R128", "c", "d", 2, ls=3,
                 score="2-1 RET", bo=5),
            srow("2024-580", "Australian Open", "G", 20240115, "R64", "a", "e", 3, ws=1, bo=5),
            srow("2024-580", "Australian Open", "G", 20240115, "R32", "a", "f", 4, ws=1, bo=5)]
    wta += [srow("2024-580", "Australian Open", "G", 20240115, "R128", "x", "y", 1, ls=2)]
    df = pd.concat([sackmann.normalize(pd.DataFrame(atp, columns=COLS), "atp"),
                    sackmann.normalize(pd.DataFrame(wta, columns=COLS), "wta")], ignore_index=True)
    df = df.sort_values(["date", "round_idx"], kind="stable").reset_index(drop=True)
    return elo.add_elo(df, keys=("winner_id", "loser_id"))


KEYS = ["tennis_atp_aus_open_singles", "tennis_wta_aus_open_singles", "tennis_atp_indian_wells",
        "tennis_atp_china_open"]


def test_tournaments_scope_and_tours():
    t = dh.tournaments(sack_frame(), KEYS)
    assert sorted(zip(t["key"], t["tourney_id"], t["season"])) == [
        ("tennis_atp_aus_open_singles", "2024-580", 2024), ("tennis_wta_aus_open_singles", "2024-580", 2024)]
    r = t.iloc[0]
    assert r["win_start"] == pd.Timestamp("2024-01-13") and r["win_end"] == pd.Timestamp("2024-01-20")
    sched = dh.events_schedule(t, 24)
    assert len(sched) == 2 * 8 and sched["when"].iloc[0] == "2024-01-13T00:00:00Z"


# --- fake Odds API -----------------------------------------------------------------------------

def ev(eid, commence, home, away, dk=None, pin=None):
    e = {"id": eid, "sport_key": "k", "commence_time": commence, "home_team": home, "away_team": away}
    books = []
    for key, pr in (("draftkings", dk), ("pinnacle", pin)):
        if pr:
            books.append({"key": key, "last_update": commence, "markets": [{"key": "h2h", "outcomes": [
                {"name": home, "price": pr[0]}, {"name": away, "price": pr[1]}]}]})
    if dk or pin:
        e["bookmakers"] = books
    return e


class Resp:
    def __init__(self, body, cost, remaining):
        self._b, self.status_code = body, 200
        self.headers = {"x-requests-last": str(cost), "x-requests-remaining": str(remaining)}

    def json(self):
        return self._b

    def raise_for_status(self):
        pass


class Session:
    """Routes /historical/sports/{key}/{events|odds}?date= to canned bodies; counts calls."""

    def __init__(self, listings, snapshots, remaining=5000):
        self.listings, self.snapshots, self.remaining, self.calls = listings, snapshots, remaining, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        if url.endswith("/sports"):
            return Resp([], 0, self.remaining)
        key, kind = url.split("/sports/")[1].split("/")[:2]
        when = params["date"]
        if kind == "events":
            data = self.listings.get((key, when), [])
            cost = 1 if data else 0
            body = {"timestamp": when, "data": data}
        else:
            ts, data = self.snapshots.get((key, when), (when, []))
            cost = 10
            body = {"timestamp": ts, "data": data}
        self.remaining -= cost
        return Resp(body, cost, self.remaining)


A_KEY = "tennis_atp_aus_open_singles"


def fixtures():
    listings = {(A_KEY, "2024-01-14T00:00:00Z"): [
        ev("e1", "2024-01-15T01:00:00Z", "Player A", "Player B"),     # R1, seed 1 vs unseeded
        ev("e2", "2024-01-15T03:30:00Z", "Player D", "Player C"),     # R1, D retires in set 1: void
        ev("e9", "2024-01-15T04:00:00Z", "Nobody Known", "Player Z")]}  # unknown players
    listings[(A_KEY, "2024-01-16T00:00:00Z")] = [ev("e3", "2024-01-17T08:00:00Z", "Player E", "Player A"),  # R2
                                                ev("e4", "2024-01-19T08:00:00Z", "Player A", "Player F")]  # R3
    snaps = {
        (A_KEY, "2024-01-15T00:55:00Z"): ("2024-01-15T00:50:00Z", [
            ev("e1", "2024-01-15T01:00:00Z", "Player A", "Player B", dk=(1.25, 3.9), pin=(1.22, 4.6)),
            ev("e2", "2024-01-15T03:30:00Z", "Player D", "Player C", dk=(2.6, 1.5), pin=(2.7, 1.5))]),
        (A_KEY, "2024-01-17T07:55:00Z"): ("2024-01-17T07:50:00Z", [
            ev("e3", "2024-01-17T08:00:00Z", "Player E", "Player A", dk=(5.0, 1.17), pin=(5.5, 1.16))]),
    }
    return listings, snaps


def test_pull_cache_cap_and_spend_log(tmp_path):
    sack = sack_frame()
    t = dh.tournaments(sack, KEYS)
    t = t[t["key"] == A_KEY]
    listings, snaps = fixtures()
    s = Session(listings, snaps)
    api = OddsApi(floor=100, key="SECRET", session=s, spend_log=tmp_path / "spend.log")
    sched = dh.events_schedule(t, 24)
    res = dh.pull(api, "events", sched, cap=1000, root=tmp_path, pause_s=0)
    assert res == {"done": 8, "cached": 0, "stopped": None}
    assert dh.logged_total(tmp_path / "spend.log") == 2        # empty listings cost 0
    n = len(s.calls)
    again = dh.pull(api, "events", sched, cap=1000, root=tmp_path, pause_s=0)
    assert again["done"] == 0 and again["cached"] == 8 and len(s.calls) == n   # never repeated
    assert "SECRET" not in (tmp_path / "spend.log").read_text()

    text, parts = dh.dry_run(t, sack, 24, 6, 5, tmp_path)
    assert "exact" in text and "estimate" not in text
    req, need = parts["req"], parts["need"]
    assert sorted(need["event_id"]) == ["e1", "e2", "e3"]      # R3 and unknown players: no price needed
    # e1 (01:00) and e2 (03:30) share the 00-06 cell: one snapshot at e1's deadline
    assert list(req["when"]) == ["2024-01-15T00:55:00Z", "2024-01-17T07:55:00Z"]
    assert parts["credits_new"] == 20
    stopped = dh.pull(api, "odds", req, cap=12, root=tmp_path, pause_s=0)
    assert stopped["done"] == 1 and stopped["stopped"]          # 2 + 10 = 12; the next would pass 12
    rest = dh.pull(api, "odds", req, cap=1000, root=tmp_path, pause_s=0)
    assert rest["done"] == 1 and rest["cached"] == 1
    assert dh.logged_total(tmp_path / "spend.log") == 22


def test_dry_run_without_listings_is_an_estimate_and_makes_no_calls(tmp_path):
    sack = sack_frame()
    t = dh.tournaments(sack, KEYS)
    text, parts = dh.dry_run(t, sack, 24, 6, 5, tmp_path)
    assert "estimate" in text and parts["totals"]["listing_new"] == 16
    assert parts["credits_new"] == 16 + 10 * 2 * 5 * 3      # 5 play days x 3 cells, 2 keys


def _pulled(tmp_path):
    sack = sack_frame()
    t = dh.tournaments(sack, KEYS)
    listings, snaps = fixtures()
    snaps[(A_KEY, "2024-01-17T09:00:00Z")] = ("2024-01-17T09:00:00Z", [   # after e3's start: ignored
        ev("e3", "2024-01-17T08:00:00Z", "Player E", "Player A", dk=(1.01, 30.0), pin=(1.01, 30.0))])
    s = Session(listings, snaps)
    api = OddsApi(floor=100, key="K", session=s, spend_log=tmp_path / "spend.log")
    dh.pull(api, "events", dh.events_schedule(t, 24), cap=1000, root=tmp_path, pause_s=0)
    _, parts = dh.dry_run(t, sack, 24, 6, 5, tmp_path)
    dh.pull(api, "odds", parts["req"], cap=1000, root=tmp_path, pause_s=0)
    dh.pull(api, "odds", pd.DataFrame([{"key": A_KEY, "when": "2024-01-17T09:00:00Z"}]), 1000, tmp_path, 0)
    return sack, t


def test_prices_orientation_and_no_post_start_snapshot(tmp_path):
    sack, t = _pulled(tmp_path)
    priced = dh.collect(t, sack, 24, root=tmp_path).set_index("sack_row")
    row = lambda w, l: sack.index[(sack["winner_id"] == w) & (sack["loser_id"] == l)  # noqa: E731
                                  & (sack["tourney_id"] == "2024-580")][0]
    r1, r2, rv = row("a", "b"), row("a", "e"), row("c", "d")
    assert priced.loc[r1, "odds_w_draftkings"] == 1.25 and priced.loc[r1, "odds_l_draftkings"] == 3.9
    # e3 lists E as home; a (= A) won: odds re-oriented, and the 09:00 in-play snapshot is not used
    assert priced.loc[r2, "odds_w_draftkings"] == 1.17 and priced.loc[r2, "odds_l_draftkings"] == 5.0
    assert priced.loc[r2, "age_min_draftkings"] == 10
    # e2 lists D (who retired in set 1) as home; C won
    assert priced.loc[rv, "odds_w_draftkings"] == 1.5 and priced.loc[rv, "odds_l_draftkings"] == 2.6
    assert len(priced) == 3


def test_study_settlement_void_and_report(tmp_path):
    sack, t = _pulled(tmp_path)
    priced = dh.collect(t, sack, 24, root=tmp_path)
    f = ds.frame(priced, sack, fit_min_n=0).set_index("sack_row")
    row = lambda w, l: sack.index[(sack["winner_id"] == w) & (sack["loser_id"] == l)  # noqa: E731
                                  & (sack["tourney_id"] == "2024-580")][0]
    r1, rv = row("a", "b"), row("c", "d")
    assert f.loc[r1, "upset"] == 0 and f.loc[r1, "odds_dog_dk"] == 3.9 and f.loc[r1, "seed_fav"] == 1
    assert f.loc[rv, "void"] and f.loc[rv, "upset"] == 0     # dog D retired in set 1: void
    p = ds.pnl(f.reset_index())
    assert p[f.reset_index()["sack_row"] == rv].iloc[0] == 0.0
    assert p[f.reset_index()["sack_row"] == r1].iloc[0] == -1.0
    assert 0 < f.loc[r1, "p_model"] < 1 and f.loc[r1, "margin_dk"] == pytest.approx(1 / 1.25 + 1 / 3.9 - 1)
    text, parts = ds.run(priced, sack, min_n=0, min_select_bets=1, fit_min_n=0)
    assert "Gate:" in text and "DraftKings vs Pinnacle" in text


def test_walk_forward_uses_earlier_seasons_only():
    rng = np.random.default_rng(1)
    rows = []
    for y in range(2020, 2026):
        for _ in range(200):
            e = rng.uniform(-0.2, 0.3)
            win = rng.random() < (0.5 if e >= 0.10 else 0.2)
            rows.append({"season": y, "edge": e, "odds_dog_dk": 3.0, "upset": int(win), "void": False,
                         "min_n": 50, "tour": "atp"})
    f = pd.DataFrame(rows)
    oos, seasons = ds.walk_forward(f, min_select_bets=30)
    assert list(seasons["season"]) == [2021, 2022, 2023, 2024, 2025]
    assert (seasons["threshold"] == 0.10).all()
    g = ds.gate(oos, seasons)
    assert g["pass"]
    f2 = f.copy()
    f2.loc[f2["season"] == 2025, "upset"] = 0                  # the test season's own results...
    _, s2 = ds.walk_forward(f2, min_select_bets=30)
    assert list(s2["threshold"]) == list(seasons["threshold"])   # ...never choose its threshold


def test_api_error_stops_pull_and_caches_nothing(tmp_path):
    import requests

    class ErrResp(Resp):
        def raise_for_status(self):
            raise requests.HTTPError("401 HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN")

    class ErrSession(Session):
        def get(self, url, params=None, timeout=None):
            if "/historical/" in url:
                return ErrResp({"error_code": "HISTORICAL_UNAVAILABLE_ON_FREE_USAGE_PLAN"}, 0, self.remaining)
            return super().get(url, params, timeout)

    api = OddsApi(floor=100, key="K", session=ErrSession({}, {}), spend_log=tmp_path / "spend.log")
    todo = pd.DataFrame([{"key": A_KEY, "when": "2024-01-14T00:00:00Z"}])
    with pytest.raises(requests.HTTPError):
        dh.pull(api, "events", todo, cap=1000, root=tmp_path, pause_s=0)
    assert not list(tmp_path.glob("events/**/*.json.gz"))


def test_projection_beyond_sackmann_and_other_tier():
    sack = sack_frame()
    t = dh.tournaments(sack, KEYS, project_until=pd.Timestamp("2025-06-01"))
    proj = t[t["projected"]]
    # every edition from the last year whose next edition isn't in the data: AO 2024 (both tours)
    # -> 2025, Indian Wells 2023 -> 2024
    assert sorted(zip(proj["key"], proj["date"].dt.date.astype(str))) == [
        ("tennis_atp_aus_open_singles", "2025-01-13"), ("tennis_atp_indian_wells", "2024-03-06"),
        ("tennis_wta_aus_open_singles", "2025-01-13")]
    assert proj.set_index("key").loc["tennis_atp_aus_open_singles", "n_r12"] == 3
    # 250/500 keys are out of scope unless "other" has a history start
    s2 = sack.copy()
    s2.loc[s2["tourney_id"] == "2024-580", "level_group"] = "other"
    assert dh.tournaments(s2, KEYS).empty
    hs = {**dh.HIST_START, "other": pd.Timestamp("2024-01-01")}
    assert len(dh.tournaments(s2, KEYS, hist_start=hs)) == 2


def test_needed_covers_first_days_of_projected_events():
    j = pd.DataFrame({
        "key": ["k"] * 4 + ["s"], "tourney_id": ["p+52w"] * 4 + ["2024-580"],
        "commence": pd.to_datetime(["2026-06-15 10:00", "2026-06-17 12:00", "2026-06-18 09:00",
                                    "2026-06-20 12:00", "2024-01-15 01:00"]),
        "sack_row": [-1, -1, -1, -1, 7], "round_idx": [np.nan] * 4 + [1.0]})
    t = pd.DataFrame({"key": ["k", "s"], "tourney_id": ["p+52w", "2024-580"], "projected": [True, False],
                      "r12_days": [3, 5]})
    assert list(dh.needed(j, t)) == [True, True, False, False, True]   # days 1-3 of the projected event


def test_pull_stops_if_an_empty_listing_costs_credits(tmp_path):
    class Costly(Session):
        def get(self, url, params=None, timeout=None):
            if "/historical/" in url and url.endswith("/events"):
                self.remaining -= 1
                return Resp({"timestamp": params["date"], "data": []}, 1, self.remaining)
            return super().get(url, params, timeout)

    api = OddsApi(floor=100, key="K", session=Costly({}, {}), spend_log=tmp_path / "spend.log")
    todo = pd.DataFrame([{"key": A_KEY, "when": f"2024-01-1{i}T00:00:00Z"} for i in range(3)])
    res = dh.pull(api, "events", todo, cap=1000, root=tmp_path, pause_s=0)
    assert res["done"] == 1 and "empty listing cost credits" in res["stopped"]


def test_needed_ignores_stale_events_outside_the_window():
    j = pd.DataFrame({"key": ["k"] * 3, "tourney_id": ["p+52w"] * 3,
                      "commence": pd.to_datetime(["2025-10-01 06:00", "2026-09-30 03:00", "2026-10-01 03:00"]),
                      "sack_row": [-1] * 3, "round_idx": [np.nan] * 3})
    t = pd.DataFrame({"key": ["k"], "tourney_id": ["p+52w"], "projected": [True], "r12_days": [3],
                      "win_start": [pd.Timestamp("2026-09-16")], "win_end": [pd.Timestamp("2026-10-04")]})
    assert list(dh.needed(j, t)) == [False, True, True]   # last year's final in an old snapshot: out


def test_results_from_kalshi_and_unresolved_frame():
    u = pd.DataFrame({"key": ["tennis_atp_halle_open"] * 3, "tourney_id": ["h+52w"] * 3,
                      "event_id": ["x1", "x2", "x3"],
                      "commence": pd.to_datetime(["2026-06-16 10:00", "2026-06-16 12:00", "2026-06-17 12:00"]),
                      "home": ["Jan-Lennard Struff", "Ugo Humbert", "A B"], "away": ["Félix Auger-Aliassime", "C D", "E F"],
                      "odds_home_draftkings": [3.2, 1.5, 2.0], "odds_away_draftkings": [1.35, 2.6, 1.8],
                      "odds_home_pinnacle": [3.4, 1.52, np.nan], "odds_away_pinnacle": [1.36, 2.7, np.nan],
                      "age_min_draftkings": [9.0, 9.0, 9.0], "age_min_pinnacle": [9.0, 9.0, np.nan]})
    km = pd.DataFrame({"match_id": ["K1", "K2", "K3"], "series": ["KXATPMATCH"] * 3,
                       "scheduled_start": pd.to_datetime(["2026-06-16 10:30", "2026-06-16 12:10", "2026-06-25 12:00"], utc=True),
                       "player_a": ["Felix Auger Aliassime", "C D", "A B"], "player_b": ["Jan Lennard Struff", "Ugo Humbert", "E F"],
                       "settle_a": [0.0, 0.43, 1.0], "settle_b": [1.0, 0.57, 0.0]})
    res = ds.results_from_kalshi(ds.match_list(u), km).set_index("event_id")
    assert res.loc["x1", "winner"] == "home" and not res.loc["x1", "void"]      # Struff (home, dog) won
    assert res.loc["x2", "void"]                                                # fair price: not started
    assert "x3" not in res.index                                                # 8 days apart: no match
    assert "odds_home_draftkings" not in ds.match_list(u).columns              # no odds leave the container
    f = ds.frame_unresolved(u, res.reset_index())
    r = f.set_index(f["odds_dog_dk"])
    assert r.loc[3.2, "upset"] == 1 and r.loc[3.2, "odds_fav_dk"] == 1.35 and r.loc[3.2, "tour"] == "atp"
    assert r.loc[2.6, "void"]
    assert ds.pnl(f).sum() == pytest.approx(3.2 - 1)


def test_results_from_data_table():
    ml = pd.DataFrame({"event_id": ["e1", "e2", "e3", "e4"], "tour": ["atp", "wta", "wta", "atp"],
                       "commence": ["2026-10-02 12:30:00", "2026-08-24 21:12:50", "2026-10-22 11:00:00",
                                    "2026-07-28 15:00:00"],
                       "home": ["Bu Yunchaokete", "Maria Camila Osorio Serrano", "Elena Rybakina", "Ugo Humbert"],
                       "away": ["Novak Djokovic", "Ann Li", "Polina Kudermetova", "Andrej Martin"]})
    tbl = pd.DataFrame({
        "tournament": ["ATP Beijing", "WTA Monterrey", "WTA Ningbo", "ATP Washington"],
        "scheduled_start": ["2026-10-02T12:30Z", "2026-08-24T21:00Z", "2026-10-22T11:00Z", "2026-07-28T15:00Z"],
        "tour": ["ATP", "WTA", "WTA", "ATP"], "round": ["Round Of 16", "Round Of 32", "Round Of 16", "Round Of 32"],
        "player_a": ["Yunchaokete Bu", "Camila Osorio", "Elena Rybakina", "Ugo Humbert"],
        "player_b": ["Novak Djokovic", "Ann Li", "Polina Kudermetova", "Andres Martin"],
        "winner": ["B", "B", "A", "A"], "settle_a": [0.0, 0.0, 1.0, 1.0], "settle_b": [1.0, 1.0, 0.0, 0.0],
        "not_started": [False, False, False, False], "set1_status": ["decided", "decided", "fair_price", "missing"]})
    r = ds.results_from_table(ml, tbl).set_index("event_id")
    assert r.loc["e1", "winner"] == "away" and not r.loc["e1", "void"]       # word order: Bu Yunchaokete
    assert r.loc["e2", "winner"] == "away"                                    # subset: Camila Osorio
    assert r.loc["e3", "void"]                                                # retired in set 1
    assert "e4" not in r.index                                                # Andrej != Andres
