"""DK in-play credit dry run (upsets/dk_inplay.py), synthetic frames only."""

import pandas as pd

from upsets import dk_inplay as di


def w(rows):
    return pd.DataFrame([{"key": k, "commence": pd.Timestamp(c, tz="UTC"), "dur": d, "season": int(c[:4]),
                          "level": "slam"} for k, c, d in rows])


def test_overlapping_matches_of_one_key_share_snapshots():
    one = w([("k", "2024-01-15 10:00", 60)])
    assert len(di.slots(one, 5, 0)) == 13                      # 10:00 .. 11:00 inclusive
    both = w([("k", "2024-01-15 10:00", 60), ("k", "2024-01-15 10:30", 60)])
    assert len(di.slots(both, 5, 0)) == 19                     # 10:00 .. 11:30: shared half hour counted once
    other_key = w([("k", "2024-01-15 10:00", 60), ("j", "2024-01-15 10:00", 60)])
    assert di.credits(other_key, 5, 0) == 2 * 13 * 10


def test_slack_and_the_ten_minute_archive_before_sept_2022():
    m = w([("k", "2024-01-15 10:02", 60)])
    assert min(x for _, x in di.slots(m, 5, 0)) == pd.Timestamp("2024-01-15 10:00", tz="UTC")
    assert len(di.slots(m, 5, 60)) == len(di.slots(m, 5, 0)) + 12
    old = w([("k", "2021-01-15 10:00", 60)])
    assert len(di.slots(old, 5, 0)) == len(di.slots(old, 10, 0)) == 7   # 10-min snapshots only back then


def test_windows_fill_missing_minutes_with_the_best_of_median():
    sack = pd.DataFrame({"minutes": [90.0, 110.0, None, 400.0], "best_of": [3, 3, 3, 5],
                         "season": [2024] * 4, "level_group": ["slam"] * 4})
    priced = pd.DataFrame({"sack_row": [0, 1, 2, 3], "key": "k",
                           "commence": pd.to_datetime(["2024-01-15 10:00"] * 4, utc=True)})
    got = di.windows(priced, sack)
    assert list(got["dur"]) == [90.0, 110.0, 100.0, di.MAX_MINUTES]


def snap_fn(live_until):
    """Fake historical fetch: event e1 (A vs B) listed until `live_until`, plus an unrelated event."""
    calls = []

    def fetch(key, when):
        calls.append(when)
        ts = pd.Timestamp(when)
        data = [{"id": "zz", "commence_time": "2024-01-15T10:00:00Z", "home_team": "C D", "away_team": "E F"}]
        if ts <= pd.Timestamp(live_until, tz="UTC"):
            data.append({"id": "e1", "commence_time": "2024-01-15T10:00:00Z", "home_team": "Bee Bob",
                         "away_team": "Ann Aye"})
        return {"timestamp": when, "data": data}
    return fetch, calls


def match_w():
    return pd.DataFrame([{"key": "k", "commence": pd.Timestamp("2024-01-15 10:00", tz="UTC"), "dur": 90,
                          "season": 2024, "level": "slam",
                          "pair": frozenset((di.pkey("Ann Aye"), di.pkey("Bob Bee")))}])


def test_walk_resolves_the_event_and_stops_after_the_match_is_gone():
    fetch, calls = snap_fn("2024-01-15 11:20")
    res = di.walk(match_w(), fetch, step_min=10, slack_min=180)
    m = res["matches"].iloc[0]
    assert m["event_id"] == "e1" and m["snaps"] == 9                     # 10:00 .. 11:20
    assert m["finished_at"] == pd.Timestamp("2024-01-15 11:50", tz="UTC")  # 3 snapshots without it: 11:30, 11:40, 11:50
    assert len(calls) == 12 and not res["stopped"]                       # not the planned 10:00 .. 14:30 (28)


def test_walk_stops_at_the_cap():
    fetch, calls = snap_fn("2024-01-15 11:20")
    n = {"left": 3}

    def capped(key, when):
        if n["left"] == 0:
            return None
        n["left"] -= 1
        return fetch(key, when)
    res = di.walk(match_w(), capped, step_min=10, slack_min=180)
    assert res["stopped"] and res["fetched"] == 3


def test_event_found_by_names_when_dk_moves_the_start_and_unknown_matches_stop():
    snap = {"data": [{"id": "e9", "commence_time": "2024-01-15T10:40:00Z", "home_team": "Christopher O'Connell",
                      "away_team": "Bee Bob"}]}
    pair = frozenset((di.pkey("Christopher Oconnell"), di.pkey("Bob Bee")))
    assert di._event_id(snap, pd.Timestamp("2024-01-15 10:00", tz="UTC"), pair) == "e9"
    w = match_w().assign(pair=[frozenset(("nobody", "else"))])
    fetch, calls = snap_fn("2024-01-15 11:20")
    res = di.walk(w, fetch, step_min=10, slack_min=180)
    assert res["matches"].iloc[0]["event_id"] is None and len(calls) == 5   # 10:00 .. 10:40: 3 in-window misses


def test_full_pull_goes_newest_season_first_and_stops_at_the_cap():
    older = match_w().assign(season=2023, commence=pd.Timestamp("2023-01-15 10:00", tz="UTC"))
    newer = match_w()                                                          # 2024
    order = []

    def fetch(key, when):
        order.append(when[:4])
        return None if len(order) > 4 else {"timestamp": when, "data": []}
    res = di.walk_recent_first(pd.concat([older, newer], ignore_index=True), fetch)
    assert order[0] == "2024" and set(order[:4]) == {"2024"} and res["stopped"]   # 2023 never reached


def test_make_fetch_stops_at_the_job_cap_and_the_drift_budget(tmp_path, monkeypatch):
    from upsets import dk_history as dh
    monkeypatch.setattr(di, "INPLAY_CACHE", tmp_path / "inplay")
    monkeypatch.setattr(dh, "CACHE", tmp_path / "close")
    log = tmp_path / "spend.log"

    class Api:
        calls = 0

        def historical_odds(self, key, when, bookmakers=None):
            Api.calls += 1
            with open(log, "a") as f:
                f.write("t\t/x\t10\t0\n")                    # what OddsApi logs for a 10-credit call
            return {"timestamp": when, "data": []}
    log.write_text("t\t/x\t100\t0\n")                                           # the job has spent 100 so far
    f = di.make_fetch(Api(), log, cap=1000, stage_budget=25, pause_s=0)
    assert f("k", "2024-01-15T10:00:00Z") and f("k", "2024-01-15T10:10:00Z")   # 20 of the 25 budget
    assert f("k", "2024-01-15T10:20:00Z") is None and f.why == "per-match drift budget"
    assert f("k", "2024-01-15T10:00:00Z") is not None and Api.calls == 2         # cached: free, still allowed
    g = di.make_fetch(Api(), log, cap=125, pause_s=0)                            # job total is 120 now
    assert g("k", "2024-01-15T11:00:00Z") is None and g.why == "job cap" and Api.calls == 2
