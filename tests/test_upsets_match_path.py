"""Match path on Kalshi: leg carry/staleness, flips with hysteresis, set paths, exclusions,
report and examples. Synthetic frames only."""

import numpy as np
import pandas as pd
import pytest

from swinglock.config import kalshi_fees, load_config
from swinglock.locks import buy_cost
from upsets import match_path as mp

T0 = pd.Timestamp("2026-06-01 12:00", tz="UTC")


def at(minutes):
    return T0 + pd.Timedelta(minutes=minutes)


def test_flips_need_hysteresis_and_hold():
    ts = pd.Series([at(m) for m in range(0, 20)])
    # 1c noise around 0.5 never flips; a 0.40 run for 1 min doesn't; a 0.40 run for 3 min does
    p = pd.Series([0.51, 0.49, 0.51, 0.49, 0.40, 0.52, 0.52, 0.40, 0.40, 0.40, 0.40,
                   0.50, 0.53, 0.56, 0.56, 0.56, 0.56, 0.6, 0.6, 0.6])
    f = mp.flips(ts, p)
    assert f == [at(7), at(13)]


def test_leg_series_and_asof_staleness():
    q = pd.DataFrame({"ts": [at(0), at(2), at(5), at(50)], "side": ["A", "B", "A", "A"],
                      "ask": [0.6, 0.42, 0.55, 0.3]})
    s = mp.leg_series(q)
    assert mp.asof(s, at(6)) == (0.55, 0.42)
    assert np.isnan(mp.asof(s, at(10))[0])            # B last quoted 8 min ago > 5 min cap
    assert np.isnan(s.loc[s["ts"] == at(50), "ask_b"].iloc[0])   # B carried > 30 min: dropped


def frames():
    rows, q, sets = [], [], []

    def match(mid, series, settle_a, pre_a, pre_b):
        rows.append({"match_id": mid, "series": series, "tier": "x", "scheduled_start": T0,
                     "player_a": f"{mid} A", "player_b": f"{mid} B", "settle_a": settle_a,
                     "settle_b": 1 - settle_a, "fee_type": "quadratic", "fee_multiplier": 1.0})
        quote(mid, -10, pre_a, pre_b)

    def quote(mid, minute, a, b):
        q.append({"ts": at(minute), "match_id": mid, "side": "A", "ask": a})
        q.append({"ts": at(minute), "match_id": mid, "side": "B", "ask": b})

    def sset(mid, no, minute, side, status="decided"):
        sets.append({"match_id": mid, "set_no": no, "close_time": at(minute), "winner_side": side,
                     "status": status})

    # M1 ATP bo3: fav A loses set 1 (flip), wins set 2 (flip back), wins the decider
    match("M1", "KXATPMATCH", 1.0, 0.70, 0.33)
    for minute, a, b in [(1, .68, .34), (20, .60, .42), (39, .40, .62), (42, .38, .64), (45, .40, .62),
                         (60, .50, .52), (79, .60, .42), (81, .62, .40), (84, .63, .39), (100, .80, .22),
                         (130, .99, .02)]:
        quote("M1", minute, a, b)
    sset("M1", 1, 40, "B")
    sset("M1", 2, 80, "A")
    # M2 WTA bo3: fav B wins in straight sets, no flip
    match("M2", "KXWTAMATCH", 0.0, 0.25, 0.78)
    for minute, a, b in [(1, .24, .78), (30, .15, .87), (31, .15, .87), (60, .05, .96), (61, .04, .97)]:
        quote("M2", minute, a, b)
    sset("M2", 1, 30, "B")
    sset("M2", 2, 60, "B")
    # M3 ATP Challenger (no set markets): fav A loses
    match("M3", "KXATPCHALLENGERMATCH", 0.0, 0.66, 0.36)
    for minute, a, b in [(1, .66, .36), (50, .30, .72), (55, .25, .77), (90, .02, .99)]:
        quote("M3", minute, a, b)
    # M4: retirement (fair-price set 2): excluded
    match("M4", "KXATPMATCH", 1.0, 0.70, 0.33)
    quote("M4", 5, .7, .32)
    sset("M4", 1, 40, "A")
    sset("M4", 2, 60, None, "fair_price")
    # M5: set close 2 h after the last quote: unreliable -> no set path
    match("M5", "KXWTAMATCH", 1.0, 0.60, 0.42)
    quote("M5", 30, .7, .32)
    quote("M5", 60, .97, .04)
    sset("M5", 1, 30, "A")
    sset("M5", 2, 180, "A")
    details = pd.DataFrame({"match_id": ["M1", "M2", "M4", "M5"], "round": "R1", "best_of": ["3"] * 4,
                            "tournament_name": "T", "gender": "x"})
    return pd.DataFrame(rows), pd.DataFrame(q), pd.DataFrame(sets), details


def test_path_table():
    m, q, s, d = frames()
    t, series = mp.path_table(m, q, s, d)
    t = t.set_index("match_id")
    r = t.loc["M1"]
    assert r["fav"] == "A" and r["pre_ask"] == 0.70 and r["fav_won"] == 1
    assert r["path"] == "LWW" and r["decider"] and r["pen_fav_won"] == 1
    assert r["n_flips"] == 2 and r["first_flip_set"] == 1
    assert r["first_flip_min"] == pytest.approx(39)
    assert r["set1_ask"] == pytest.approx(0.40) and r["set2_ask"] == pytest.approx(0.62)  # close + 90 s
    assert r["set_ok"] and not r["set_unreliable"]
    assert t.loc["M2", "fav"] == "B" and t.loc["M2", "path"] == "WW" and t.loc["M2", "n_flips"] == 0
    assert t.loc["M3", "tour"] == "ATP-Ch" and not t.loc["M3", "has_sets"] and t.loc["M3", "n_flips"] == 1
    assert t.loc["M4", "set_fair"]
    assert t.loc["M5", "set_unreliable"] and not t.loc["M5", "set_ok"]
    assert t.loc["M1", "p_min"] == pytest.approx((0.38 + 1 - 0.64) / 2)


def test_report_and_examples():
    m, q, s, d = frames()
    t, series = mp.path_table(m, q, s, d)
    text = mp.report(t, load_config())
    for part in ("Coverage", "By set path", "Favourite flips", "Average path", "Price test",
                 "Penultimate-set winner"):
        assert part in text
    assert "| ATP bo3 | LWW | 1 |" in text
    ex = mp.examples(t, series, m)
    assert [e["match_id"] for e in ex] == ["M1"]
    assert ex[0]["favourite"] == "M1 A" and len(ex[0]["points"]) <= 60 and ex[0]["set_ends_min"] == [40.0, 80.0]


def test_buy_costs_match_fee_model():
    m, q, s, d = frames()
    t, _ = mp.path_table(m, q, s, d)
    t = t[t["match_id"] == "M1"]
    b = mp.buy(t, "set2_ask", t["settle_fav"], load_config())
    fees = kalshi_fees(load_config(), "quadratic", 1.0)
    assert b["cost_0c"].iloc[0] == pytest.approx(buy_cost(0.62, 100, fees))
    assert b["pnl_0c"].iloc[0] == pytest.approx(100 - buy_cost(0.62, 100, fees))


def test_batch_close_times_are_unreliable():
    sets = pd.DataFrame({"match_id": [f"M{i}" for i in range(6)], "set_no": 1,
                         "close_time": [at(600)] * 5 + [at(30)], "winner_side": "A", "status": "decided"})
    last = pd.Series({f"M{i}": at(700) for i in range(6)})
    flags = mp.unreliable_sets(sets, last)
    assert list(flags) == [True] * 5 + [False]


def test_decider_guard_applies_to_match_path():
    m, q, s, d = frames()
    t, _ = mp.path_table(m, q, s, d)
    assert t.set_index("match_id").loc["M1", "decider_ok"]
    m["close_time"] = at(85)                     # decider (starts +80) would last 5 min
    t, _ = mp.path_table(m, q, s, d)
    r = t.set_index("match_id").loc["M1"]
    assert r["decider"] and not r["decider_ok"]
    assert "| ATP bo3 | all |" not in mp.report(t, load_config())   # no levelling-player bet


@pytest.mark.parametrize("letters,bo,won,expect", [
    ("WW", 3, 1, ("complete", "WW")),
    ("WL", 3, 0, ("decider", "WLL")),
    ("WL", 5, 1, ("incomplete", "incomplete")),     # bo5 at 1-1, set 3 unlisted: not a decider
    ("WLW", 5, 1, ("incomplete", "incomplete")),    # 2-1 in bo5, set 4 missing
    ("WLWL", 5, 1, ("decider", "WLWLW")),
    ("WWW", 5, 1, ("complete", "WWW")),
    ("WW", 3, 0, ("inconsistent", "inconsistent")),  # listed sets disagree with the settlement
    ("WL", float("nan"), 1, ("incomplete", "incomplete")),
])
def test_classify_path(letters, bo, won, expect):
    assert mp.classify_path(list(letters), bo, won) == expect


def test_bo5_at_one_all_is_not_a_decider():
    m, q, s, d = frames()
    d.loc[d["match_id"] == "M1", "best_of"] = "5"     # M1 has sets 1-2 listed, 1-1
    t, _ = mp.path_table(m, q, s, d)
    r = t.set_index("match_id").loc["M1"]
    assert not r["decider"] and r["path_kind"] == "incomplete" and r["path_listed"] == "LW"


def test_set_end_states_only_while_in_play():
    m, q, s, d = frames()
    t, _ = mp.path_table(m, q, s, d)
    t = t.set_index("match_id")
    assert t.loc["M1", "set1_live"] and t.loc["M1", "set2_live"]       # 1-1: decider still to play
    assert t.loc["M2", "set1_live"] and not t.loc["M2", "set2_live"]   # 2-0: match over
    text = mp.report(t.reset_index(), load_config())
    price = text.split("## Price test at each set end")[1].split("## Penultimate")[0]
    assert "| WTA bo3 | 2 |" not in price and "| ATP bo3 | 2 |" in price


def test_post_match_junk_is_cleaned():
    rows = [{"match_id": "J1", "series": "KXATPMATCH", "tier": "x", "scheduled_start": T0, "player_a": "a",
             "player_b": "b", "settle_a": 1.0, "settle_b": 0.0, "fee_type": "quadratic", "fee_multiplier": 1.0,
             "tournament": "T"}]
    q = []
    for minute, a, b in [(-10, .65, .37), (1, .64, .38), (41, .8, .22), (79, .99, .01),
                         (81, .04, .97), (85, .03, .98)]:      # after the end: junk book
        q += [{"ts": at(minute), "match_id": "J1", "side": "A", "ask": a},
              {"ts": at(minute), "match_id": "J1", "side": "B", "ask": b}]
    sets = pd.DataFrame({"match_id": "J1", "set_no": [1, 2], "close_time": [at(40), at(80)],
                         "winner_side": ["A", "A"], "status": "decided"})
    d = pd.DataFrame({"match_id": ["J1"], "round": "R1", "best_of": ["3"], "tournament_name": "T", "gender": "m"})
    t, _ = mp.path_table(pd.DataFrame(rows), pd.DataFrame(q), sets, d)
    r = t.iloc[0]
    assert r["p_min_raw"] < 0.1 and r["n_flips_raw"] == 1
    assert r["p_min"] > 0.5 and r["n_flips"] == 0
    assert "favourite wins with a raw min < 0.10 that the cleaning removed: 1" in mp.report(t, load_config())


def test_team_events_and_best_of_default():
    m, q, s, d = frames()
    m["tournament"] = ""
    m.loc[m["match_id"] == "M2", "tournament"] = "Billie Jean King Cup Finals"
    d = d[d["match_id"] != "M5"]                     # M5 (WTA) has no milestone best_of
    t, _ = mp.path_table(m, q, s, d)
    t = t.set_index("match_id")
    assert t.loc["M2", "tour"] == "WTA team"
    assert t.loc["M5", "best_of"] == 3 and t.loc["M3", "best_of"] == 3   # WTA / ATP-Ch default
