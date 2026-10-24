"""Walk-forward gate tests on hand-built trade tables and synthetic paths (never results)."""

import numpy as np
import pandas as pd
import pytest

from swinglock.backtest.align import align
from swinglock.backtest.run import main
from swinglock.backtest.swing import TRADE_COLUMNS, match_paths
from swinglock.backtest.walkforward import (WF_DEFAULTS, cluster_mean_ci, evaluate, match_months, select_rule,
                                            walk_forward, wf_settings)
from swinglock.schema import MATCH_COLUMNS, QUOTE_COLUMNS, conform

from test_backtest import CFG, LOCK_PATH

MONTHS = [pd.Period(f"2026-0{m}", "M") for m in range(1, 6)]
R1, R2 = ("first", 0.4, 0.97), ("first", 0.3, 0.95)
COMBOS = [R1, R2]
ST = {**WF_DEFAULTS, "min_train_trades": 1, "n_boot": 500}


def month_ts(period, day=10):
    return pd.Timestamp(f"{period}-{day:02d} 12:00", tz="UTC")


def trade_table(rows):
    """rows: (match_id, rule, pnl, settle_ts)."""
    recs = []
    for mid, (mode, x, y), pnl, settle in rows:
        r = {c: np.nan for c in TRADE_COLUMNS}
        r.update(match_id=mid, mode=mode, x=x, y=y, pnl=pnl, settle_ts=settle, entry_ts=settle,
                 locked=pnl > 0, capital=5.0)
        recs.append(r)
    return pd.DataFrame(recs)


def book(pnl_by_month):
    """{month_index: {rule: [pnl, ...]}} -> (trades, months); one match per pnl value per rule index."""
    rows, months = [], {}
    for k, by_rule in pnl_by_month.items():
        for j, (rule, pnls) in enumerate(by_rule.items()):
            for i, p in enumerate(pnls):
                mid = f"M{k}-{j}-{i}"
                months[mid] = MONTHS[k]
                rows.append((mid, rule, p, month_ts(MONTHS[k])))
    return trade_table(rows), pd.Series(months, dtype=object)


def run(pnl_by_month, st=ST, slip_shift=-0.1):
    """Same trades at 0c; 1c trades are 0c minus `slip_shift` per trade."""
    t0, months = book(pnl_by_month)
    t1 = t0.assign(pnl=t0["pnl"] + slip_shift)
    return evaluate({0.0: t0, 0.01: t1}, months, COMBOS, st)


# R1 wins months 0-1, R2 wins months 2-4: the chosen rule must lag by using only the past.
REGIME = {0: {R1: [1, 1], R2: [0, 0]}, 1: {R1: [1, 1], R2: [-1, 0]}, 2: {R1: [-1, -1], R2: [1, 1]},
          3: {R1: [-1, -1], R2: [2, 2]}, 4: {R1: [-1, -1], R2: [2, 2]}}


def test_folds_choose_on_earlier_months_only():
    wf = run(REGIME)
    f = wf.folds
    assert list(f["test_month"]) == ["2026-02", "2026-03", "2026-04", "2026-05"]
    assert list(f["train_from"]) == ["2026-01"] * 4 and list(f["train_to"]) == ["2026-01", "2026-02", "2026-03",
                                                                                 "2026-04"]
    # training totals at 1c (select_slippage) for Apr: R1 2 - 0.6 = 1.4 beats R2 1 - 0.6 = 0.4
    assert list(zip(f["x"], f["y"])) == [(0.4, 0.97), (0.4, 0.97), (0.4, 0.97), (0.3, 0.95)]
    assert list(f["oos_pnl_0c"]) == pytest.approx([2, -2, -2, 4])
    assert list(f["oos_pnl_1c"]) == pytest.approx([1.8, -2.2, -2.2, 3.8])
    assert list(f["oos_trades_0c"]) == [2, 2, 2, 2]
    assert not wf.passed
    assert any("2 of 4 folds positive at 1c; need 3" in r for r in wf.reasons)
    assert any("OOS trades" in r for r in wf.reasons)


def test_no_lookahead_future_months_cannot_change_a_fold():
    base = run(REGIME).folds.set_index("test_month")
    future = {**REGIME, 3: {R1: [-50, -50], R2: [99, 99]}, 4: {R1: [-50], R2: [99, 99, 99]}}
    alt = run(future).folds.set_index("test_month")
    for m in ("2026-02", "2026-03", "2026-04"):     # choice for a month uses only months before it
        assert (alt.loc[m, ["mode", "x", "y"]] == base.loc[m, ["mode", "x", "y"]]).all()
    assert (alt.loc["2026-04", "x"], alt.loc["2026-04", "y"]) == (0.4, 0.97)


def test_unsettled_training_trades_are_purged():
    t, months = book({0: {R1: [5], R2: [1]}, 1: {R1: [1], R2: [1]}})
    t.loc[t["match_id"] == "M0-0-0", "settle_ts"] = month_ts(MONTHS[1], 2)  # R1's big win settles in test month
    wf = evaluate({0.0: t, 0.01: t}, months, COMBOS, ST)
    assert (wf.folds.iloc[0]["x"], wf.folds.iloc[0]["y"]) == (0.3, 0.95)


def test_min_train_trades_and_rolling_window():
    assert select_rule(trade_table([("a", R1, 1.0, month_ts(MONTHS[0]))]), COMBOS,
                       {**ST, "min_train_trades": 2}) is None
    wf = run(REGIME, st={**ST, "min_train_trades": 99})
    assert wf.folds["mode"].isna().all() and (wf.folds["oos_trades_0c"] == 0).all()
    assert "0 of 4 folds positive" in "; ".join(wf.reasons)
    roll = run(REGIME, st={**ST, "train_months": 1}).folds
    assert list(roll["train_from"]) == list(roll["train_to"]) == ["2026-01", "2026-02", "2026-03", "2026-04"]
    assert list(roll["x"]) == [0.4, 0.4, 0.3, 0.3]        # last month only


def test_objective_mean_vs_total():
    t, months = book({0: {R1: [1, 1, 1], R2: [1.5]}, 1: {R1: [0], R2: [0]}})
    total = evaluate({0.0: t, 0.01: t}, months, COMBOS, ST).folds.iloc[0]
    mean = evaluate({0.0: t, 0.01: t}, months, COMBOS, {**ST, "objective": "mean_pnl"}).folds.iloc[0]
    assert total["x"] == 0.4 and mean["x"] == 0.3
    with pytest.raises(ValueError):
        wf_settings({"backtest": {"walkforward": {"objective": "sharpe"}}})


def test_gate_passes_and_reports_ci():
    good = {k: {R1: [0.5] * 10, R2: [0.1] * 10} for k in range(5)}
    good[2] = {R1: [-0.2] * 10, R2: [0.0] * 10}          # one losing fold is allowed (3 of 4)
    wf = run(good, slip_shift=-0.05)
    assert wf.passed, wf.reasons
    g = wf.gate.set_index("slippage")
    assert g.loc[0.0, "n_folds"] == 4 and g.loc[0.01, "folds_positive"] == 3 and g.loc[0.01, "folds_needed"] == 3
    assert g.loc[0.0, "oos_trades"] == 40 and g.loc[0.0, "oos_pnl"] == pytest.approx(30 * 0.5 - 10 * 0.2)
    assert g.loc[0.01, "mean_pnl"] == pytest.approx(13 / 40 - 0.05)
    assert g.loc[0.0, "ci_lo"] < g.loc[0.0, "mean_pnl"] < g.loc[0.0, "ci_hi"]
    assert len(wf.trades) == 80 and set(wf.trades["slippage"]) == {0.0, 0.01}
    # same trades but 1c turns the total negative -> fail
    assert not run(good, slip_shift=-0.5).passed


def test_cluster_bootstrap_ci():
    assert np.isnan(cluster_mean_ci(np.array([]), np.array([]))).all()
    m, lo, hi = cluster_mean_ci(np.full(6, 0.3), np.array(list("aabbcc")))
    assert (m, lo, hi) == pytest.approx((0.3, 0.3, 0.3))
    m, lo, hi = cluster_mean_ci(np.array([1, 1, -1, -1, 0, 0.5]), np.array(list("aabbcc")), n_boot=4000)
    assert m == pytest.approx(0.25 / 3) and lo < m < hi and lo >= -1 and hi <= 1


# ---- end to end on synthetic quote paths ----------------------------------

def monthly_data(n_per_month=8, n_months=5):
    """LOCK_PATH copies spread over months; every match locks for +$1.35 at 0c."""
    qs, ms = [], []
    for k in range(n_months):
        for i in range(n_per_month):
            mid, t0 = f"M{k}-{i}", pd.Timestamp(f"2026-0{k + 1}-{i + 1:02d} 12:00", tz="UTC")
            rows = [(t0 + pd.Timedelta(seconds=s), side, a) for s, aa, ab in LOCK_PATH for side, a in (("A", aa), ("B", ab))]
            qs.append(pd.DataFrame([dict(ts=ts, match_id=mid, side=sd, ask=a, ask_size=np.nan, source="orderbook")
                                    for ts, sd, a in rows]))
            ms.append(dict(match_id=mid, winner="B", tier="atp", fee_type="quadratic", fee_multiplier=1.0))
    return conform(pd.DataFrame(ms), MATCH_COLUMNS), conform(pd.concat(qs), QUOTE_COLUMNS)


def test_walk_forward_end_to_end():
    m, q = monthly_data()
    paths = match_paths(align(q, m), m, CFG)
    assert match_months(paths)["M3-0"] == pd.Period("2026-04", "M")
    cfg = {**CFG, "backtest": {**CFG["backtest"], "walkforward": {"min_train_trades": 5}}}
    wf = walk_forward(paths, cfg)
    assert len(wf.folds) == 4 and wf.passed, wf.reasons
    g = wf.gate.set_index("slippage")
    assert g.loc[0.0, "oos_trades"] == 32
    assert g.loc[0.0, "mean_pnl"] == pytest.approx(1.35)
    assert g.loc[0.01, "mean_pnl"] == pytest.approx(1.35 - 0.20)   # 10c on each of the two 10-lots
    assert (wf.folds["x"] == 0.40).all()                          # 0.30 never triggers


def test_cli_writes_walkforward(tmp_path):
    m, q = monthly_data(n_per_month=2)
    data = tmp_path / "data"
    data.mkdir()
    m.to_parquet(data / "matches.parquet")
    q.to_parquet(data / "quotes.parquet")
    out = tmp_path / "out"
    assert main(["--data", str(data), "--out", str(out), "--modes", "first"]) == 0
    for f in ("walkforward_folds.csv", "walkforward_trades.csv", "walkforward_gate.csv"):
        assert (out / f).exists()
    md = (out / "backtest_summary.md").read_text()
    assert "Walk-forward gate" in md and "FAIL" in md and "need >= 30" in md
