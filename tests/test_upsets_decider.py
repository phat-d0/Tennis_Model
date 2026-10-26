"""Kalshi decider-price test (penultimate-set winner at the decider start). Synthetic frames only."""

import pandas as pd
import pytest

from swinglock.config import kalshi_fees, load_config
from swinglock.locks import buy_cost
from upsets import decider

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
        "close_time": [T0 + pd.Timedelta(minutes=150)] * 3,
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
    sets = sets_frame([("M1", ["A", "B", "B"], [40, 80, 120]), ("M2", ["B", "A", "A"], [41, 82, 121]),
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


def test_guard_flags_short_long_and_shared_deciders():
    dec = pd.DataFrame({"match_id": ["M1", "M2", "M3", "M4", "M5"],
                        "decider_start": [T0, T0, T0 + pd.Timedelta(minutes=1), T0 + pd.Timedelta(minutes=2),
                                          T0 + pd.Timedelta(minutes=3)]})
    end = pd.Series({"M1": T0 + pd.Timedelta(minutes=60), "M2": T0 + pd.Timedelta(minutes=60),
                     "M3": T0 + pd.Timedelta(minutes=10), "M4": T0 + pd.Timedelta(minutes=300),
                     "M5": T0 + pd.Timedelta(minutes=50)})
    g = decider.guard(dec, end).set_index("match_id")
    assert list(g["shared"]) == [True, True, False, False, False]
    assert g.loc["M3", "too_short"] and g.loc["M4", "too_long"]
    assert list(g["ok"]) == [False, False, False, False, True]


def test_decider_with_bad_close_time_is_excluded():
    m, q, s, d = kalshi_frames()
    m["close_time"] = T0 + pd.Timedelta(minutes=85)   # decider would last 5 min: impossible
    b = decider.build(m, q, s, d, load_config())
    assert len(b) == 0
