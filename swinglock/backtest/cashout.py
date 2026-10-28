"""Cash-out (take-profit) study, pre-registered in docs/edge_cashout.md.

For selection-neutral entries (E1: both players at a match's first `pre` observation; E2: both at
its first `live` one), compare selling at the bid when a take-profit rule triggers with holding the
same position to settlement:

    delta = P&L(sell at the bid on trigger) - P&L(hold)        (0 when the rule never triggers)

Entry: ask + slippage, taker fee rounded up per order, `backtest.contracts_per_entry` contracts
(capped by ask depth when known). Exit: the first row strictly after the entry where the net bid
per contract, (bid - slippage) - fee / n, is >= entry all-in + T (absolute rules), >= k x entry
all-in (relative rules) or >= L (level rules, only for entries with all-in < L), with bid size >= n
when known. Hold: n x settle_side - entry cost.

Addendum of 2026-10-28 (dated in docs/edge_cashout.md): level rules; live exits tagged set end /
mid-set from Kalshi set-winner close times (descriptive); the owner's DOG50 strategy (dogs < 20c,
sell at 50c) gated on absolute P&L as a fixed rule.

No lookahead: an exit uses only its own aligned row (quotes at or before it); settlement is used
only for the hold leg.

On Kalshi's paired markets bid(A) = 1 - ask(B) by construction (see `identity_check`) and the fee is
symmetric, so a take-profit at T is the swing lock at Y = 1 - T.

    python -m swinglock.backtest.cashout --data data/processed/kalshi --out reports/

Outputs are aggregates only (no per-position rows): Kalshi data stays private.
"""

from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from ..config import kalshi_fees, load_config
from ..fees import _EPS, FeeModel
from ..locks import SIDES
from .align import align, match_fees, staleness_s
from .run import load, md_table
from .swing import settlement
from .walkforward import WalkForward, cluster_mean_ci, evaluate, slip_label, wf_settings

ENTRY_TYPES = {"E1": "pre", "E2": "live"}
# addendum 5 (post hoc, descriptive only, never gated): E1 at the first pre row with a formed book. The
# first pre row is usually the listing-time placeholder book (median ask_a + ask_b $1.84 / $1.88).
E1R, E1R_MAX_COMBINED = "E1r", 1.05
ABS_T = (0.03, 0.05, 0.10, 0.15, 0.20, 0.30)
REL_K = (1.5, 2.0, 3.0)
LEVEL_L = (0.40, 0.50, 0.60)
ABSOLUTE, RELATIVE, LEVEL, HOLD = 0.0, 1.0, 2.0, 3.0   # rule kind, stored in the walk-forward's "x" column
RULES: tuple[tuple[float, float], ...] = (*((ABSOLUTE, t) for t in ABS_T), *((RELATIVE, k) for k in REL_K),
                                          *((LEVEL, v) for v in LEVEL_L))
BAND_EDGES = (0.0, 0.20, 0.40, 0.60, 0.80, 1.0 + 1e-9)
BAND_LABELS = ("<20c", "20-40c", "40-60c", "60-80c", ">=80c")
SLIPPAGES = (0.0, 0.01)

POSITION_COLUMNS = ["match_id", "tier", "mode", "x", "y", "rule", "side", "band", "entry_ts", "entry_phase",
                    "entry_ask", "contracts", "entry_cost", "settle_ts", "settle_side", "hold_pnl", "locked",
                    "exit_ts", "exit_phase", "exit_bid", "exit_bid_age_s", "exit_value", "minutes_to_exit",
                    "rule_pnl", "pnl"]


def rule_label(kind: float, value: float) -> str:
    if kind == HOLD:
        return "hold"
    if kind == LEVEL:
        return f"L={value * 100:g}c"
    return f"T={value * 100:g}c" if kind == ABSOLUTE else f"k={value:g}"


def fee_vec(fm: FeeModel, price: np.ndarray, contracts: float) -> np.ndarray:
    """`FeeModel.fee` (taker, rounded up per order) for an array of prices."""
    raw = fm.multiplier * fm.taker_rate * contracts * price * (1.0 - price)
    if fm.rounding_increment > 0:
        raw = np.ceil(raw / fm.rounding_increment - _EPS) * fm.rounding_increment
    return np.round(raw, 10)


@dataclass
class CashPath:
    match_id: str
    tier: str
    pay: dict[str, float]
    fees: FeeModel
    ts: pd.DatetimeIndex
    phase: np.ndarray
    ask: dict[str, np.ndarray]
    ask_size: dict[str, np.ndarray]
    bid: dict[str, np.ndarray]
    bid_size: dict[str, np.ndarray]
    bid_age: dict[str, np.ndarray]     # seconds the bid's source quote has been unchanged

    @property
    def settle_ts(self) -> pd.Timestamp:
        return self.ts[-1]


def cash_paths(aligned: pd.DataFrame, matches: pd.DataFrame, cfg: dict[str, Any]) -> list[CashPath]:
    """One path per settled match (payouts or an A/B winner) with aligned quotes."""
    fees = match_fees(matches, cfg)
    m = matches.drop_duplicates("match_id").set_index("match_id")
    out = []
    for mid, g in aligned.groupby("match_id", sort=True):
        if mid not in m.index or (pay := settlement(m.loc[mid])) is None:
            continue
        g = g.sort_values("ts", kind="stable")
        tier = m.at[mid, "tier"]
        col = lambda name: {s: g[f"{name}_{s.lower()}"].to_numpy(float) for s in SIDES}   # noqa: E731
        out.append(CashPath(str(mid), tier if isinstance(tier, str) else "unknown", dict(zip(SIDES, pay)),
                            fees[mid], pd.DatetimeIndex(g["ts"]), g["phase"].to_numpy(object),
                            col("ask"), col("size"), col("bid"), col("bsize"),
                            # bid(A) = 1 - ask(B) from the same two market quotes, so A's bid is as
                            # old as B's ask (align's age_b), and vice versa
                            {"A": g["age_b"].to_numpy(float), "B": g["age_a"].to_numpy(float)}))
    return out


def _band(ask: float) -> str:
    return BAND_LABELS[int(np.searchsorted(BAND_EDGES, ask, side="right")) - 1]


def _positions(p: CashPath, entry: str, contracts: float, slip: float,
               rules: Sequence[tuple[float, float]] = RULES) -> list[dict]:
    """Rows (one per side x rule) for one match and entry type; [] if there is no such entry."""
    if entry == E1R:
        idx = np.flatnonzero((p.phase == "pre") & (p.ask["A"] + p.ask["B"] <= E1R_MAX_COMBINED + 1e-9))
    else:
        idx = np.flatnonzero(p.phase == ENTRY_TYPES[entry])
    if not idx.size:
        return []
    i, rows = int(idx[0]), []
    for side in SIDES:
        ask, size = float(p.ask[side][i]), p.ask_size[side][i]
        if not 0 < ask < 1 or (not np.isnan(size) and size <= 0):
            continue
        n = contracts if np.isnan(size) else min(contracts, float(size))
        fill = min(ask + slip, 1.0)
        entry_cost = n * fill + p.fees.fee(fill, n)
        all_in = entry_cost / n
        hold = n * p.pay[side] - entry_cost

        sale = np.clip(p.bid[side][i + 1:] - slip, 0.0, 1.0)
        bsize = p.bid_size[side][i + 1:]
        value = n * sale - fee_vec(p.fees, sale, n)                      # cash from selling n now
        ok = (sale > 0) & ~np.isnan(sale) & (np.isnan(bsize) | (bsize >= n - 1e-9))
        net = np.where(ok, value / n, -np.inf)
        base = dict(match_id=p.match_id, tier=p.tier, mode=entry, side=side, band=_band(ask),
                    entry_ts=p.ts[i], entry_phase=str(p.phase[i]), entry_ask=ask, contracts=n,
                    entry_cost=entry_cost, settle_ts=p.settle_ts, settle_side=p.pay[side], hold_pnl=hold)
        for kind, v in rules:
            target = (all_in + v if kind == ABSOLUTE else all_in * v if kind == RELATIVE
                      else v if kind == LEVEL and all_in < v            # level: take-profit only
                      else np.inf)                                      # hold: never sell
            hit = np.flatnonzero(net >= target - 1e-12)
            r = dict(base, x=kind, y=v, rule=rule_label(kind, v), locked=bool(hit.size), exit_ts=pd.NaT,
                     exit_phase=None, exit_bid=np.nan, exit_bid_age_s=np.nan, exit_value=np.nan, minutes_to_exit=np.nan, rule_pnl=hold)
            if hit.size:
                j = i + 1 + int(hit[0])
                r.update(exit_ts=p.ts[j], exit_phase=str(p.phase[j]), exit_bid=float(p.bid[side][j]),
                         exit_bid_age_s=float(p.bid_age[side][j]),
                         exit_value=float(value[j - i - 1]),
                         minutes_to_exit=(p.ts[j] - p.ts[i]).total_seconds() / 60,
                         rule_pnl=float(value[j - i - 1]) - entry_cost)
            r["pnl"] = r["rule_pnl"] - hold                              # delta (walk-forward's "pnl")
            rows.append(r)
    return rows


def simulate_cashout(paths: Sequence[CashPath], cfg: dict[str, Any], slippage: float,
                     entries: Sequence[str] = tuple(ENTRY_TYPES),
                     rules: Sequence[tuple[float, float]] = RULES) -> pd.DataFrame:
    """Every (match, entry type, side, rule) position at this slippage; `pnl` is delta vs hold."""
    contracts = float(cfg["backtest"]["contracts_per_entry"])
    rows = [r for p in paths for e in entries for r in _positions(p, e, contracts, slippage, rules)]
    df = pd.DataFrame(rows, columns=POSITION_COLUMNS)
    for c in ("entry_ts", "exit_ts", "settle_ts"):
        df[c] = pd.to_datetime(df[c], utc=True)
    return df


# ---- metrics -----------------------------------------------------------------

STALE_BID_S = 60.0
SUMMARY_COLUMNS = ["entries", "triggers", "trigger_rate", "delta_trig_pc", "ci_lo", "ci_hi", "delta_all_pc",
                   "sd_hold_pc", "sd_rule_pc", "p10_hold_pc", "p10_rule_pc", "frac_exit_live", "median_min_to_exit",
                   "frac_stale_bid"]


def _stats(g: pd.DataFrame, st: dict[str, Any]) -> dict[str, float]:
    n = g["contracts"].to_numpy(float)
    hold, rule, delta = (g[c].to_numpy(float) / n for c in ("hold_pnl", "rule_pnl", "pnl"))
    trig = g["locked"].to_numpy(bool)
    mean, lo, hi = cluster_mean_ci(delta[trig], g["match_id"].to_numpy()[trig], st["ci_level"], st["n_boot"],
                                   st["seed"])
    q = lambda a, f: float(f(a)) if a.size else np.nan                 # noqa: E731
    return dict(entries=len(g), triggers=int(trig.sum()), trigger_rate=q(trig, np.mean),
                delta_trig_pc=mean, ci_lo=lo, ci_hi=hi, delta_all_pc=q(delta, np.mean),
                sd_hold_pc=q(hold, np.std), sd_rule_pc=q(rule, np.std),
                p10_hold_pc=q(hold, lambda a: np.quantile(a, 0.1)), p10_rule_pc=q(rule, lambda a: np.quantile(a, 0.1)),
                frac_exit_live=float((g.loc[trig, "exit_phase"] == "live").mean()) if trig.any() else np.nan,
                median_min_to_exit=float(g.loc[trig, "minutes_to_exit"].median()) if trig.any() else np.nan,
                frac_stale_bid=_stale_share(g.loc[trig, "exit_bid_age_s"]))


def _stale_share(age: pd.Series) -> float:
    """Share of triggers (with a known age) whose exit bid was unchanged for > STALE_BID_S."""
    a = age.dropna().to_numpy(float)
    return float((a > STALE_BID_S).mean()) if a.size else np.nan


def summarize(positions: pd.DataFrame, by: Sequence[str] = ("mode", "rule"), st: dict[str, Any] | None = None
              ) -> pd.DataFrame:
    """Per-contract metrics (see SUMMARY_COLUMNS) per group; delta CI resamples whole matches."""
    st = st or wf_settings({})
    by = list(by)
    rows = [{**dict(zip(by, k if isinstance(k, tuple) else (k,))), **_stats(g, st)}
            for k, g in positions.groupby(by, sort=True)] if len(positions) else []
    return pd.DataFrame(rows, columns=[*by, *SUMMARY_COLUMNS])


def formed_book_coverage(paths: Sequence[CashPath], max_combined: float = E1R_MAX_COMBINED) -> dict[str, float]:
    """How many matches have a pre-match row at all, and how many ever show a formed pre-match book
    (ask_a + ask_b <= max_combined); plus the median combined ask at the first pre row (the E1 book)."""
    pre = [p for p in paths if (p.phase == "pre").any()]
    first = [float(p.ask["A"][i] + p.ask["B"][i]) for p in pre for i in [int(np.flatnonzero(p.phase == "pre")[0])]]
    formed = sum(bool(((p.phase == "pre") & (p.ask["A"] + p.ask["B"] <= max_combined + 1e-9)).any()) for p in pre)
    return dict(matches=len(paths), with_pre=len(pre), with_formed_pre=formed,
                frac_formed=formed / len(pre) if pre else np.nan,
                median_first_pre_combined=float(np.median(first)) if first else np.nan)


def identity_check(aligned: pd.DataFrame, tol: float = 1e-6) -> dict[str, float]:
    """bid(A) = 1 - ask(B) and bid(B) = 1 - ask(A) on rows with both values (pipeline check)."""
    gaps = []
    for b, a in (("bid_a", "ask_b"), ("bid_b", "ask_a")):
        d = (aligned[b] + aligned[a] - 1.0).abs().dropna()
        gaps.append(d.to_numpy(float))
    g = np.concatenate(gaps) if gaps else np.array([])
    return dict(rows=int(g.size), max_abs_gap=float(g.max()) if g.size else np.nan,
                share_within_tol=float((g <= tol).mean()) if g.size else np.nan)


# ---- set end vs mid-set (descriptive; addendum 2026-10-28) ---------------------

SET_WINDOW_S = 180.0


def tag_set_split(positions: pd.DataFrame, sets: pd.DataFrame | None, window_s: float = SET_WINDOW_S
                  ) -> pd.DataFrame:
    """Add `set_split` to triggered positions: "pre" (pre-match exit), "set_end" (live exit within
    window_s of a set-winner close_time of that match), "mid_set" (other live exits in matches that
    have set rows) or "no_set_data" (matches without set rows: Challenger, WTA 125, or none listed)."""
    out = positions.assign(set_split=pd.Series(None, index=positions.index, dtype=object))
    trig = out["locked"].astype(bool)
    out.loc[trig & (out["exit_phase"] != "live"), "set_split"] = "pre"
    live = out[trig & (out["exit_phase"] == "live")]
    if live.empty:
        return out
    if sets is None or sets.empty:
        out.loc[live.index, "set_split"] = "no_set_data"
        return out
    st = sets[["match_id", "close_time"]].dropna().assign(
        close_time=lambda d: pd.to_datetime(d["close_time"], utc=True).astype("datetime64[ns, UTC]"),
        match_id=lambda d: d["match_id"].astype(str))
    has = set(st["match_id"])
    left = live[["match_id", "exit_ts"]].astype({"match_id": str}).reset_index().sort_values("exit_ts")
    left["exit_ts"] = left["exit_ts"].astype("datetime64[ns, UTC]")
    near = pd.merge_asof(left, st.sort_values("close_time"), left_on="exit_ts", right_on="close_time",
                         by="match_id", direction="nearest")
    gap = (near["exit_ts"] - near["close_time"]).abs().dt.total_seconds()
    split = np.where(~near["match_id"].isin(has), "no_set_data",
                     np.where(gap <= window_s, "set_end", "mid_set"))
    out.loc[near["index"].to_numpy(), "set_split"] = split
    return out


# ---- DOG50: the owner's strategy (addendum 2026-10-28) --------------------------

DOG_RULE = "L=50c"
DOG_EDGES = (0.0, 0.10, 0.20, 0.30)
DOG_LABELS = ("<10c", "10-20c", "20-30c")
DOG_COLUMNS = ["entries", "triggers", "trigger_rate", "pnl_pc", "pnl_ci_lo", "pnl_ci_hi", "roi", "roi_ci_lo",
               "roi_ci_hi", "delta_pc", "delta_ci_lo", "delta_ci_hi", "sd_pc", "p10_pc", "frac_stale_bid"]
# exit-level curve for dogs (addendum 2, 2026-10-28): sell at net bid >= L, or never ("hold")
DOG_LEVELS = (0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.80, 0.90)
DOG_CURVE_RULES: tuple[tuple[float, float], ...] = (*((LEVEL, v) for v in DOG_LEVELS), (HOLD, 1.0))


def dog_positions(positions: pd.DataFrame, max_ask: float = 0.20, rule: str | None = DOG_RULE) -> pd.DataFrame:
    """DOG positions: E1/E2 sides bought below max_ask; `rule` keeps one exit rule (default the
    sell-at-50c DOG50 exit), None keeps every rule present (e.g. the exit-level curve)."""
    keep = positions["entry_ask"] < max_ask
    if rule is not None:
        keep &= positions["rule"] == rule
    d = positions[keep]
    band = np.searchsorted(DOG_EDGES, d["entry_ask"].to_numpy(float), side="right") - 1
    return d.assign(dog_band=[DOG_LABELS[i] for i in band])


def cluster_ratio_ci(num: np.ndarray, den: np.ndarray, groups: np.ndarray, level: float = 0.95,
                     n_boot: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """(sum num / sum den, lo, hi), percentile bootstrap over whole groups (e.g. ROI by match)."""
    num, den = np.asarray(num, float), np.asarray(den, float)
    if not num.size or den.sum() == 0:
        return (np.nan, np.nan, np.nan)
    codes, uniq = pd.factorize(pd.Series(groups))
    sn = np.bincount(codes, weights=num, minlength=len(uniq))
    sd = np.bincount(codes, weights=den, minlength=len(uniq))
    idx = np.random.default_rng(seed).integers(0, len(uniq), size=(n_boot, len(uniq)))
    boot = sn[idx].sum(axis=1) / sd[idx].sum(axis=1)
    a = (1 - level) / 2
    return float(num.sum() / den.sum()), float(np.quantile(boot, a)), float(np.quantile(boot, 1 - a))


def _dog_stats(g: pd.DataFrame, st: dict[str, Any]) -> dict[str, float]:
    n, mid = g["contracts"].to_numpy(float), g["match_id"].to_numpy()
    pnl, delta = g["rule_pnl"].to_numpy(float) / n, g["pnl"].to_numpy(float) / n
    ci = lambda v: cluster_mean_ci(v, mid, st["ci_level"], st["n_boot"], st["seed"])   # noqa: E731
    (pm, plo, phi), (dm, dlo, dhi) = ci(pnl), ci(delta)
    roi, rlo, rhi = cluster_ratio_ci(g["rule_pnl"].to_numpy(float), g["entry_cost"].to_numpy(float), mid,
                                     st["ci_level"], st["n_boot"], st["seed"])
    trig = g["locked"].astype(bool)
    return dict(entries=len(g), triggers=int(trig.sum()), trigger_rate=float(trig.mean()), pnl_pc=pm,
                sd_pc=float(pnl.std()), p10_pc=float(np.quantile(pnl, 0.1)),
                pnl_ci_lo=plo, pnl_ci_hi=phi, roi=roi, roi_ci_lo=rlo, roi_ci_hi=rhi, delta_pc=dm,
                delta_ci_lo=dlo, delta_ci_hi=dhi,
                frac_stale_bid=_stale_share(g.loc[trig, "exit_bid_age_s"]))


def dog_summary(dog: pd.DataFrame, by: Sequence[str], st: dict[str, Any] | None = None) -> pd.DataFrame:
    st = st or wf_settings({})
    by = list(by)
    rows = [{**dict(zip(by, k if isinstance(k, tuple) else (k,))), **_dog_stats(g, st)}
            for k, g in dog.groupby(by, sort=True)] if len(dog) else []
    return pd.DataFrame(rows, columns=[*by, *DOG_COLUMNS])


@dataclass
class FixedGate:
    folds: pd.DataFrame          # month x P&L per slippage
    gate: pd.DataFrame           # one row per slippage
    passed: bool
    reasons: list[str]


def fixed_rule_gate(by_slip: dict[float, pd.DataFrame], months: pd.Series, st: dict[str, Any]) -> FixedGate:
    """Gate a fixed rule (no selection, every month out of sample) on absolute P&L (`rule_pnl`)."""
    months = months.astype("period[M]")   # keeps .map() Period-typed under pandas 3
    tagged = {s: d.assign(period=d["match_id"].map(months)) for s, d in by_slip.items()}
    periods = sorted({p for d in tagged.values() for p in d["period"].dropna()})
    folds = pd.DataFrame({"month": [str(p) for p in periods]})
    rows = []
    for s, d in sorted(tagged.items()):
        per = d.groupby("period")["rule_pnl"].sum()
        folds[f"pnl_{slip_label(s)}"] = [float(per.get(p, 0.0)) for p in periods]
        folds[f"triggers_{slip_label(s)}"] = [int(d.loc[d["period"] == p, "locked"].sum()) for p in periods]
        positive = int((folds[f"pnl_{slip_label(s)}"] > 0).sum())
        rows.append(dict(slippage=s, months=len(periods), months_positive=positive, months_needed=math.ceil(st["pass_frac"] * len(periods)), entries=len(d),
                         triggers=int(d["locked"].sum()), pnl=float(d["rule_pnl"].sum()),
                         roi=float(d["rule_pnl"].sum() / d["entry_cost"].sum()) if len(d) else np.nan))
    gate = pd.DataFrame(rows)
    reasons = []
    if len(periods) < st["min_folds"]:
        reasons.append(f"only {len(periods)} month(s); need >= {st['min_folds']}")
    if len(gate):
        worst = gate.loc[gate["slippage"].idxmax()]
        if worst["months_positive"] < worst["months_needed"] or not len(periods):
            reasons.append(f"{int(worst['months_positive'])} of {len(periods)} months positive at "
                           f"{slip_label(worst['slippage'])}; need {int(worst['months_needed'])}")
        for r in gate.itertuples():
            if not r.pnl > 0:
                reasons.append(f"P&L ${r.pnl:.2f} not positive at {slip_label(r.slippage)}")
        if gate["triggers"].min() < st["min_oos_trades"]:
            reasons.append(f"{int(gate['triggers'].min())} triggers; need >= {st['min_oos_trades']}")
    else:
        reasons.append("no DOG positions")
    return FixedGate(folds, gate, not reasons, reasons)


def dogl_walk_forward(by_slip: dict[float, pd.DataFrame], months: pd.Series, st: dict[str, Any]) -> FixedGate:
    """DOGL gate (addendum 2): per test month, choose the exit level (or "hold") with the best total
    absolute P&L (`rule_pnl`) at the select slippage on earlier months, using only positions settled
    before the test month. A level needs >= min_train_trades training triggers; "hold" has no exit
    and is always eligible. The choice runs unchanged on the test month. PASS: >= min_folds folds,
    positive in >= ceil(pass_frac x folds) at the worst slippage, total > 0 at every slippage,
    >= min_oos_trades OOS positions (triggers are reported; "hold" has none)."""
    months = months.astype("period[M]")
    tagged = {s: d.assign(period=d["match_id"].map(months)) for s, d in by_slip.items()}
    sel = tagged[float(st["select_slippage"])]
    periods = sorted({p for d in tagged.values() for p in d["period"].dropna()})
    order = {r: i for i, r in enumerate(rule_label(k, v) for k, v in DOG_CURVE_RULES)}
    fold_rows, oos = [], {s: [] for s in tagged}
    for k, test in enumerate(periods):
        train_p = periods[:k][-int(st["train_months"]):] if st["train_months"] else periods[:k]
        if len(train_p) < st["min_train_months"]:
            continue
        start = test.start_time.tz_localize("UTC")
        tr = sel[sel["period"].isin(train_p) & (sel["settle_ts"] < start)]
        agg = tr.groupby("rule").agg(total=("rule_pnl", "sum"), triggers=("locked", "sum")).reset_index()
        agg = agg[(agg["rule"] == "hold") | (agg["triggers"] >= st["min_train_trades"])]
        row = dict(fold=len(fold_rows) + 1, test_month=str(test), rule=None, train_pnl=np.nan, train_triggers=0)
        if len(agg):
            agg = agg.assign(o=agg["rule"].map(order)).sort_values(["total", "o"], ascending=[False, True])
            best = agg.iloc[0]
            row.update(rule=best["rule"], train_pnl=float(best["total"]), train_triggers=int(best["triggers"]))
        for s, d in sorted(tagged.items()):
            te = d[(d["period"] == test) & (d["rule"] == row["rule"])] if row["rule"] else d.iloc[:0]
            row[f"pnl_{slip_label(s)}"] = float(te["rule_pnl"].sum())
            row[f"positions_{slip_label(s)}"] = len(te)
            row[f"triggers_{slip_label(s)}"] = int(te["locked"].sum())
            oos[s].append(te)
        fold_rows.append(row)
    folds = pd.DataFrame(fold_rows)
    n = len(folds)
    need = math.ceil(st["pass_frac"] * n) if n else 0
    rows = []
    for s in sorted(tagged):
        t = pd.concat(oos[s]) if oos[s] else tagged[s].iloc[:0]
        pm, plo, phi = cluster_mean_ci((t["rule_pnl"] / t["contracts"]).to_numpy(float), t["match_id"].to_numpy(),
                                       st["ci_level"], st["n_boot"], st["seed"])
        positive = int((folds[f"pnl_{slip_label(s)}"] > 0).sum()) if n else 0
        rows.append(dict(slippage=s, folds=n, folds_positive=positive, folds_needed=need, positions=len(t), triggers=int(t["locked"].sum()),
                         pnl=float(t["rule_pnl"].sum()), pnl_pc=pm, pnl_ci_lo=plo, pnl_ci_hi=phi,
                         roi=float(t["rule_pnl"].sum() / t["entry_cost"].sum()) if len(t) else np.nan))
    gate = pd.DataFrame(rows)
    reasons = []
    if n < st["min_folds"]:
        reasons.append(f"only {n} fold(s); need >= {st['min_folds']}")
    worst = gate.loc[gate["slippage"].idxmax()]
    if worst["folds_positive"] < need or n == 0:
        reasons.append(f"{int(worst['folds_positive'])} of {n} folds positive at {slip_label(worst['slippage'])}; "
                       f"need {need}")
    for r in gate.itertuples():
        if not r.pnl > 0:
            reasons.append(f"P&L ${r.pnl:.2f} not positive at {slip_label(r.slippage)}")
    if gate["positions"].min() < st["min_oos_trades"]:
        reasons.append(f"{int(gate['positions'].min())} OOS positions; need >= {st['min_oos_trades']}")
    return FixedGate(folds, gate, not reasons, reasons)


# ---- MISMATCH50: buy the much worse-ranked player, sell at 50c (addendum 3) --------

RATIO_EDGES = (1.0, 2.0, 4.0, 8.0, np.inf)
RATIO_LABELS = ("<2", "2-4", "4-8", ">=8")
MISMATCH_RATIO, MISMATCH_BEST = 4.0, 100
MISMATCH_COLUMNS = ["reach_eligible", "reach_rate", "implied_rate", "frac_under_20c"]


def load_ranks(path: Path | None) -> pd.DataFrame | None:
    """Pre-match rank table (match_id, rank_a, rank_b; NaN = unranked, with optional reason_a/reason_b);
    a proxy computed from results before each match."""
    if path is None or not path.exists():
        return None
    r = pd.read_parquet(path)
    r = r[[c for c in ("match_id", "rank_a", "rank_b", "reason_a", "reason_b") if c in r.columns]]
    return r.assign(match_id=r["match_id"].astype(str)).drop_duplicates("match_id", keep="last")


def ranked_positions(positions: pd.DataFrame, ranks: pd.DataFrame | None, rule: str = DOG_RULE) -> pd.DataFrame:
    """The worse-ranked player's positions under `rule` (sell at 50c by default), tagged with the rank
    ratio (worse / better), its bucket and the better player's rank. Ties and unranked matches drop."""
    cols = [*positions.columns, "better_rank", "rank_ratio", "ratio_bucket"]
    if ranks is None or ranks.empty or positions.empty:
        return pd.DataFrame(columns=cols)
    d = positions[positions["rule"] == rule].astype({"match_id": str}).merge(
        ranks[["match_id", "rank_a", "rank_b"]].dropna(), on="match_id")
    worse = np.where(d["rank_a"] > d["rank_b"], "A", np.where(d["rank_b"] > d["rank_a"], "B", ""))
    d = d[d["side"].to_numpy() == worse]
    better = np.minimum(d["rank_a"], d["rank_b"]).astype(float)
    ratio = np.maximum(d["rank_a"], d["rank_b"]).astype(float) / better
    bucket = np.searchsorted(RATIO_EDGES, ratio.to_numpy(), side="right") - 1
    return d.assign(better_rank=better, rank_ratio=ratio, ratio_bucket=[RATIO_LABELS[min(i, 3)] for i in bucket])[cols]


def mismatch_positions(ranked: pd.DataFrame, min_ratio: float = MISMATCH_RATIO,
                       max_better: float = MISMATCH_BEST) -> pd.DataFrame:
    """MISMATCH50 entries: worse rank >= min_ratio x the better one's, better ranked <= max_better."""
    return ranked[(ranked["rank_ratio"] >= min_ratio) & (ranked["better_rank"] <= max_better)]


UNRANKED_COLUMNS = [*POSITION_COLUMNS, "better_rank", "reason"]


def unranked_positions(positions: pd.DataFrame, ranks: pd.DataFrame | None, rule: str = DOG_RULE,
                       max_better: float = MISMATCH_BEST) -> pd.DataFrame:
    """MISMATCH50-U (addendum 4): matches where one player is ranked <= max_better and the other is
    unranked (NaN rank; treated as below the whole active pool, a labelled assumption). Keeps the
    unranked player's positions under `rule`, with `reason` from reason_a/reason_b ("unknown" if absent)."""
    if ranks is None or ranks.empty or positions.empty:
        return pd.DataFrame(columns=UNRANKED_COLUMNS)
    r = ranks.copy()
    for s in ("a", "b"):
        if f"reason_{s}" not in r.columns:
            r[f"reason_{s}"] = "unknown"
    ua, ub = r["rank_a"].isna(), r["rank_b"].isna()
    side = np.where(ua & ~ub & (r["rank_b"] <= max_better), "A",
                    np.where(ub & ~ua & (r["rank_a"] <= max_better), "B", ""))
    r = r.assign(u_side=side, better_rank=np.where(side == "A", r["rank_b"], r["rank_a"]),
                 reason=np.where(side == "A", r["reason_a"], r["reason_b"]))
    r = r[r["u_side"] != ""]
    d = positions[positions["rule"] == rule].astype({"match_id": str}).merge(
        r[["match_id", "u_side", "better_rank", "reason"]], on="match_id")
    d = d[d["side"] == d["u_side"]].assign(reason=lambda x: x["reason"].fillna("unknown").astype(str))
    return d[UNRANKED_COLUMNS]


PRICE_COLUMNS = ["entries", "ask_p10", "ask_p25", "ask_p50", "ask_p75", "ask_p90", "frac_under_20c", "frac_over_50c"]


def price_distribution(d: pd.DataFrame, by: Sequence[str]) -> pd.DataFrame:
    """Entry-ask distribution per group (does the market price these players as heavy dogs?)."""
    by = list(by)
    rows = []
    for k, g in (d.groupby(by, sort=True) if len(d) else []):
        a = g["entry_ask"].astype(float)
        rows.append({**dict(zip(by, k if isinstance(k, tuple) else (k,))), "entries": len(g),
                     **{f"ask_p{q}": float(a.quantile(q / 100)) for q in (10, 25, 50, 75, 90)},
                     "frac_under_20c": float((a < 0.20).mean()), "frac_over_50c": float((a > 0.50).mean())})
    return pd.DataFrame(rows, columns=[*by, *PRICE_COLUMNS])


def target_bid(fm: FeeModel, n: float, level: float = 0.50) -> float:
    """Smallest whole-cent bid whose net (bid - fee / n) clears `level`."""
    grid = np.round(np.arange(level, 1.0001, 0.01), 2)
    ok = grid - fee_vec(fm, grid, n) / n >= level - 1e-12
    return float(grid[np.argmax(ok)]) if ok.any() else np.nan


def _reach_stats(g: pd.DataFrame, slip: float, fm: FeeModel) -> dict[str, float]:
    """Reach-50 rate vs the price-implied rate (martingale: P(reach b*) = p0 / b*, p0 = entry ask) over
    entries bought below 50c all-in (the only ones the level rule can sell)."""
    elig = g[g["entry_cost"] / g["contracts"] < 0.50]
    if elig.empty:
        return dict(reach_eligible=0, reach_rate=np.nan, implied_rate=np.nan,
                    frac_under_20c=float((g["entry_ask"] < 0.20).mean()) if len(g) else np.nan)
    tb = np.array([target_bid(fm, n) for n in elig["contracts"]]) + slip
    implied = np.minimum(elig["entry_ask"].to_numpy(float) / tb, 1.0)
    return dict(reach_eligible=len(elig), reach_rate=float(elig["locked"].mean()), implied_rate=float(implied.mean()),
                frac_under_20c=float((g["entry_ask"] < 0.20).mean()))


def mismatch_summary(d: pd.DataFrame, by: Sequence[str], fm: FeeModel, st: dict[str, Any] | None = None
                     ) -> pd.DataFrame:
    """DOG_COLUMNS (P&L, ROI, delta, SD, P10, CIs) plus the reach-50 test per group (needs `slippage` in d)."""
    st = st or wf_settings({})
    by = list(by)
    rows = [{**dict(zip(by, k if isinstance(k, tuple) else (k,))), **_dog_stats(g, st),
             **_reach_stats(g, float(g["slippage"].iloc[0]), fm)}
            for k, g in d.groupby(by, sort=True)] if len(d) else []
    return pd.DataFrame(rows, columns=[*by, *DOG_COLUMNS, *MISMATCH_COLUMNS])


def mismatch_md(mm: dict[str, pd.DataFrame], gate: FixedGate) -> list[str]:
    fmt = lambda df: md_table(df.round(4))                               # noqa: E731
    verdict = "PASS" if gate.passed else "FAIL: " + "; ".join(gate.reasons)
    return ["## MISMATCH50: buy the worse-ranked player (rank >= 4x, better <= 100), sell at net bid >= 50c",
            "Rank = pre-match Elo rank (a PROXY computed from earlier results, not the official ranking). "
            "reach_rate vs implied_rate (entry ask / bid needed for a 50c net) is the test of 'goes to 50-50 often'; "
            "frac_under_20c = overlap with DOG50.", "",
            f"- Gate (fixed rule, absolute P&L, monthly): **{verdict}**", "",
            fmt(gate.gate.assign(slippage=gate.gate["slippage"].map(slip_label))), "", fmt(gate.folds), "",
            "Overall, by entry type and by tour level:", "", fmt(mm["mm50"]), "", fmt(mm["mm50_mode"]), "",
            fmt(mm["mm50_tier"]), "",
            "All worse-ranked players (any ratio, any better rank), by rank-ratio bucket and tour level:", "",
            fmt(mm["ratio_bucket"]), "", fmt(mm["ratio_tier"]), ""]


def unranked_md(u: dict[str, pd.DataFrame], gate: FixedGate) -> list[str]:
    fmt = lambda df: md_table(df.round(4))                               # noqa: E731
    verdict = "PASS" if gate.passed else "FAIL: " + "; ".join(gate.reasons)
    return ["## MISMATCH50-U: buy the UNRANKED player vs a player ranked <= 100, sell at net bid >= 50c",
            "ASSUMPTION: an unranked player (rank proxy missing) is treated as below the whole active pool. "
            "Reported apart from MISMATCH50. Reasons: too few rated matches / inactive 365 d / name not matched.", "",
            f"- Gate (fixed rule, absolute P&L, monthly): **{verdict}**", "",
            fmt(gate.gate.assign(slippage=gate.gate["slippage"].map(slip_label))), "", fmt(gate.folds), "",
            "Overall, by unranked reason, by entry type and by tour level:", "", fmt(u["u50"]), "",
            fmt(u["u50_reason"]), "", fmt(u["u50_mode"]), "", fmt(u["u50_tier"]), "",
            "Entry-price distribution by unranked reason (0c; are they priced as heavy dogs?):", "",
            fmt(u["u50_price"]), ""]


# ---- walk-forward gate ---------------------------------------------------------

def match_months(paths: Sequence[CashPath]) -> pd.Series:
    return pd.Series({p.match_id: p.ts[0].tz_convert("UTC").tz_localize(None).to_period("M") for p in paths},
                     dtype=object)


def walk_forward_cashout(by_slip: dict[float, pd.DataFrame], months: pd.Series, entry: str,
                         cfg: dict[str, Any]) -> WalkForward:
    """Gate per entry type: rule (kind, value) chosen on earlier months by total delta at the select
    slippage among rules with >= min_train_trades training triggers; OOS 'trades' are triggers."""
    st = wf_settings(cfg)
    trig = {s: t[(t["mode"] == entry) & t["locked"]] for s, t in by_slip.items()}
    return evaluate(trig, months, [(entry, k, v) for k, v in RULES], st)


# ---- CLI -----------------------------------------------------------------------

def report_md(data_dir, aligned, ident, summary, bands, gates: dict[str, WalkForward], set_split,
              dog: dict[str, pd.DataFrame], dog_gate: FixedGate, dogl: FixedGate) -> str:
    fmt = lambda df: md_table(df.round(4))                               # noqa: E731
    lines = ["# Cash-out study: run summary", "",
             f"Data `{data_dir}`; {aligned['match_id'].nunique()} matches, {len(aligned)} aligned observations. "
             "Pre-registration: docs/edge_cashout.md. Per-contract values in dollars; delta = cash-out - hold.", "",
             "## Identity check: bid(A) = 1 - ask(B)",
             f"- rows {ident['rows']}, max |gap| {ident['max_abs_gap']:.2g}, "
             f"share within 1e-6: {ident['share_within_tol']:.4%}", "",
             "## By entry type and rule",
             f"frac_stale_bid = share of triggers whose exit bid had not changed for > {STALE_BID_S:g} s "
             "(carried candle; less reliable).", "", fmt(summary), "",
             "## By entry band (rule x band, 1c slippage)", "", fmt(bands), ""]
    for entry, wf in gates.items():
        verdict = "PASS" if wf.passed else "FAIL: " + "; ".join(wf.reasons)
        lines += [f"## Walk-forward gate, {entry}", "", f"- Verdict: **{verdict}** (OOS trades = triggers)", "",
                  fmt(wf.gate.assign(slippage=wf.gate["slippage"].map(slip_label))), "",
                  fmt(wf.folds), ""]
    lines += ["## Set end vs mid-set (live exits, 1c; descriptive only)",
              f"Set end = within {SET_WINDOW_S / 60:g} min of a Kalshi set-winner close_time (ATP/WTA, sets "
              "before the decider); no_set_data = matches without set rows.", "", fmt(set_split), ""]
    verdict = "PASS" if dog_gate.passed else "FAIL: " + "; ".join(dog_gate.reasons)
    lines += ["## DOG50: dogs < 20c (E1 + E2), sell at net bid >= 50c, else hold", "",
              f"- Gate (fixed rule, absolute P&L, monthly): **{verdict}**", "",
              fmt(dog_gate.gate.assign(slippage=dog_gate.gate["slippage"].map(slip_label))), "",
              fmt(dog_gate.folds), "", "Overall, by entry type and by band:", "",
              fmt(dog["dog50"]), "", fmt(dog["dog50_mode"]), "", fmt(dog["dog50_band"]), "",
              "## DOG30 (dogs < 30c; descriptive only)", "", fmt(dog["dog30_band"]), ""]
    verdict = "PASS" if dogl.passed else "FAIL: " + "; ".join(dogl.reasons)
    lines += ["## Dog exit-level curve: cost and risk of each exit level (addendum 2)",
              "Dogs bought < 20c / < 30c (E1 + E2 sides); sell at net bid >= L, else hold. pnl_pc and ROI are "
              "absolute; delta_pc = vs hold; sd_pc / p10_pc = spread and worst decile of P&L per contract.", "",
              "Dogs < 20c:", "", fmt(dog["curve20"]), "", "Dogs < 30c:", "", fmt(dog["curve30"]), "",
              "## DOGL gate: exit level chosen on earlier months (dogs < 20c)", "",
              f"- Verdict: **{verdict}**", "", fmt(dogl.gate.assign(slippage=dogl.gate["slippage"].map(slip_label))),
              "", fmt(dogl.folds), ""]
    return "\n".join(lines)


def e1r_md(t: dict[str, pd.DataFrame], cov: dict[str, float]) -> list[str]:
    fmt = lambda df: md_table(df.round(4))                               # noqa: E731
    lines = ["## E1r robustness check (addendum 5: POST HOC, descriptive only, never gated)",
             f"E1 buys at the first pre-match row, which is usually the listing-time placeholder book (median "
             f"ask_a + ask_b there: ${cov['median_first_pre_combined']:.2f}), so E1 results above are an artefact. "
             f"E1r = the first pre-match row with ask_a + ask_b <= ${E1R_MAX_COMBINED:.2f}. Matches with a pre-match "
             f"row: {cov['with_pre']}; with a formed pre-match book: {cov['with_formed_pre']} "
             f"({cov['frac_formed']:.1%}). Gate verdicts above are unchanged.", "",
             "DOG50 at E1r:", "", fmt(t["e1r_dog50"]), "", "All rules at E1r:", "", fmt(t["e1r_summary"]), ""]
    for k, title in (("e1r_mm50", "MISMATCH50 at E1r"), ("e1r_u50", "MISMATCH50-U at E1r")):
        if k in t:
            lines += [f"{title}:", "", fmt(t[k]), ""]
    return lines


def load_sets(path: Path | None) -> pd.DataFrame | None:
    return pd.read_parquet(path) if path is not None and path.exists() else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cash-out (take-profit) study, docs/edge_cashout.md")
    ap.add_argument("--data", default="data/processed/kalshi", type=Path)
    ap.add_argument("--sets", default=None, type=Path, help="set-winner table (default <data>/sets.parquet)")
    ap.add_argument("--ranks", default=None, type=Path,
                    help="pre-match rank proxy (match_id, rank_a, rank_b) for MISMATCH50; skipped if absent")
    ap.add_argument("--out", default="reports", type=Path)
    ap.add_argument("--config", default=None)
    args = ap.parse_args(argv)

    loaded = load(args.data)
    if loaded is None:
        print(f"No input in {args.data}: need non-empty matches.parquet and quotes.parquet. Nothing to do.",
              file=sys.stderr)
        return 0
    matches, quotes = loaded
    cfg = load_config(args.config)
    st = wf_settings(cfg)
    aligned = align(quotes, matches, staleness_s(cfg))
    paths = cash_paths(aligned, matches, cfg)
    by_slip = {s: simulate_cashout(paths, cfg, s).assign(slippage=s) for s in SLIPPAGES}
    allpos = pd.concat(by_slip.values(), ignore_index=True)
    summary = summarize(allpos, ("mode", "rule", "slippage"), st)
    bands = summarize(by_slip[0.01], ("mode", "rule", "band"), st)
    phases = summarize(allpos[allpos["locked"]], ("mode", "rule", "slippage", "exit_phase"), st)
    months = match_months(paths)
    gates = {e: walk_forward_cashout(by_slip, months, e, cfg) for e in ENTRY_TYPES}

    tagged = tag_set_split(by_slip[0.01], load_sets(args.sets or args.data / "sets.parquet"))
    live = tagged[tagged["set_split"].isin(["set_end", "mid_set", "no_set_data"])]
    set_split = summarize(live, ("mode", "rule", "set_split"), st)

    dog_by = {s: dog_positions(d) for s, d in by_slip.items()}
    dog_all = pd.concat(dog_by.values(), ignore_index=True)
    dog30 = pd.concat([dog_positions(d, 0.30) for d in by_slip.values()], ignore_index=True)
    dog = {"dog50": dog_summary(dog_all, ("slippage",), st),
           "dog50_mode": dog_summary(dog_all, ("slippage", "mode"), st),
           "dog50_band": dog_summary(dog_all, ("slippage", "dog_band"), st),
           "dog30_band": dog_summary(dog30, ("slippage", "dog_band"), st)}
    dog_gate = fixed_rule_gate(dog_by, months, st)
    curve = {s: simulate_cashout(paths, cfg, s, rules=DOG_CURVE_RULES).assign(slippage=s) for s in SLIPPAGES}
    curve20 = {s: dog_positions(d, 0.20, rule=None) for s, d in curve.items()}
    for cap, src in (("20", curve20), ("30", {s: dog_positions(d, 0.30, rule=None) for s, d in curve.items()})):
        dog[f"curve{cap}"] = dog_summary(pd.concat(src.values(), ignore_index=True), ("slippage", "rule"), st)
    dogl = dogl_walk_forward(curve20, months, st)

    ranks, mm_tables = load_ranks(args.ranks), []
    if ranks is not None:
        fm = kalshi_fees(cfg)
        ranked = {s: ranked_positions(d, ranks) for s, d in by_slip.items()}
        mm_by = {s: mismatch_positions(d) for s, d in ranked.items()}
        mm_all, rk_all = (pd.concat(x.values(), ignore_index=True) for x in (mm_by, ranked))
        mm = {"mm50": mismatch_summary(mm_all, ("slippage",), fm, st),
              "mm50_mode": mismatch_summary(mm_all, ("slippage", "mode"), fm, st),
              "mm50_tier": mismatch_summary(mm_all, ("slippage", "tier"), fm, st),
              "ratio_bucket": mismatch_summary(rk_all, ("slippage", "ratio_bucket"), fm, st),
              "ratio_tier": mismatch_summary(rk_all, ("slippage", "tier", "ratio_bucket"), fm, st)}
        mm_gate = fixed_rule_gate(mm_by, months, st)
        u_by = {s: unranked_positions(d, ranks).assign(slippage=s) for s, d in by_slip.items()}
        u_all = pd.concat(u_by.values(), ignore_index=True)
        u = {"u50": mismatch_summary(u_all, ("slippage",), fm, st),
             "u50_reason": mismatch_summary(u_all, ("slippage", "reason"), fm, st),
             "u50_mode": mismatch_summary(u_all, ("slippage", "mode"), fm, st),
             "u50_tier": mismatch_summary(u_all, ("slippage", "tier"), fm, st),
             "u50_price": price_distribution(u_by[0.0], ("reason",))}
        u_gate = fixed_rule_gate(u_by, months, st)
        mm_tables = [*((f"cashout_{k}", v) for k, v in mm.items()), ("cashout_mm50_gate", mm_gate.gate),
                     ("cashout_mm50_months", mm_gate.folds), *((f"cashout_{k}", v) for k, v in u.items()),
                     ("cashout_u50_gate", u_gate.gate), ("cashout_u50_months", u_gate.folds)]

    args.out.mkdir(parents=True, exist_ok=True)
    for name, df in [*mm_tables, ("cashout_summary", summary), ("cashout_bands", bands), ("cashout_exit_phase", phases),
                     ("cashout_set_split", set_split),
                     *((f"cashout_{k}", v) for k, v in dog.items()), ("cashout_dog50_gate", dog_gate.gate),
                     ("cashout_dog50_months", dog_gate.folds), ("cashout_dogl_gate", dogl.gate),
                     ("cashout_dogl_folds", dogl.folds)]:
        df.to_csv(args.out / f"{name}.csv", index=False)
    for e, wf in gates.items():
        wf.folds.to_csv(args.out / f"cashout_wf_folds_{e}.csv", index=False)
        wf.gate.to_csv(args.out / f"cashout_wf_gate_{e}.csv", index=False)
    # addendum 5: E1r robustness check (post hoc, descriptive only, never gated)
    cov = formed_book_coverage(paths)
    e1r = {s: simulate_cashout(paths, cfg, s, entries=(E1R,)).assign(slippage=s) for s in SLIPPAGES}
    e1r_all = pd.concat(e1r.values(), ignore_index=True)
    e1r_tables = {"e1r_dog50": dog_summary(dog_positions(e1r_all), ("slippage",), st),
                  "e1r_summary": summarize(e1r_all, ("rule", "slippage"), st)}
    if ranks is not None:
        e1r_tables["e1r_mm50"] = mismatch_summary(mismatch_positions(ranked_positions(e1r_all, ranks)),
                                                  ("slippage",), fm, st)
        e1r_tables["e1r_u50"] = mismatch_summary(
            pd.concat([unranked_positions(d, ranks).assign(slippage=s) for s, d in e1r.items()], ignore_index=True),
            ("slippage",), fm, st)
    for k, v in e1r_tables.items():
        v.to_csv(args.out / f"cashout_{k}.csv", index=False)
    pd.DataFrame([cov]).to_csv(args.out / "cashout_e1r_coverage.csv", index=False)

    md = report_md(args.data, aligned, identity_check(aligned), summary, bands, gates, set_split, dog, dog_gate,
                   dogl)
    if ranks is not None:
        md += "\n" + "\n".join([*mismatch_md(mm, mm_gate), *unranked_md(u, u_gate)])
    md += "\n" + "\n".join(e1r_md(e1r_tables, cov))
    (args.out / "cashout_summary.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
