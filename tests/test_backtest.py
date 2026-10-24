"""Backtest unit tests on small hand-built quote paths (synthetic; never results)."""

import numpy as np
import pandas as pd
import pytest

from swinglock.backtest.align import align
from swinglock.backtest.arb import scan_arb
from swinglock.backtest.grid import entry_diagnostics, grid_search, grid_trades
from swinglock.backtest.metrics import breakdown, capital_usage, max_drawdown, summarize
from swinglock.backtest.run import main
from swinglock.backtest.swing import entry_filters, match_paths, simulate
from swinglock.schema import MATCH_COLUMNS, QUOTE_COLUMNS, conform

T0 = pd.Timestamp("2026-01-01 12:00", tz="UTC")
CFG = {
    "fees": {"kalshi": {"taker_rate": 0.07, "maker_rate": 0.0175, "default_multiplier": 1.0,
                        "rounding_increment": 0.01}},
    "execution": {"slippage": 0.0, "max_contracts_per_trade": 100},
    "backtest": {"entry_thresholds": [0.30, 0.40], "lock_thresholds": [0.95, 0.97],
                 "contracts_per_entry": 10, "min_arb_profit": 0.0},
}


def t(sec: float) -> pd.Timestamp:
    return T0 + pd.Timedelta(seconds=sec)


def quotes(rows, match="M1", source="orderbook") -> pd.DataFrame:
    """rows: (sec, side, ask, ask_size)."""
    return conform(pd.DataFrame([dict(ts=t(s), match_id=match, side=side, ask=a, ask_size=sz, source=source)
                                 for s, side, a, sz in rows]), QUOTE_COLUMNS)


def path(rows, match="M1", size=np.nan, source="orderbook") -> pd.DataFrame:
    """rows: (sec, ask_a, ask_b) with both sides quoted at the same instant."""
    return quotes([(s, side, a, size) for s, aa, ab in rows for side, a in (("A", aa), ("B", ab))],
                  match, source)


def matches(*ids, winner="B", start=None, tier="atp", settle=(np.nan, np.nan)) -> pd.DataFrame:
    return conform(pd.DataFrame([dict(match_id=m, winner=winner, tier=tier, fee_type="quadratic",
                                      fee_multiplier=1.0, scheduled_start=start, settle_a=settle[0],
                                      settle_b=settle[1]) for m in ids]), MATCH_COLUMNS)


def trades_for(q, m, x=0.40, y=0.97, mode="first", cfg=CFG):
    return simulate(match_paths(align(q, m), m, cfg), x, y, cfg, mode)


# ---- alignment -----------------------------------------------------------

def test_align_asof_no_lookahead_and_phase():
    q = quotes([(0, "A", 0.40, 5), (5, "B", 0.55, 7), (20, "A", 0.42, 5)])
    al = align(q, matches("M1", start=t(10)))
    assert list(al["ts"]) == [t(5), t(20)]          # t=0 has no B quote yet
    assert list(al["ask_a"]) == [0.40, 0.42]
    assert list(al["ask_b"]) == [0.55, 0.55]
    assert list(al["phase"]) == ["pre", "live"]
    assert list(align(q)["phase"]) == ["unknown", "unknown"]


def test_staleness_limit():
    q = quotes([(0, "A", 0.40, 5), (0, "B", 0.50, 5), (100, "A", 0.41, 5)])
    assert list(align(q)["ts"]) == [t(0)]           # B is 100s old at t=100 > 60s
    assert list(align(q, max_staleness_s=200)["ts"]) == [t(0), t(100)]


# ---- true arb ------------------------------------------------------------

def test_arb_episode_duration_and_profit():
    q = quotes([(s, side, a, sz) for s, aa, ab, sa, sb in [
        (0, 0.50, 0.52, 50, 30), (10, 0.45, 0.50, 50, 30), (20, 0.44, 0.50, 50, 30), (30, 0.50, 0.52, 50, 30)]
        for side, a, sz in (("A", aa, sa), ("B", ab, sb))])
    eps, summ = scan_arb(align(q), matches("M1"), CFG)
    assert len(eps) == 1
    e = eps.iloc[0]
    assert (e["start"], e["end"], e["duration_s"], e["n_obs"]) == (t(10), t(20), 10.0, 2)
    # best fill at t=20: 30 x (1 - 0.94) - fee(0.44, 30)=0.52 - fee(0.50, 30)=0.53
    assert e["contracts"] == 30
    assert e["profit"] == pytest.approx(1.80 - 0.52 - 0.53)
    assert e["best_edge"] == pytest.approx(0.75 / 30)
    assert e["depth_known"]
    assert summ.iloc[0]["frac_arb"] == pytest.approx(0.5)
    assert summ.iloc[0]["n_episodes"] == 1


def test_arb_depth_capped_and_gap_splits_episode():
    q = path([(0, 0.45, 0.50), (30, 0.45, 0.50), (200, 0.45, 0.50)], size=500)
    eps, _ = scan_arb(align(q), matches("M1"), CFG)
    assert list(eps["n_obs"]) == [2, 1]             # 170s data gap > staleness splits the episode
    assert (eps["contracts"] == 100).all()          # execution.max_contracts_per_trade


def test_combined_below_1_but_fees_kill_it():
    eps, summ = scan_arb(align(path([(0, 0.49, 0.50), (10, 0.49, 0.50)], size=10)), matches("M1"), CFG)
    assert eps.empty
    assert summ.iloc[0]["min_combined"] == pytest.approx(0.99)
    assert summ.iloc[0]["frac_arb"] == 0


def test_arb_nan_depth_assumes_one_contract():
    eps, _ = scan_arb(align(path([(0, 0.40, 0.50)], source="candle")), matches("M1"), CFG)
    e = eps.iloc[0]
    assert e["contracts"] == 1 and not e["depth_known"]
    assert e["profit"] == pytest.approx(1 - 0.90 - 0.02 - 0.02)   # each 1-lot fee rounds up to 2c


# ---- swing lock ----------------------------------------------------------
# Entry A @ 0.38 x 10: 3.80 + fee 0.17 = 3.97 (0.397 all-in).
# Lock B @ 0.45 x 10: 4.50 + fee 0.18 = 4.68; 0.397 + 0.45 + 0.0173 = 0.864 <= Y.

LOCK_PATH = [(0, 0.60, 0.64), (10, 0.38, 0.64), (20, 0.70, 0.45), (30, 0.40, 0.62)]


def test_lock_triggers():
    tr = trades_for(path(LOCK_PATH), matches("M1", start=t(15)))
    assert len(tr) == 1
    r = tr.iloc[0]
    assert (r["side"], r["entry_ts"], r["entry_ask"], r["role"], r["entry_phase"]) == ("A", t(10), 0.38, "underdog", "pre")
    assert r["entry_cost"] == pytest.approx(3.97)
    assert r["locked"] and r["lock_ts"] == t(20) and r["lock_ask"] == 0.45
    assert r["lock_cost"] == pytest.approx(4.68)
    assert r["pnl"] == pytest.approx(10 - 3.97 - 4.68)
    assert r["capital"] == pytest.approx(8.65)
    assert r["hold_s"] == 10.0


def test_unlocked_position_loses_at_settlement():
    tr = trades_for(path([(0, 0.60, 0.64), (10, 0.38, 0.64), (20, 0.36, 0.62), (30, 0.10, 0.95)]), matches("M1"))
    r = tr.iloc[0]
    assert not r["locked"] and pd.isna(r["lock_ts"])
    assert r["pnl"] == pytest.approx(-3.97)
    assert r["settle_ts"] == t(30) and r["hold_s"] == 20.0
    m = summarize(tr)
    assert m["avg_unlocked_loss"] == pytest.approx(-3.97) and m["lock_rate"] == 0 and m["hit_rate"] == 0


def test_no_lookahead_lock_waits_for_the_price():
    # B's cheap ask is first quoted at t=25; nothing before that may lock.
    q = quotes([(0, "A", 0.60, np.nan), (10, "A", 0.38, np.nan), (20, "A", 0.50, np.nan), (30, "A", 0.55, np.nan),
                (0, "B", 0.64, np.nan), (15, "B", 0.64, np.nan), (25, "B", 0.45, np.nan)])
    m = matches("M1")
    r = trades_for(q, m).iloc[0]
    assert r["entry_ts"] == t(10) and r["lock_ts"] == t(25)
    # truncating the future can't change past decisions
    r2 = trades_for(q[q["ts"] < t(25)], m).iloc[0]
    assert r2["entry_ts"] == t(10) and not r2["locked"]


def test_entry_size_limited_by_depth_and_modes():
    q = quotes([(0, "A", 0.38, 4), (0, "B", 0.66, 50), (10, "A", 0.70, 50), (10, "B", 0.30, 50)])
    m = matches("M1", winner="A")
    first = trades_for(q, m)
    assert list(first["side"]) == ["A"] and first.iloc[0]["contracts"] == 4
    both = trades_for(q, m, mode="both")
    assert list(both["side"]) == ["A", "B"]
    with pytest.raises(ValueError):
        trades_for(q, m, mode="xyz")


def test_unsettled_matches_skipped():
    assert trades_for(path(LOCK_PATH), matches("M1", winner=None)).empty
    assert trades_for(path(LOCK_PATH), matches("M1", winner=None, settle=(0.4, np.nan))).empty


# ---- settlement payouts (settle_a / settle_b) ---------------------------

NO_LOCK_PATH = [(0, 0.60, 0.64), (10, 0.38, 0.64), (20, 0.36, 0.62), (30, 0.40, 0.60)]


def test_fair_price_unlocked_trade():
    # Match never started: no winner, A pays 0.40 and B 0.60 per contract.
    r = trades_for(path(NO_LOCK_PATH), matches("M1", winner=None, settle=(0.40, 0.60))).iloc[0]
    assert not r["locked"] and r["winner"] == "NA"
    assert (r["settle_a"], r["settle_b"]) == (0.40, 0.60)
    assert r["pnl"] == pytest.approx(10 * 0.40 - 3.97)


def test_fair_price_locked_trade_pays_contracts():
    # Equal counts on both sides pay $1 per pair whatever the fair price split.
    r = trades_for(path(LOCK_PATH), matches("M1", winner=None, settle=(0.30, 0.70))).iloc[0]
    assert r["locked"] and r["pnl"] == pytest.approx(10 - 3.97 - 4.68)


def test_settle_columns_win_over_winner_and_fall_back_to_it():
    r = trades_for(path(NO_LOCK_PATH), matches("M1", winner="B", settle=(1.0, 0.0))).iloc[0]
    assert r["pnl"] == pytest.approx(10 - 3.97)          # payouts decide, winner label is ignored
    r = trades_for(path(NO_LOCK_PATH), matches("M1", winner="A")).iloc[0]   # old file: NaN payouts
    assert (r["settle_a"], r["settle_b"], r["pnl"]) == (1.0, 0.0, pytest.approx(10 - 3.97))


# ---- metrics / grid ------------------------------------------------------

def test_max_drawdown_known_sequence():
    assert max_drawdown([1, -2, 3, -4, 1]) == pytest.approx(4)   # cum 1,-1,2,-2,-1
    assert max_drawdown([-1, -1]) == pytest.approx(2)            # peak starts at 0
    assert max_drawdown([]) == 0
    order = [2, 0, 4, 1, 3]                                      # rows shuffled; settle_ts orders them
    pnl = [1, -2, 3, -4, 1]
    tr = pd.DataFrame(dict(settle_ts=[t(i) for i in order], pnl=[pnl[i] for i in order],
                           entry_ts=[t(i - 1) for i in order], entry_cost=1.0, lock_ts=pd.NaT,
                           lock_cost=0.0, capital=1.0, locked=False))
    assert summarize(tr)["max_drawdown"] == pytest.approx(4)


def test_capital_usage():
    tr = pd.DataFrame(dict(entry_ts=[t(0), t(50)], entry_cost=[4.0, 6.0], locked=[False, True],
                           lock_ts=[pd.NaT, t(60)], lock_cost=[0.0, 3.0], settle_ts=[t(100), t(200)],
                           capital=[4.0, 9.0]))
    peak, avg = capital_usage(tr)
    assert peak == pytest.approx(13)
    assert avg == pytest.approx((4 * 50 + 10 * 10 + 13 * 40 + 9 * 100) / 200)


def test_grid_and_breakdown():
    q = pd.concat([path(LOCK_PATH, "M1"), path(LOCK_PATH, "M2")])
    m = pd.concat([matches("M1", tier="atp"), matches("M2", tier="wta")])
    g = grid_search(align(q, m), m, CFG, modes=("first", "both"))
    assert len(g) == 2 * 2 * 2
    assert (g.loc[g["x"] == 0.30, "n_trades"] == 0).all()      # A never trades <= 0.30
    hit = g[(g["x"] == 0.40) & (g["y"] == 0.97) & (g["mode"] == "first")].iloc[0]
    assert hit["n_trades"] == 2 and hit["lock_rate"] == 1 and hit["total_pnl"] == pytest.approx(2 * 1.35)
    bd = breakdown(trades_for(q, m))
    assert set(bd["dimension"]) == {"entry_phase", "role", "tier"}
    assert bd.set_index(["dimension", "value"]).loc[("tier", "wta"), "n_trades"] == 1


def test_cli_empty_data_dir(tmp_path, capsys):
    assert main(["--data", str(tmp_path / "missing"), "--out", str(tmp_path / "out")]) == 0
    assert "Nothing to do" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_cli_end_to_end(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    matches("M1", start=t(15)).to_parquet(data / "matches.parquet")
    path(LOCK_PATH).to_parquet(data / "quotes.parquet")
    assert main(["--data", str(data), "--out", str(tmp_path / "out")]) == 0
    for f in ("arb_episodes.csv", "arb_by_match.csv", "grid_metrics.csv", "grid_trades.csv",
              "breakdowns.csv", "grid_entries.csv", "backtest_summary.md"):
        assert (tmp_path / "out" / f).exists()


# ---- entry diagnostics and filters ------------------------------------------
# B dips to 0.38 ten minutes in; A collapses to 4c and 3c late (a near-decided match).

LATE_PATH = [(0, 0.60, 0.42), (600, 0.62, 0.38), (1200, 0.04, 0.97), (1800, 0.03, 0.98)]


def cfg_with(**bt):
    return {**CFG, "backtest": {**CFG["backtest"], **bt}}


def test_entry_timing_fields():
    m = matches("M1", winner="A", start=t(0))
    r = trades_for(path(LATE_PATH), m, x=0.20).iloc[0]
    assert (r["side"], r["entry_ask"]) == ("A", 0.04)
    assert r["minutes_to_close"] == pytest.approx(10) and r["minutes_from_start"] == pytest.approx(20)
    r = trades_for(path(LATE_PATH), matches("M1", winner="A"), x=0.40).iloc[0]
    assert (r["side"], r["minutes_to_close"]) == ("B", pytest.approx(20)) and np.isnan(r["minutes_from_start"])


def test_entry_filters():
    q, m = path(LATE_PATH), matches("M1", winner="A", start=t(0))
    assert len(trades_for(q, m, x=0.20, cfg=cfg_with(min_entry_ask=None))) == 1      # null = off
    assert trades_for(q, m, x=0.20, cfg=cfg_with(min_entry_ask=0.05)).empty         # 4c and 3c skipped
    assert trades_for(q, m, x=0.40, cfg=cfg_with(min_entry_ask=0.05)).iloc[0]["side"] == "B"
    # minutes after scheduled start (known live): B at +10 min passes 15, A at +20 doesn't
    assert trades_for(q, m, x=0.40, cfg=cfg_with(max_minutes_from_start=15)).iloc[0]["side"] == "B"
    assert trades_for(q, m, x=0.20, cfg=cfg_with(max_minutes_from_start=15)).empty
    assert trades_for(q, matches("M1", winner="A"), x=0.40, cfg=cfg_with(max_minutes_from_start=15)).empty
    # minutes to the last observation (lookahead diagnostic): B entry is 20 min before the end
    assert trades_for(q, m, x=0.40, cfg=cfg_with(min_minutes_to_close=15)).iloc[0]["side"] == "B"
    assert trades_for(q, m, x=0.40, cfg=cfg_with(min_minutes_to_close=25)).empty


def test_entry_diagnostics_per_rule():
    q = pd.concat([path(LATE_PATH, "M1"), path(LATE_PATH, "M2")])
    m = pd.concat([matches("M1", winner="A", start=t(0)), matches("M2", winner="A", start=t(0))])
    d = entry_diagnostics(grid_trades(match_paths(align(q, m), m, CFG), CFG), CFG).set_index(["x", "y"])
    late, swing = d.loc[(0.30, 0.97)], d.loc[(0.40, 0.97)]
    assert late["n_trades"] == 2 and late["ask_p50"] == pytest.approx(0.04)
    assert late["frac_ask_lt_5c"] == 1 and late["mtc_p50"] == pytest.approx(10) and late["frac_live"] == 1
    assert late["pnl_ask_lt_10c"] > 0 and np.isnan(late["pnl_ask_ge_10c"])     # A wins from 4c: +$9.57
    assert swing["ask_p50"] == pytest.approx(0.38) and swing["frac_ask_lt_10c"] == 0
    assert swing["mtc_p50"] == pytest.approx(20)
    assert swing["pnl_ask_ge_10c"] == pytest.approx(10 - 3.97 - 0.43)              # B 0.38 locked by A at 4c


def test_in_play_window_and_phase_filters():
    # Start at t=900s: rows at -15, -5 (pre) and +5, +15 min (live). B dips to 0.38 pre-match;
    # A collapses to 4c in play.
    q, m = path(LATE_PATH), matches("M1", winner="A", start=t(900))
    side = lambda **f: list(trades_for(q, m, x=0.40, cfg=cfg_with(**f))["side"])   # noqa: E731
    assert side() == ["B"]
    assert side(entry_phase="any") == ["B"] and side(entry_phase=None) == ["B"]
    assert side(entry_phase="live") == ["A"] and side(entry_phase="pre") == ["B"]
    assert side(min_minutes_from_start=0, max_minutes_from_start=60) == ["A"]     # in play, first hour
    assert side(min_minutes_from_start=0) == ["A"]
    assert side(min_minutes_from_start=-10, max_minutes_from_start=0) == ["B"]
    r = trades_for(q, m, x=0.40, cfg=cfg_with(min_minutes_from_start=6, max_minutes_from_start=60)).iloc[0]
    assert (r["side"], r["entry_ask"], r["minutes_from_start"]) == ("A", 0.03, 15)   # skips the +5 min row
    assert trades_for(q, matches("M1", winner="A"), x=0.40, cfg=cfg_with(min_minutes_from_start=0)).empty
    assert entry_filters(cfg_with(entry_phase="live", min_minutes_from_start=0)) == \
        {"entry_phase": "live", "min_minutes_from_start": 0.0}
    with pytest.raises(ValueError):
        entry_filters(cfg_with(entry_phase="inplay"))
