"""Pre-match Elo ranks for Kalshi matches (upsets/elo_ranks.py), synthetic frames only."""

import numpy as np
import pandas as pd

from upsets import elo_ranks as er
from upsets import sackmann

COLS = ["tourney_id", "tourney_name", "surface", "draw_size", "tourney_level", "tourney_date",
        "match_num", "winner_id", "winner_seed", "winner_entry", "winner_name", "loser_id",
        "loser_seed", "loser_entry", "loser_name", "score", "best_of", "round",
        "winner_rank", "winner_rank_points", "loser_rank", "loser_rank_points"]
NAMES = {"p": "Pedro Perez", "q": "Quinn Quill", "x1": "Xavier One", "x2": "Xavier Two", "x3": "Xavier Three"}


def day(num):
    return int((pd.Timestamp("2025-01-06") + pd.Timedelta(days=14 * num)).strftime("%Y%m%d"))


def sack():
    rows, num = [], 0
    # 2025: p beats everyone twice, q beats the x's once each: p > q > x's
    for rep in range(2):
        for opp in ["q", "x1", "x2", "x3"]:
            num += 1
            rows.append(dict(zip(COLS, [f"t{num}", "T", "Hard", 32, "A", day(num), num, "p", None, None,
                                        NAMES["p"], opp, None, None, NAMES[opp], "6-3 6-3", 3, "R32", 1, 1, 2, 2])))
    for opp in ["x1", "x2", "x3"]:
        num += 1
        rows.append(dict(zip(COLS, [f"t{num}", "T", "Hard", 32, "A", day(num), num, "q", None, None,
                                    NAMES["q"], opp, None, None, NAMES[opp], "6-3 6-3", 3, "R32", 1, 1, 2, 2])))
    return sackmann.normalize(pd.DataFrame(rows, columns=COLS), "atp").sort_values(
        ["date", "round_idx"], kind="stable").reset_index(drop=True)


def kmatches(rows, series="KXATPMATCH"):
    return pd.DataFrame([{"match_id": mid, "series": series, "tier": "atp",
                          "scheduled_start": pd.Timestamp(start, tz="UTC"), "player_a": a, "player_b": b,
                          "settle_a": sa, "settle_b": 1 - sa} for mid, start, a, b, sa in rows])


def test_ranks_order_unmatched_and_challenger():
    km = kmatches([("k1", "2025-12-01 10:00", "Xavier One", "Pedro Perez", 0.0),
                   ("k2", "2025-12-02 10:00", "Quinn Quill", "Nobody Atall", 1.0)])
    km = pd.concat([km, kmatches([("k3", "2025-12-03 10:00", "Xavier Two", "Quinn Quill", 0.0)],
                                 series="KXATPCHALLENGERMATCH")], ignore_index=True)
    r = er.ranks(km, sack(), min_n=1).set_index("match_id")
    assert r.loc["k1", "rank_b"] == 1 and r.loc["k1", "rank_a"] > 2          # p is #1, x1 below p and q
    assert r.loc["k2", "rank_a"] == 2                                       # q is #2
    assert pd.isna(r.loc["k2", "rank_b"]) and not r.loc["k2", "matched_b"]  # unmatched name: blank
    assert r.loc["k3", "series"] == "KXATPCHALLENGERMATCH" and r.loc["k3", "rank_b"] == 2
    # k2's unmatched player is a real player rated from Kalshi results: in the pool from the next day, but
    # never given a rank himself
    assert list(r["pool"]) == [5, 5, 6]


def test_min_n_and_inactive_players_are_blank_or_excluded():
    km = kmatches([("k1", "2025-12-01 10:00", "Xavier One", "Pedro Perez", 0.0)])
    r = er.ranks(km, sack(), min_n=5).set_index("match_id")
    assert pd.isna(r.loc["k1", "rank_a"]) and r.loc["k1", "rank_b"] == 1    # x1 has 3 matches < 5
    late = kmatches([("k9", "2027-06-01 10:00", "Xavier One", "Pedro Perez", 0.0)])
    r = er.ranks(late, sack(), min_n=1, active_days=365).set_index("match_id")
    assert pd.isna(r.loc["k9", "rank_a"]) and r.loc["k9", "pool"] == 0      # nobody active: no rank


def test_same_day_results_are_not_in_the_pool_and_never_rank_a_player_below_himself():
    # q beats p in the morning; in the evening p's pre-match Elo has dropped, but the pool is the day-start one
    km = kmatches([("am", "2025-12-01 09:00", "Quinn Quill", "Pedro Perez", 1.0),
                   ("pm", "2025-12-01 18:00", "Pedro Perez", "Xavier One", 1.0)])
    r = er.ranks(km, sack(), min_n=1).set_index("match_id")
    assert r.loc["am", "rank_b"] == 1
    # p's own (higher) day-start entry is not counted against him; q's day-start rating is still below
    # p's new rating or above it, but never p himself
    assert r.loc["pm", "rank_a"] in (1.0, 2.0)
    elo_drop = r.loc["pm", "elo_a"] < r.loc["am", "elo_b"]
    assert elo_drop


def test_no_lookahead_later_results_never_change_earlier_ranks():
    base = [("k1", "2025-12-01 10:00", "Xavier One", "Quinn Quill", 0.0)]
    later = base + [("k2", "2025-12-05 10:00", "Xavier One", "Pedro Perez", 1.0),
                    ("k3", "2025-12-06 10:00", "Xavier One", "Quinn Quill", 1.0)]
    a = er.ranks(kmatches(base), sack(), min_n=1).set_index("match_id")
    b = er.ranks(kmatches(later), sack(), min_n=1).set_index("match_id")
    assert a.loc["k1", ["rank_a", "rank_b", "elo_a", "elo_b"]].tolist() == \
        b.loc["k1", ["rank_a", "rank_b", "elo_a", "elo_b"]].tolist()


def test_flipping_a_later_result_never_changes_an_earlier_rank():
    """Data's check: a rank uses only matches that finished before its match started. Flip later results
    (the same evening, and the next day) and the earlier match's ranks stay put; a match that started
    late the evening before (it may still be running) isn't in the pool either."""
    def run(later_a_wins, eve_a_wins):
        rows = [("eve", "2025-11-30 23:30", "Xavier Two", "Quinn Quill", eve_a_wins),     # started 30 min before midnight
                ("k1", "2025-12-01 10:00", "Xavier One", "Quinn Quill", 0.0),
                ("pm", "2025-12-01 18:00", "Xavier Three", "Pedro Perez", later_a_wins),
                ("next", "2025-12-02 10:00", "Xavier Two", "Pedro Perez", later_a_wins)]
        return er.ranks(kmatches(rows), sack(), min_n=1).set_index("match_id").loc["k1"]
    base = run(0.0, 0.0)
    for later, eve in ((1.0, 0.0), (0.0, 1.0), (1.0, 1.0)):
        other = run(later, eve)
        assert (other["rank_a"], other["rank_b"]) == (base["rank_a"], base["rank_b"])
    # but q's own result the evening before does move q's own (exact) Elo
    assert run(0.0, 1.0)["elo_b"] < base["elo_b"]


def test_ranks_are_integers_and_follow_matches_parquet_order():
    km = kmatches([("k1", "2025-12-01 10:00", "Pedro Perez", "Xavier One", 1.0)])
    r = er.ranks(km, sack(), min_n=1)
    assert str(r["rank_a"].dtype) == "Int64" and r.loc[0, "rank_a"] == 1 and r.loc[0, "rank_b"] > 1
