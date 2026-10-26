"""Penultimate-set theory: score parsing, set-probability inversion, decider framing (results),
and the Kalshi decider-price test. Synthetic frames only."""

import numpy as np
import pandas as pd
import pytest

from swinglock.config import kalshi_fees, load_config
from swinglock.locks import buy_cost
from upsets import decider, elo, penultimate as pen, sackmann

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


# --- Kalshi decider test -----------------------------------------------------------------------

T0 = pd.Timestamp("2026-06-01 12:00", tz="UTC")


def sets_frame(rows):
    """rows: (match_id, [winner sides], minutes after T0 each set ended)."""
    out = []
    for mid, sides, ends in rows:
        for k, (s, e) in enumerate(zip(sides, ends), 1):
            out.append({"match_id": mid, "set_no": k, "close_time": T0 + pd.Timedelta(minutes=e), "winner_side": s})
    return pd.DataFrame(out)


def test_deciders():
    s = sets_frame([("M1", ["A", "B", "B"], [40, 80, 120]),       # bo3 decider: pen = B (set 2)
                    ("M2", ["A", "A"], [40, 80]),                  # straight sets
                    ("M3", ["B", "A", "A", "B"], [40, 80, 120, 160]),  # bo5, 2-2: pen = B (set 4); set 5 ongoing
                    ("M4", ["A", "B"], [40, 80])])                 # 1-1, decider not recorded yet
    d = decider.deciders(s, pd.Series({"M1": 3, "M2": 3, "M3": 5, "M4": 3})).set_index("match_id")
    assert sorted(d.index) == ["M1", "M3", "M4"]
    assert d.loc["M1", "pen_side"] == "B" and d.loc["M1", "decider_start"] == T0 + pd.Timedelta(minutes=80)
    assert d.loc["M3", "pen_side"] == "B" and d.loc["M3", "best_of"] == 5
    inferred = decider.deciders(s).set_index("match_id")       # best_of unknown: inferred
    assert sorted(inferred.index) == ["M1", "M3", "M4"]


def kalshi_frames():
    matches = pd.DataFrame({
        "match_id": ["M1", "M2", "M3"], "series": ["KXATPMATCH", "KXWTAMATCH", "KXATPMATCH"],
        "tier": ["atp", "wta", "atp"], "scheduled_start": [T0] * 3,
        "settle_a": [0.0, 1.0, 1.0], "settle_b": [1.0, 0.0, 0.0],
        "fee_type": ["quadratic"] * 3, "fee_multiplier": [1.0] * 3})
    q = []

    def add(mid, side, ask, minutes):
        q.append({"ts": T0 + pd.Timedelta(minutes=minutes), "match_id": mid, "side": side, "ask": ask})
    # pre-match: A favourite in M1 and M2
    for mid in ("M1", "M2", "M3"):
        add(mid, "A", 0.70, -10)
        add(mid, "B", 0.33, -10)
    # M1: set 2 (won by B) ends at +80 min; quotes around the break
    add("M1", "A", 0.60, 79)
    add("M1", "B", 0.44, 79)
    add("M1", "B", 0.47, 81)          # at +90 s the last B quote is 0.47
    add("M1", "B", 0.10, 85)          # 5 min later: never used
    # M2: set 2 won by A ends +80; only stale quotes (> 5 min before the decider)
    add("M2", "A", 0.55, 70)
    add("M2", "B", 0.50, 70)
    sets = sets_frame([("M1", ["A", "B", "B"], [40, 80, 120]), ("M2", ["B", "A", "A"], [40, 80, 120]),
                       ("M3", ["A", "A"], [40, 80])])
    details = pd.DataFrame({"match_id": ["M1", "M2", "M3"], "round": ["Round 1"] * 3, "best_of": ["3"] * 3,
                            "tournament_name": ["T"] * 3, "gender": ["men"] * 3})
    return matches, pd.DataFrame(q), sets, details


def test_build_price_fee_and_roles():
    m, q, s, d = kalshi_frames()
    b = decider.build(m, q, s, d, load_config(), offset_s=90, max_age_s=300).set_index("match_id")
    assert list(b.index) == ["M1"]                       # M2 only stale quotes; M3 no decider
    r = b.loc["M1"]
    assert r["pen_side"] == "B" and r["pen_ask"] == pytest.approx(0.47) and r["oth_ask"] == pytest.approx(0.60)
    assert r["pen_prematch"] == "underdog" and r["pen_won"] == 1 and r["tour"] == "ATP"
    fees = kalshi_fees(load_config(), "quadratic", 1.0)
    assert r["cost_pen_0c"] == pytest.approx(buy_cost(0.47, 100, fees))
    assert r["pnl_pen_0c"] == pytest.approx(100 - buy_cost(0.47, 100, fees))
    assert r["pnl_oth_0c"] == pytest.approx(-buy_cost(0.60, 100, fees))
    at0 = decider.build(m, q, s, d, load_config(), offset_s=0).set_index("match_id")
    assert at0.loc["M1", "pen_ask"] == pytest.approx(0.44)   # +0 s: the quote before the break


def test_run_report():
    m, q, s, d = kalshi_frames()
    text, by = decider.run(m, q, s, d, load_config())
    assert set(by) == {0, 60, 90, 180}
    assert "Timing sensitivity" in text and "| All | 1 |" in text
