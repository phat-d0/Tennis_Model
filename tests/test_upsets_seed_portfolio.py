"""Seed losing early (upsets/seed_portfolio.py) on synthetic priced rows."""

import numpy as np
import pandas as pd
import pytest

from upsets import seed_portfolio as sp
from upsets.odds import devig_power


def data():
    # rows: 0 seed lost to a qualifier (unseeded won); 1 seed won vs a direct entrant; 2 both seeded (out);
    # 3 round 3 (out); 4 walkover (out); 5 neither seeded (out); 6 unseeded DK favourite won vs seed 30
    sack = pd.DataFrame({
        "date": pd.to_datetime(["2023-05-01", "2024-06-01", "2024-06-02", "2024-06-03", "2025-01-01", "2025-01-02",
                                "2026-03-01"]),
        "season": [2023, 2024, 2024, 2024, 2025, 2025, 2026], "tour": "atp",
        "level_group": ["slam", "1000", "1000", "1000", "other", "other", "slam"],
        "round_idx": [1, 2, 1, 3, 1, 1, 1], "void": [False, False, False, False, True, False, False],
        "w_seed": [np.nan, 3, 1, np.nan, np.nan, np.nan, np.nan],
        "l_seed": [2, np.nan, 5, 7, 9, np.nan, 30],
        "w_entry": ["Q", None, None, None, None, None, None], "l_entry": [None, None, None, None, None, None, None]})
    priced = pd.DataFrame({
        "sack_row": range(7),
        "odds_w_draftkings": [4.0, 1.3, 1.5, 3.0, 2.0, 2.0, 1.6], "odds_l_draftkings": [1.25, 3.6, 2.6, 1.4, 1.8, 1.8, 2.4],
        "odds_w_pinnacle": [4.2, 1.32, 1.55, 3.1, 2.0, 2.0, 1.62], "odds_l_pinnacle": [1.27, 3.7, 2.6, 1.42, 1.9, 1.9, 2.5]})
    return priced, sack


def test_bets_rule_and_values():
    b = sp.bets(*data())
    assert list(b["sack_row"]) == [0, 1, 6]                       # exactly one seed, R1/R2, not void
    r0, r1, r6 = (b[b["sack_row"] == i].iloc[0] for i in (0, 1, 6))
    # row 0: the unseeded qualifier won at 4.0
    assert r0["win"] == 1 and r0["odds"] == 4.0 and r0["pnl"] == 3.0 and r0["qual"] and r0["dk_dog"]
    assert r0["seed"] == 2 and r0["band"] == "1–4"
    assert r0["p_fair"] == pytest.approx(devig_power(np.array([4.2]), np.array([1.27]))[0])
    # row 1: the seed (winner) beat the unseeded loser, bet at the loser's 3.6
    assert r1["win"] == 0 and r1["odds"] == 3.6 and r1["pnl"] == -1.0 and not r1["qual"] and r1["seed"] == 3
    # row 6: unseeded DK favourite won vs seed 30
    assert not r6["dk_dog"] and r6["band"] == "17–32" and r6["pnl"] == pytest.approx(0.6)
    assert r6["pnl_cut"] == pytest.approx(1.6 * 0.97 - 1)
    assert (b["ev"] == b["odds"] * b["p_fair"] - 1).all()


def test_subrules_and_gate():
    b = sp.bets(*data())
    assert list(sp.subrule(b, "b")["sack_row"]) == [0] and list(sp.subrule(b, "c")["sack_row"]) == [1, 6]
    g = sp.gate(b, min_bets=3)
    assert g["bets"] == 3 and g["pnl"] == pytest.approx(3.0 - 1.0 + 0.6)
    assert g["seasons_positive"] == 2 and not g["pass"]            # 2023 +3, 2024 −1, 2026 +0.6: 2 of 4
    assert not sp.gate(b)["pass"]                                    # under 30 bets


def test_report_has_all_sections():
    text = sp.report(sp.bets(*data()))
    for s in ("### Gate", "(a) All", "(b) Qualifiers", "### Seed band", "DK favourite", "### Season"):
        assert s in text
