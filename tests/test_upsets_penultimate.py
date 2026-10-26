"""Penultimate-set theory (results only): score parsing, set-probability inversion, decider
framing, favourite paths. Synthetic frames only."""

import numpy as np
import pandas as pd
import pytest

from upsets import elo, penultimate as pen, sackmann

COLS = ["tourney_id", "tourney_name", "surface", "draw_size", "tourney_level", "tourney_date",
        "match_num", "winner_id", "winner_seed", "winner_entry", "winner_name", "loser_id",
        "loser_seed", "loser_entry", "loser_name", "score", "best_of", "round",
        "winner_rank", "winner_rank_points", "loser_rank", "loser_rank_points"]


def test_parse_sets():
    assert pen.parse_sets("6-3 6-4") == [1, 1]
    assert pen.parse_sets("4-6 7-6(5) 6-2") == [0, 1, 1]
    assert pen.parse_sets("6-4 3-6 [10-7]") == [1, 0, 1]
    assert pen.parse_sets("6-4 Played and abandoned") is None
    assert pen.parse_sets("6-3?") is None and pen.parse_sets("") is None


@pytest.mark.parametrize("bo", [3, 5])
def test_set_prob_inverts_match_prob(bo):
    s = np.array([0.3, 0.5, 0.62, 0.8])
    m = s ** 2 * (3 - 2 * s) if bo == 3 else s ** 3 * (10 - 15 * s + 6 * s ** 2)
    assert np.allclose(pen.set_prob(m, np.full(4, bo)), s, atol=1e-6)


def frame(rows):
    raw = pd.DataFrame([dict(zip(COLS, [f"t{i}", "T", "Hard", 32, "A", 20200106 + i, i, w, None, None, w,
                                        l, None, None, l, sc, bo, "R32", wr, 1, lr, 1]))
                        for i, (w, l, sc, bo, wr, lr) in enumerate(rows)])
    df = sackmann.normalize(raw, "atp")
    return elo.add_elo(df, keys=("winner_id", "loser_id"))


def test_penultimate_frame():
    f = pen.penultimate_frame(frame([
        ("a", "b", "6-3 6-4", 3, 1, 50),           # straight sets: pen winner = match winner
        ("a", "c", "4-6 6-3 6-2", 3, 1, 60),       # fav a levelled (won set 2) and won
        ("d", "a", "6-4 3-6 6-3", 3, 70, 1),       # d won set 1, a levelled, d won: pen winner lost
        ("a", "e", "6-4 3-6 6-3 6-7(4) 6-2", 5, 1, 80),  # 2-2 after a lost set 4: pen winner e lost
        ("a", "f", "6-4 3-6 6-3 6-2", 5, 1, 90),   # 4 sets, no decider; a won set 3 (penultimate)
        ("a", "g", "6-4 2-1 RET", 3, 1, 90),       # retirement: excluded
        ("a", "h", "6-4 Played and abandoned", 3, 1, 90),
    ]))
    assert len(f) == 5
    assert list(f["decider"]) == [False, True, True, True, False]
    assert list(f["pen_won_match"]) == [1, 1, 0, 0, 1]
    assert list(f["pen_is_fav_rank"]) == [1.0, 1.0, 1.0, 0.0, 1.0]
    assert f["p_set_pen"].between(0, 1).all()


def test_symmetric_momentum():
    rows = []
    # fav levelled: wins 70 of 100; dog levelled: fav wins 50 of 100 -> momentum +10 pp
    for i in range(100):
        rows.append({"fmt": "ATP bo3", "pen_is_fav_elo": 1.0, "pen_won_match": int(i < 70)})
        rows.append({"fmt": "ATP bo3", "pen_is_fav_elo": 0.0, "pen_won_match": int(i < 50)})
    s = pen.symmetric(pd.DataFrame(rows)).iloc[0]
    assert s["fav wins (fav levelled)"] == pytest.approx(0.7)
    assert s["fav wins (dog levelled)"] == pytest.approx(0.5)
    assert s["momentum"] == pytest.approx(0.10)


def test_fav_paths_orient_to_favourite():
    f = pen.penultimate_frame(frame([
        ("a", "b", "4-6 6-3 6-2", 3, 1, 50),       # favourite a (rank 1) came back: LWW
        ("c", "d", "6-4 3-6 6-3", 3, 70, 2),       # favourite d lost: their view LWL
    ]))
    fp = pen.fav_paths(f, "rank")
    assert list(fp["path"]) == ["LWW", "LWL"] and list(fp["fav_won"]) == [1, 0]
    assert list(fp["won_set1"]) == [0, 0]
