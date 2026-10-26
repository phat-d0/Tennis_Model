"""Line-shopping drawdown breakdown (upsets/line_shop_drawdown.py) on synthetic bets."""

import numpy as np
import pandas as pd
import pytest

from upsets import line_shop_drawdown as dd


def bets():
    d = pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01", "2025-04-01"])
    return pd.DataFrame({"date": d, "odds": [3.0, 3.0, 3.0, 3.0], "p_fair": [0.4] * 4, "win": [1, 1, 0, 0],
                         "pnl": [2.0, 2.0, -1.0, -1.0], "ev": [0.2] * 4, "void": False})


def test_peak_phase_and_summary():
    b = bets()
    peak = dd.peak_date(b)
    assert peak == pd.Timestamp("2025-02-01")
    ph = dd.phase(b, peak)
    assert list(ph) == ["run-up", "run-up", "drawdown", "drawdown"]
    s = dd.summarize(b)
    assert s["n"] == 4 and s["real"] == 2.0 and s["exp"] == pytest.approx(0.8)
    sd = np.sqrt(4 * 9 * 0.4 * 0.6)
    assert s["z"] == pytest.approx((2.0 - 0.8) / sd)
    assert dd.summarize(b.assign(void=True)) == {"n": 0}


def test_portfolio_bets_gap_and_power_ev():
    f = pd.DataFrame({"date": pd.to_datetime(["2025-01-01", "2025-01-02"]), "void": False, "upset": [1, 0],
                      "odds_dog_dk": [12.0, 3.2], "odds_fav_dk": [1.03, 1.3], "odds_dog_pin": [11.0, 3.0],
                      "odds_fav_pin": [1.06, 1.42], "p_model": np.nan, "tour": "atp", "level_group": "slam"})
    b = dd.portfolio_bets(f)
    assert len(b) == 2 and (b["side"] == "dog").all()
    i_d, i_f = 1 / 11.0, 1 / 1.06
    k_d, k_f = 1 / 12.0, 1 / 1.03
    assert b.loc[0, "gap"] == pytest.approx(abs(k_d / (k_d + k_f) - i_d / (i_d + i_f)))
    # the power de-vig gives the long shot less chance than the proportional one
    assert (b["p_pow"] < b["p_fair"]).all() and (b["ev_pow"] < b["ev"]).all()
