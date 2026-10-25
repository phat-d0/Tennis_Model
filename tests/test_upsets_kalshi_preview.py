"""Kalshi upset preview: closing quote, underdog pick, fees, fair-price settlement, round groups."""

import pandas as pd
import pytest

from swinglock.config import kalshi_fees, load_config
from swinglock.locks import buy_cost
from upsets import kalshi_preview as kp

T0 = pd.Timestamp("2026-06-01 12:00", tz="UTC")


def frames():
    matches = pd.DataFrame({
        "match_id": ["M1", "M2", "M3", "M4"],
        "tier": ["atp", "wta", "atp", "atp"],
        "scheduled_start": [T0, T0, T0, T0 + pd.Timedelta(days=1)],
        "settle_a": [1.0, 0.0, 0.42, 1.0], "settle_b": [0.0, 1.0, 0.58, 0.0],
        "fee_type": ["quadratic"] * 4, "fee_multiplier": [1.0] * 4,
    })
    q = []
    def add(mid, side, ask, minutes_before):
        q.append({"ts": T0 - pd.Timedelta(minutes=minutes_before), "match_id": mid, "side": side, "ask": ask})
    add("M1", "A", 0.50, 300); add("M1", "A", 0.21, 10); add("M1", "B", 0.82, 10)   # dog A wins
    add("M1", "A", 0.05, -5)                                                       # after start: ignored
    add("M2", "A", 0.70, 30); add("M2", "B", 0.33, 30)                             # dog B wins
    add("M3", "A", 0.40, 20); add("M3", "B", 0.62, 20)                             # not started, fair price
    add("M4", "A", 0.30, 30); add("M4", "B", 0.72, 30)                             # quote 1 day + 30 min before: too old
    details = pd.DataFrame({"match_id": ["M1", "M2", "M3"],
                            "round": ["Round of 64", "Round 2", "Qualification Round 1"],
                            "best_of": ["3"] * 3, "tournament_name": ["T", "U", "T"], "gender": ["men"] * 3})
    return matches, pd.DataFrame(q), details


def test_closing_quote_dog_and_settlement():
    m, q, d = frames()
    b = kp.build_bets(m, q, d, load_config(), contracts=100, max_age_h=3).set_index("match_id")
    assert list(b.index) == ["M1", "M2", "M3"]             # M4's quotes are too old
    assert b.loc["M1", "dog_ask"] == pytest.approx(0.21)   # last pre-start quote, not the 5¢ one after start
    assert b.loc["M2", "dog_ask"] == pytest.approx(0.33) and b.loc["M2", "upset"] == 1
    fees = kalshi_fees(load_config(), "quadratic", 1.0)
    cost = buy_cost(0.21, 100, fees)
    assert b.loc["M1", "cost_0c"] == pytest.approx(cost)
    assert b.loc["M1", "pnl_0c"] == pytest.approx(100 - cost)
    assert b.loc["M1", "pnl_1c"] == pytest.approx(100 - buy_cost(0.21, 100, fees, 0.01))
    # not started: dog A settles at its fair price, not 0 or 1
    assert b.loc["M3", "pnl_0c"] == pytest.approx(42 - buy_cost(0.40, 100, fees))
    assert b.loc["M3", "upset"] == 0


def test_round_groups():
    df = pd.DataFrame({
        "round": ["Round of 128", "Round of 64", "Round of 32", "Final", "Round 1", "Round 3",
                  "Qualification Round 2", None, "Round of 32", "Round of 16"],
        "tournament_name": ["Slam"] * 4 + ["X", "X", "X", "X", "Small", "Small"],
        "scheduled_start": [T0] * 10,
    })
    assert kp.round_group(df).tolist() == ["early", "early", "later", "later", "early", "later",
                                           "qualifying", "unknown", "early", "early"]


def test_report_renders():
    m, q, d = frames()
    b = kp.build_bets(m, q, d, load_config())
    text = kp.report(b, 0.75, len(m))
    assert "Headline" in text and "Round of 64" in text


def test_milestone_details_from_fixture():
    import json
    from pathlib import Path
    ms = json.loads(Path("tests/fixtures/kalshi/milestones_atp_faria_brunold_2026-10-24.json").read_text())["milestones"]

    class Client:
        def milestones(self, max_age_s=None, **filt):
            assert filt["type"] == "tennis_tournament_singles"
            return iter(ms)

    d = kp.milestone_details(Client(), "2026-04-01T00:00:00Z").set_index("match_id")
    row = d.loc["KXATPMATCH-26OCT24FARBRU"]
    assert row["round"] == "Qualification Round 1" and row["tournament_name"] == "ATP Basel"
