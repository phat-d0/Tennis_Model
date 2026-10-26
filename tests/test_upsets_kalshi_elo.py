"""Elo vs Kalshi prices: name matching, timeline (no lookahead, carry-forward, no double count),
calibration fit window, walk-forward. Synthetic frames only."""

import numpy as np
import pandas as pd
import pytest

from swinglock.config import load_config
from upsets import kalshi_elo as ke
from upsets import sackmann

COLS = ["tourney_id", "tourney_name", "surface", "draw_size", "tourney_level", "tourney_date",
        "match_num", "winner_id", "winner_seed", "winner_entry", "winner_name", "loser_id",
        "loser_seed", "loser_entry", "loser_name", "score", "best_of", "round",
        "winner_rank", "winner_rank_points", "loser_rank", "loser_rank_points"]


def srow(tid, date, w, l, num=1, rnd="R32", ws=None, ls=None):
    return dict(zip(COLS, [tid, "T", "Hard", 32, "A", date, num, w, ws, None, NAMES[w], l, ls, None,
                           NAMES[l], "6-3 6-3", 3, rnd, 10, 1000, 50, 500]))


NAMES = {"p": "Pedro Pérez", "q": "Quinn Quill", "r": "Rafe Roe", "s": "Sam Sole",
         "x1": "Xavier One", "x2": "Xavier Two", "x3": "Xavier Three", "x4": "Xavier Four"}


def sack_frame(extra=()):
    rows = []
    # p beats four players twice in 2025: p's Elo ends well above 1500
    for i, opp in enumerate(["x1", "x2", "x3", "x4"] * 2):
        rows.append(srow(f"t{i}", 20250106 + 100 * (i // 4) + 7 * (i % 4), "p", opp, num=i))
    rows += list(extra)
    return sackmann.normalize(pd.DataFrame(rows, columns=COLS), "atp").sort_values(
        ["date", "round_idx"], kind="stable").reset_index(drop=True)


def kmatches(rows):
    """rows: (match_id, start, player_a, player_b, settle_a)."""
    return pd.DataFrame([{
        "match_id": mid, "series": "KXATPMATCH", "tier": "atp",
        "scheduled_start": pd.Timestamp(start, tz="UTC"), "player_a": a, "player_b": b,
        "settle_a": sa, "settle_b": 1 - sa, "fee_type": "quadratic", "fee_multiplier": 1.0}
        for mid, start, a, b, sa in rows])


# --- names -----------------------------------------------------------------------------------

def players(rows):
    return pd.DataFrame([{"tour": t, "id": i, "name": n, "key": ke.name_key(n),
                          "last": pd.Timestamp(last)} for t, i, n, last in rows])


def test_name_matching():
    p = players([("atp", "1", "Felix Auger Aliassime", "2026-05-01"),
                 ("wta", "2", "Qinwen Zheng", "2026-05-01"),
                 ("atp", "3", "Alex de Minaur", "2026-05-01"),
                 ("atp", "4", "Stefanos Tsitsipas", "2026-05-01"),
                 ("atp", "5", "Marco Rossi", "2026-05-01"), ("atp", "6", "Marco Rossi", "2026-04-01"),
                 ("atp", "7", "Old Timer", "2010-01-01"), ("atp", "8", "Old Timer", "2026-05-01"),
                 ("wta", "9", "Felix Auger Aliassime", "2026-05-01")])
    names = pd.Series(["Félix Auger-Aliassime", "Zheng Qinwen", "A. de Minaur", "Stefanos Tsitsipaz",
                       "Marco Rossi", "Old Timer", "Nobody Atall"])
    tours = pd.Series(["atp", "wta", "atp", "atp", "atp", "atp", "atp"])
    r = ke.match_names(names, tours, p, active_since=pd.Timestamp("2025-01-01"))
    assert list(r["id"].astype(object).where(r["id"].notna(), None)) == [
        "1", "2", "3", "4", None, "8", None]
    assert list(r["how"]) == ["exact", "order", "initial", "fuzzy", "ambiguous", "exact", "none"]


# --- timeline --------------------------------------------------------------------------------

def test_carry_forward_and_kalshi_updates():
    sack = sack_frame()
    pl = ke.player_table(sack)
    km = ke.kalshi_matches(kmatches([
        ("K1", "2026-06-10 12:00", "Pedro Perez", "Quinn Quill", 1.0),   # after Sackmann ends
        ("K2", "2026-06-11 12:00", "Quinn Quill", "Rafe Roe", 1.0),      # q unknown to Sackmann
        ("K3", "2026-06-12 12:00", "Quinn Quill", "Sam Sole", 0.0),
    ]), pl)
    _, km = ke.timeline(sack, km)
    k = km.set_index("match_id")
    assert k.loc["K1", "elo_a"] > 1550 and k.loc["K1", "elo_b"] == 1500     # carried forward
    assert k.loc["K2", "elo_a"] < 1500                                       # q lost K1
    assert k.loc["K3", "elo_a"] > k.loc["K2", "elo_a"]                       # q won K2
    assert k.loc["K3", "n_a"] == 2


def test_own_result_never_moves_own_rating():
    sack = sack_frame()
    pl = ke.player_table(sack)
    base = [("K1", "2026-06-10", "Pedro Perez", "Quinn Quill", 1.0),
            ("K2", "2026-06-11", "Pedro Perez", "Rafe Roe", 1.0)]
    flip = [base[0], ("K2", "2026-06-11", "Pedro Perez", "Rafe Roe", 0.0)]
    a = ke.timeline(sack, ke.kalshi_matches(kmatches(base), pl))[1].set_index("match_id")
    b = ke.timeline(sack, ke.kalshi_matches(kmatches(flip), pl))[1].set_index("match_id")
    assert a.loc["K2", "elo_a"] == b.loc["K2", "elo_a"]
    assert a.loc["K2", "elo_b"] == b.loc["K2", "elo_b"]


def test_join_takes_sackmann_row_seeds_and_counts_once():
    extra = [srow("rg", 20260525, "q", "p", num=1, rnd="R128", ws=None, ls=3)]
    sack = sack_frame(extra)
    sack.loc[sack["tourney_id"] == "rg", "draw_size"] = 128
    pl = ke.player_table(sack)
    km = ke.kalshi_matches(kmatches([
        ("K1", "2026-05-26 10:00", "Pedro Perez", "Quinn Quill", 0.0),   # = the Sackmann R1 row
        ("K2", "2026-06-20 10:00", "Pedro Perez", "Sam Sole", 1.0),
        ("K3", "2026-05-27 10:00", "Rafe Roe", "Sam Sole", 1.0),         # not in Sackmann, in its span
    ]), pl)
    _, km = ke.timeline(sack, km)
    k = km.set_index("match_id")
    assert k.loc["K1", "sack_row"] >= 0 and k.loc["K1", "seed_a"] == 3 and np.isnan(k.loc["K1", "seed_b"])
    assert k.loc["K1", "sack_a_won"] == 0.0 == k.loc["K1", "a_won"]
    assert k.loc["K2", "n_a"] == 9               # 8 + the joined loss, counted once
    assert k.loc["K2", "elo_b"] == 1500          # K3 is inside Sackmann's span: no update
    assert k.loc["K2", "elo_a"] < k.loc["K1", "elo_a"]


# --- calibration + walk-forward --------------------------------------------------------------

def test_fit_calibration_ignores_matches_after_window():
    rng = np.random.default_rng(1)
    n = 400
    d = pd.DataFrame({
        "level_group": "other", "round_idx": 1.0, "void": False, "season": 2020,
        "date": pd.date_range("2020-01-01", periods=n, freq="D"),
        "w_elo": 1500 + rng.normal(50, 100, n), "l_elo": 1500.0, "w_n": 50, "l_n": 50, "best_of": 3})
    before = pd.Timestamp("2020-08-01")
    c1 = ke.fit_calibration(d, before, from_season=2015)
    d2 = d.copy()
    late = d2["date"] + pd.Timedelta(days=14) >= before
    d2.loc[late, "w_elo"] = 1000.0
    c2 = ke.fit_calibration(d2, before, from_season=2015)
    assert np.allclose(c1.coef, c2.coef)


def test_walk_forward_uses_earlier_months_only():
    rng = np.random.default_rng(0)
    rows = []
    for mo in ["2026-05", "2026-06", "2026-07", "2026-08"]:
        for _ in range(60):
            e = rng.uniform(-0.1, 0.2)
            pnl = 30 if e >= 0.08 else -10
            rows.append({"month": mo, "edge": e, "pnl_0c": pnl, "pnl_1c": pnl - 1, "cost_0c": 20.0})
    b = pd.DataFrame(rows)
    oos, months = ke.walk_forward(b, min_select_bets=20)
    assert list(months["month"]) == ["2026-06", "2026-07", "2026-08"]
    assert (months["threshold"] == 0.08).all()
    assert (oos["edge"] >= 0.08).all() and set(oos["month"]) == {"2026-06", "2026-07", "2026-08"}
    b2 = b.copy()
    b2.loc[b2["month"] == "2026-08", "pnl_1c"] *= -5         # the test month's own results...
    _, m2 = ke.walk_forward(b2, min_select_bets=20)
    assert list(m2["threshold"]) == list(months["threshold"])  # ...never pick its threshold
    g = ke.gate(oos, months)
    assert g["pass"]


def test_run_end_to_end_smoke():
    sack = sack_frame()
    rng = np.random.default_rng(2)
    rows, quotes, details = [], [], []
    for i in range(60):
        start = pd.Timestamp("2026-06-08 12:00", tz="UTC") + pd.Timedelta(days=2 * i)
        mid = f"K{i}"
        rows.append((mid, start.tz_localize(None), "Pedro Perez", ["Xavier One", "Xavier Two"][i % 2],
                     float(rng.random() < 0.7)))
        for side, ask in (("A", 0.72), ("B", 0.30)):
            quotes.append({"ts": start - pd.Timedelta(minutes=30), "match_id": mid, "side": side, "ask": ask})
        details.append({"match_id": mid, "round": "Round 1", "best_of": "3",
                        "tournament_name": f"T{i}", "gender": "men"})
    m = kmatches(rows)
    text, parts = ke.run(m, pd.DataFrame(quotes), pd.DataFrame(details), sack, load_config(),
                         min_n=1, min_select_bets=5, fit_min_n=0)
    assert "Gate:" in text and "Joins" in text
    assert parts["km"]["id_a"].notna().all()
    assert len(parts["bets"]) == 60
    assert parts["bets"]["p_dog"].between(0, 1).all()
