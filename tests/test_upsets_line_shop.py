"""Line-shopping rule (upsets/line_shop.py) on synthetic quotes; no real odds in git."""

import numpy as np
import pandas as pd

from upsets import line_shop as ls


def q_frame():
    # event e1: DK beats Pinnacle-fair on home at 10:00, not at 11:00; 11:55 is the close
    ts = pd.to_datetime(["2026-07-01 10:00", "2026-07-01 11:00", "2026-07-01 11:55"])
    return pd.DataFrame({
        "event_id": "e1", "snapshot_ts": ts,
        "odds_1_dk": [2.30, 2.00, 2.10], "odds_2_dk": [1.60, 1.80, 1.70],
        "odds_1_pin": [2.05, 2.05, 2.20], "odds_2_pin": [1.80, 1.80, 1.70],
        "last_update_dk": ts - pd.Timedelta(minutes=30), "last_update_pin": ts,
        "is_close": [False, False, True]})


def ev_frame(winner="home", void=False):
    return pd.DataFrame({"event_id": ["e1"], "key": ["k"], "tourney_id": ["p"], "commence":
                         [pd.Timestamp("2026-07-01 12:00")], "winner": [winner], "void": [void],
                         "season": [2026], "tour": ["atp"], "level_group": ["slam"]})


def test_first_qualifying_snapshot_and_clv():
    q = q_frame()
    long = ls.sides(q)
    pc = ls.pinnacle_close(q)
    b = ls.bets(long, ev_frame(), pc, 0.0)
    assert list(b["side"]) == ["home"] and b.loc[0, "snapshot_ts"] == pd.Timestamp("2026-07-01 10:00")
    assert np.isclose(b.loc[0, "pnl"], 1.3) and b.loc[0, "dk_minus_pin_min"] == -30
    p_close = ls.devig_power(np.array([2.20]), np.array([1.70]))[0]
    assert np.isclose(b.loc[0, "clv"], 2.30 * p_close - 1)
    # the close itself never yields a bet, even when it qualifies
    q2 = q.assign(odds_1_dk=[2.0, 2.0, 2.6])
    assert ls.bets(ls.sides(q2), ev_frame(), ls.pinnacle_close(q2), 0.0).empty
    # void: stake back
    assert ls.bets(long, ev_frame(None, True), pc, 0.0).loc[0, "pnl"] == 0.0


def test_walk_forward_uses_earlier_seasons_only():
    def mk(season, n, pnl):
        return pd.DataFrame({"event_id": [f"{season}-{i}" for i in range(n)], "season": season,
                             "void": False, "pnl": pnl})
    by_t = {0.0: pd.concat([mk(2024, 40, -1.0), mk(2025, 40, 1.0)]),
            0.02: pd.concat([mk(2024, 40, 0.5), mk(2025, 40, -1.0)])}
    oos, seasons = ls.walk_forward(by_t)
    assert seasons.loc[0, "threshold"] == 0.02 and seasons.loc[0, "pnl"] == -40.0   # chosen on 2024
    assert not ls.gate(oos, seasons)["pass"]
