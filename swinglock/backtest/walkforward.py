"""Walk-forward gate for swing-lock rules (X, Y): choose on earlier months, test on the next.

Each match belongs to the calendar month (UTC) of its first aligned observation. For every
test month with at least `min_train_months` earlier months, the rule (mode, X, Y) with the
best training objective is chosen from the grid using only trades from earlier months that
had also SETTLED before the test month began (purge: an outcome not yet known at the fold
start can't inform the choice). The chosen rule is then run, unchanged, on the test month's
matches at each reported slippage (default 0c and 1c).

The gate (CLAUDE.md / docs/team/backtest.md) passes only if:
- there are at least `min_folds` folds (default 4);
- out-of-sample P&L is positive in at least ceil(pass_frac * folds) folds (3 of 4, 4 of 5)
  at the WORST reported slippage;
- total out-of-sample P&L is positive at every reported slippage;
- there are at least `min_oos_trades` out-of-sample trades (default 30).
The no-lookahead requirement is covered by tests (tests/test_backtest*.py), not checked here.

The confidence interval for mean P&L per trade is a percentile bootstrap that resamples
whole matches (trades in the same match, e.g. mode "both", are not independent).

Settings come from config `backtest.walkforward` (all optional; defaults in WF_DEFAULTS).
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .grid import KEYS, combos as grid_combos, grid_trades
from .swing import TRADE_COLUMNS, MatchPath

WF_DEFAULTS: dict[str, Any] = dict(
    min_train_months=1,       # earlier months required before a month can be a test fold
    train_months=None,        # None = expanding window; N = rolling window of the last N months
    min_train_trades=10,      # a rule needs this many training trades to be eligible
    objective="total_pnl",    # or "mean_pnl" (per trade)
    select_slippage=0.01,     # slippage used when choosing the rule on training data
    slippages=[0.0, 0.01],    # slippages the chosen rule is evaluated at out of sample
    min_folds=4,
    pass_frac=0.75,           # positive folds needed: ceil(pass_frac * folds)
    min_oos_trades=30,
    ci_level=0.95,
    n_boot=2000,
    seed=0,
)
OBJECTIVES = ("total_pnl", "mean_pnl")
GATE_COLUMNS = ["slippage", "n_folds", "folds_positive", "folds_needed", "oos_trades", "oos_matches",
                "oos_pnl", "mean_pnl", "ci_lo", "ci_hi"]


def wf_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    st = {**WF_DEFAULTS, **((cfg.get("backtest") or {}).get("walkforward") or {})}
    if st["objective"] not in OBJECTIVES:
        raise ValueError(f"walkforward.objective must be one of {OBJECTIVES}, got {st['objective']!r}")
    return st


def slip_label(s: float) -> str:
    """0.01 -> '1c' (column suffix)."""
    return f"{round(s * 100, 2):g}c"


def with_slippage(cfg: dict[str, Any], slippage: float) -> dict[str, Any]:
    out = copy.deepcopy(cfg)
    out.setdefault("execution", {})["slippage"] = float(slippage)
    return out


def match_months(paths: Sequence[MatchPath]) -> pd.Series:
    """match_id -> calendar month (UTC) of the match's first aligned observation."""
    return pd.Series({p.match_id: pd.Timestamp(p.ts[0]).tz_convert("UTC").tz_localize(None).to_period("M")
                      for p in paths}, dtype=object)


def _month_start(period: pd.Period) -> pd.Timestamp:
    return period.start_time.tz_localize("UTC")


def select_rule(train: pd.DataFrame, combos: Sequence[tuple[str, float, float]],
                st: dict[str, Any]) -> dict[str, Any] | None:
    """Best (mode, x, y) on training trades, or None when no rule has enough trades.
    Ties: more trades, then lowest (mode, x, y), so the choice is deterministic."""
    if train.empty:
        return None
    g = train.groupby(KEYS)["pnl"].agg(n="size", total="sum")
    g["mean"] = g["total"] / g["n"]
    g = g[g["n"] >= st["min_train_trades"]]
    allowed = {(m, float(x), float(y)) for m, x, y in combos}
    g = g[[(m, float(x), float(y)) in allowed for m, x, y in g.index]]
    if g.empty:
        return None
    key = "total" if st["objective"] == "total_pnl" else "mean"
    g = g.reset_index().sort_values([key, "n", *KEYS], ascending=[False, False, True, True, True], kind="stable")
    best = g.iloc[0]
    return dict(mode=best["mode"], x=float(best["x"]), y=float(best["y"]),
                train_trades=int(best["n"]), train_pnl=float(best["total"]))


def cluster_mean_ci(pnl: np.ndarray, groups: np.ndarray, level: float = 0.95, n_boot: int = 2000,
                    seed: int = 0) -> tuple[float, float, float]:
    """(mean per trade, lo, hi): percentile bootstrap resampling whole groups (matches)."""
    pnl = np.asarray(pnl, float)
    if not pnl.size:
        return (np.nan, np.nan, np.nan)
    codes, uniq = pd.factorize(pd.Series(groups))
    sums = np.bincount(codes, weights=pnl, minlength=len(uniq))
    counts = np.bincount(codes, minlength=len(uniq)).astype(float)
    mean = float(pnl.mean())
    idx = np.random.default_rng(seed).integers(0, len(uniq), size=(n_boot, len(uniq)))
    boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    a = (1 - level) / 2
    return mean, float(np.quantile(boot, a)), float(np.quantile(boot, 1 - a))


@dataclass
class WalkForward:
    folds: pd.DataFrame                   # one row per fold: chosen rule, train and OOS numbers
    trades: pd.DataFrame                  # OOS trades (TRADE_COLUMNS + mode/x/y, fold, test_month, slippage)
    gate: pd.DataFrame                    # GATE_COLUMNS, one row per reported slippage
    passed: bool
    reasons: list[str] = field(default_factory=list)   # failed gate checks (empty when passed)


def evaluate(trades_by_slip: dict[float, pd.DataFrame], months: pd.Series,
             combos: Sequence[tuple[str, float, float]], st: dict[str, Any]) -> WalkForward:
    """Walk-forward over precomputed grid trades (one table per slippage, tagged mode/x/y)."""
    report = [float(s) for s in st["slippages"]]
    periods = sorted(set(months.dropna()))
    tagged = {s: t.assign(period=t["match_id"].map(months)) for s, t in trades_by_slip.items()}
    sel_all = tagged[float(st["select_slippage"])]

    fold_rows, oos = [], []
    for k, test in enumerate(periods):
        train_periods = periods[:k]
        if st["train_months"]:
            train_periods = train_periods[-int(st["train_months"]):]
        if len(train_periods) < st["min_train_months"]:
            continue
        start = _month_start(test)
        train = sel_all[sel_all["period"].isin(train_periods) & (sel_all["settle_ts"] < start)]
        rule = select_rule(train, combos, st)
        row = dict(fold=len(fold_rows) + 1, test_month=str(test), train_from=str(train_periods[0]),
                   train_to=str(train_periods[-1]), train_matches=int(months.isin(train_periods).sum()),
                   test_matches=int((months == test).sum()), mode=None, x=np.nan, y=np.nan,
                   train_trades=0, train_pnl=np.nan)
        if rule:
            row.update(rule)
        for s in report:
            lab = slip_label(s)
            t = tagged[s]
            te = t.iloc[:0]
            if rule:
                te = t[(t["period"] == test) & (t["mode"] == rule["mode"]) & np.isclose(t["x"], rule["x"])
                       & np.isclose(t["y"], rule["y"])]
            row[f"oos_trades_{lab}"] = len(te)
            row[f"oos_pnl_{lab}"] = float(te["pnl"].sum())
            row[f"oos_lock_rate_{lab}"] = float(te["locked"].mean()) if len(te) else np.nan
            oos.append(te.drop(columns="period").assign(fold=row["fold"], test_month=row["test_month"], slippage=s))
        fold_rows.append(row)

    fold_cols = ["fold", "test_month", "train_from", "train_to", "train_matches", "test_matches", *KEYS,
                 "train_trades", "train_pnl",
                 *[f"oos_{m}_{slip_label(s)}" for s in report for m in ("trades", "pnl", "lock_rate")]]
    folds = pd.DataFrame(fold_rows, columns=fold_cols)
    oos_cols = [*TRADE_COLUMNS, *KEYS, "fold", "test_month", "slippage"]
    oos_df = pd.concat([o for o in oos if len(o)], ignore_index=True) if any(len(o) for o in oos) \
        else pd.DataFrame(columns=oos_cols)
    return _gate(folds, oos_df[oos_cols], report, st)


def _gate(folds: pd.DataFrame, oos: pd.DataFrame, report: list[float], st: dict[str, Any]) -> WalkForward:
    n = len(folds)
    need = math.ceil(st["pass_frac"] * n) if n else 0
    rows = []
    for s in report:
        t = oos[np.isclose(oos["slippage"].astype(float), s)] if len(oos) else oos
        mean, lo, hi = cluster_mean_ci(t["pnl"].to_numpy(float), t["match_id"].to_numpy(),
                                       st["ci_level"], st["n_boot"], st["seed"])
        rows.append(dict(slippage=s, n_folds=n,
                         folds_positive=int((folds[f"oos_pnl_{slip_label(s)}"] > 0).sum()) if n else 0,
                         folds_needed=need, oos_trades=len(t), oos_matches=int(t["match_id"].nunique()),
                         oos_pnl=float(t["pnl"].sum()), mean_pnl=mean, ci_lo=lo, ci_hi=hi))
    gate = pd.DataFrame(rows, columns=GATE_COLUMNS)

    reasons = []
    if n < st["min_folds"]:
        reasons.append(f"only {n} fold(s); need >= {st['min_folds']}")
    if len(gate):
        worst = gate.loc[gate["slippage"].idxmax()]
        if worst["folds_positive"] < need or n == 0:
            reasons.append(f"{int(worst['folds_positive'])} of {n} folds positive at {slip_label(worst['slippage'])}; "
                           f"need {need}")
        for r in gate.itertuples():
            if not r.oos_pnl > 0:
                reasons.append(f"OOS P&L ${r.oos_pnl:.2f} not positive at {slip_label(r.slippage)}")
        if gate["oos_trades"].min() < st["min_oos_trades"]:
            reasons.append(f"{int(gate['oos_trades'].min())} OOS trades; need >= {st['min_oos_trades']}")
    return WalkForward(folds, oos, gate, passed=not reasons, reasons=reasons)


def walk_forward(paths: Sequence[MatchPath], cfg: dict[str, Any], modes: Sequence[str] = ("first",)) -> WalkForward:
    """Simulate the whole grid at each needed slippage, then run the walk-forward gate."""
    st = wf_settings(cfg)
    slips = sorted({float(s) for s in st["slippages"]} | {float(st["select_slippage"])})
    trades = {s: grid_trades(list(paths), with_slippage(cfg, s), modes) for s in slips}
    return evaluate(trades, match_months(paths), grid_combos(cfg, modes), st)
