import numpy as np
import pandas as pd
import pytest

from upsets import dk_inplay_study as st


def _x(rows):
    """Live rows: (sack_row, minute, p_dog, odds_dog, odds_fav)."""
    t0 = pd.Timestamp("2025-01-01 12:00", tz="UTC")
    return pd.DataFrame([{"sack_row": r, "ts": t0 + pd.Timedelta(minutes=mn), "p_dog": p, "odds_dog": od,
                          "odds_fav": of} for r, mn, p, od, of in rows])


def _entries():
    return pd.DataFrame({"sack_row": [1, 2, 3], "season": 2025, "odds_bet": [6.0, 6.0, 6.0], "p_close": 0.15,
                         "won": [False, True, False], "void": [False, False, True], "side": "dog"})


def test_hedge_locks_equal_payout_at_the_first_crossing_and_holds_otherwise():
    x = _x([(1, 10, 0.40, 2.4, 1.6), (1, 20, 0.55, 1.8, 2.1), (1, 30, 0.70, 1.4, 3.0),
            (2, 10, 0.30, 3.2, 1.35), (3, 10, 0.60, 1.6, 2.4)])
    b = st.hedge_rule(_entries(), x, 0.50, 0.0).set_index("sack_row")
    assert b.loc[1, "hedged"] and b.loc[1, "pnl"] == pytest.approx(6.0 - 1 - 6.0 / 2.1)   # first p >= 50%: 20 min
    assert not b.loc[2, "hedged"] and b.loc[2, "pnl"] == 5.0                              # never reached: held, won
    assert b.loc[3, "pnl"] == 0.0                                                         # void: refunded
    cut = st.hedge_rule(_entries(), x, 0.50, 0.03).set_index("sack_row")
    assert cut.loc[1, "pnl"] == pytest.approx(6.0 - 1 - 6.0 / (1 + 1.1 * 0.97))


def test_decisions_never_use_later_snapshots():
    x = _x([(1, 10, 0.40, 2.4, 1.6), (1, 20, 0.55, 1.8, 2.1), (1, 30, 0.70, 1.4, 3.0), (2, 10, 0.30, 3.2, 1.35)])
    later = x.copy()
    after = (later["sack_row"] == 1) & (later["ts"] > later["ts"].min() + pd.Timedelta(minutes=10))
    after &= later["ts"] > later.loc[later["p_dog"] >= 0.5, "ts"].min()   # rows after match 1's trigger only
    later.loc[after, ["p_dog", "odds_fav"]] = [0.05, 77.0]
    assert after.sum() == 1
    a, b = st.hedge_rule(_entries(), x, 0.50, 0.03), st.hedge_rule(_entries(), later, 0.50, 0.03)
    assert a["pnl"].tolist() == b["pnl"].tolist()                          # match 1 decided at 20 min either way
    fav = pd.DataFrame({"sack_row": [1], "season": 2025, "odds_bet": [1.3], "p_close": 0.75, "won": [True],
                        "void": [False], "side": "fav"})
    d1 = st.dip_rule(fav, x.assign(p_dog=[0.40, 0.55, 0.70, 0.30]), 0.50, 0.0)
    d2 = st.dip_rule(fav, x.assign(p_dog=[0.40, 0.55, 0.10, 0.30]), 0.50, 0.0)
    assert d1["odds_bet"].tolist() == d2["odds_bet"].tolist() == [2.1]      # favourite first <= 50% at 20 min


def test_dip_bets_only_when_the_favourite_falls_to_50():
    fav = pd.DataFrame({"sack_row": [1, 2], "season": 2025, "odds_bet": [1.3, 1.2], "p_close": [0.75, 0.82],
                        "won": [True, False], "void": [False, False], "side": "fav"})
    x = _x([(1, 10, 0.45, 2.2, 1.7), (1, 20, 0.62, 1.6, 2.5), (2, 10, 0.30, 3.2, 1.35)])
    b = st.dip_rule(fav, x, 0.50, 0.0).set_index("sack_row")
    assert list(b.index) == [1] and b.loc[1, "odds_bet"] == 2.5 and b.loc[1, "pnl"] == 1.5


def test_mismatch_entries_back_the_worse_ranked_player():
    sack = pd.DataFrame({"w_rank": [20.0, 200.0, 50.0, 10.0], "l_rank": [200.0, 20.0, 60.0, np.nan]}, index=[0, 1, 2, 3])
    s = pd.DataFrame({"sack_row": [0, 1, 2, 3], "season": 2025, "upset": [0, 1, 0, 0], "void": False,
                      "odds_dog_dk": 4.0, "odds_fav_dk": 1.25, "p_dk": 0.22})
    e = st.mismatch_entries(s, sack).set_index("sack_row")
    assert list(e.index) == [0, 1]                         # 50 vs 60 is no mismatch; a missing rank is out
    assert not e.loc[0, "won"] and e.loc[0, "side"] == "dog" and e.loc[0, "odds_bet"] == 4.0
    assert e.loc[1, "won"] and e.loc[1, "side"] == "dog"


def test_gate_needs_the_main_sample_too():
    b = pd.DataFrame({"season": [2023] * 20 + [2024] * 20 + [2025] * 5 + [2026] * 5,
                      "pnl": [1.0] * 40 + [-1.0, 0.5, 0.5, 0.5, 0.5] * 2})
    g = st.gate(b)
    assert g["pos"] == 4 and g["pnl"] > 0 and not g["pass"]   # 10 bets in 2025-26 < 30


def test_validity_counts_decided_and_identical_prices_without_outcomes():
    ts = lambda mn: pd.Timestamp("2025-01-01 12:00", tz="UTC") + pd.Timedelta(minutes=mn)  # noqa: E731
    m = pd.DataFrame({"live_started": [True, True], "postponed": [False, False], "season": [2025, 2025]})
    q = pd.DataFrame({"match": [0, 0, 0, 1, 1], "ts": [ts(0), ts(10), ts(20), ts(0), ts(10)], "live_started": True,
                      "draftkings_home": [1.8, 1.5, 1.05, 2.0, 2.0], "draftkings_away": [2.0, 2.6, 12.0, 1.8, 1.8],
                      "pinnacle_home": [1.8, 1.8, 1.8, 2.0, 2.0], "pinnacle_away": [2.0, 2.0, 2.0, 1.8, 1.8]})
    text = st.validity(m, q)
    dk = [r for r in text.splitlines() if r.startswith("| DraftKings | Pooled")][0].split("|")
    assert dk[4].strip() == "0%" and dk[5].strip() == "50%"      # decided at first / last
    assert dk[7].strip() == "33%"                                # 1 of 3 consecutive pairs identical
    assert "FAIL" in text
    assert "| 0–10 | 2 | 50% | 0% |" in text                     # both last (a‴) rows are the last listed ones


def test_calibration_bins_and_log_loss():
    s = pd.DataFrame({"sack_row": [1, 2], "p_dk": [0.2, 0.2], "void": [False, False]})
    x = pd.DataFrame({"sack_row": [1, 1, 2, 2], "p_dog": [0.3, 0.95, 0.25, 0.05], "upset": [1, 1, 0, 0]})
    text = st.calibration(s, x)
    assert "| (0.2, 0.3] | 2 | 2 | 0.275 | 0.500 |" in text
    assert "close 0.9163" in text and "PASS" in text       # last rows 0.95 / 0.05 beat the close 0.2 / 0.2
