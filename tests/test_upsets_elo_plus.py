"""Elo upgrades (upsets/elo_plus.py) on synthetic Sackmann-shaped rows."""

import numpy as np
import pandas as pd

from upsets import elo, elo_plus as ep


def frame():
    rows = [("2024-01-01", "a", "b", "6-1 6-1", "E1", "R32", 1.0), ("2024-01-01", "a", "c", "7-6 7-6", "E1", "R16", 2.0),
            ("2024-01-08", "b", "c", "6-3 3-6 6-2", "E2", "R32", 1.0), ("2024-06-01", "a", "b", "W/O", "E3", "R32", 1.0),
            ("2025-06-01", "c", "a", "6-4 6-4", "E4", "R32", 1.0)]
    df = pd.DataFrame(rows, columns=["date", "winner_id", "loser_id", "score", "tourney_id", "round", "round_idx"])
    df["date"] = pd.to_datetime(df["date"])
    df["tour"], df["surface"] = "atp", "Hard"
    df["tournament"] = df["tourney_id"]
    df["comment"] = np.where(df["score"] == "W/O", "Walkover", "Completed")
    gs = np.array([ep.games_sets(s) for s in df["score"]])
    df["_share"] = (gs[:, 0] - gs[:, 1]) / np.maximum(gs[:, 0] + gs[:, 1], 1)
    df["_sets"] = gs[:, 2] + gs[:, 3]
    return df


def test_games_sets_and_match_prob():
    assert ep.games_sets("6-3 4-6 7-6(5)") == (17, 15, 2, 1)
    assert ep.games_sets("W/O") == (0, 0, 0, 0)
    p = ep.match_prob(np.array([0.65, 0.6, 0.6]), np.array([0.6, 0.6, 0.65]), np.array([3, 5, 3]))
    assert p[0] > 0.7 and abs(p[1] - 0.5) < 1e-9 and abs(p[0] + p[2] - 1) < 1e-6


def test_run_defaults_match_upsets_elo():
    df = frame()
    keep = np.ones(len(df), bool)
    r = ep.run(df, keep)
    ref = elo.add_elo(df, keys=("winner_id", "loser_id"))
    assert np.allclose(r["e_w"], ref["w_elo"]) and np.allclose(r["s_l"], ref["l_selo"])
    # margin of victory moves ratings further after a 6-1 6-1 than after 7-6 7-6
    m = ep.run(df, keep, mov=1.0)
    assert m["e_w"][1] > r["e_w"][1]          # a's rating after the 6-1 6-1 win is higher with MOV
    # decay pulls a towards 1500 after the year off before the last match
    d = ep.run(df, keep, decay=1.0)
    assert abs(d["e_l"][4] - 1500) < abs(r["e_l"][4] - 1500)


def test_fatigue_counts_recent_sets():
    df = frame()
    fw, fl = ep.fatigue(df, np.array([1, 2]))
    assert list(fw) == [2, 2]   # row 1: a's R32 (2 sets); row 2: b played 2 sets on 2024-01-01 (7 days earlier)
    assert list(fl) == [0, 2]   # row 1: c had no earlier match; row 2: c played 2 sets in E1


def test_fatigue_ignores_later_rounds():
    # a QF (or any later round) of the same event must never count as qualifying for its R16
    df = frame()
    qf = df.iloc[[1]].assign(winner_id="c", loser_id="a", round="QF", round_idx=3.0, _sets=3)
    df = pd.concat([df, qf], ignore_index=True)
    fw, fl = ep.fatigue(df, np.array([1]))
    assert list(fw) == [2] and list(fl) == [0]
