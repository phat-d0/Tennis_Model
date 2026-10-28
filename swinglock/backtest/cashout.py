"""Cash-out (take-profit) study, pre-registered in docs/edge_cashout.md.

For selection-neutral entries (E1: both players at a match's first `pre` observation; E2: both at
its first `live` one), compare selling at the bid when a take-profit rule triggers with holding the
same position to settlement:

    delta = P&L(sell at the bid on trigger) - P&L(hold)        (0 when the rule never triggers)

Entry: ask + slippage, taker fee rounded up per order, `backtest.contracts_per_entry` contracts
(capped by ask depth when known). Exit: the first row strictly after the entry where the net bid
per contract, (bid - slippage) - fee / n, is >= entry all-in + T (absolute rules) or >= k x entry
all-in (relative rules), with bid size >= n when known. Hold: n x settle_side - entry cost.

No lookahead: an exit uses only its own aligned row (quotes at or before it); settlement is used
only for the hold leg.

On Kalshi's paired markets bid(A) = 1 - ask(B) by construction (see `identity_check`) and the fee is
symmetric, so a take-profit at T is the swing lock at Y = 1 - T.

    python -m swinglock.backtest.cashout --data data/processed/kalshi --out reports/
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from ..config import load_config
from ..fees import _EPS, FeeModel
from ..locks import SIDES
from .align import align, match_fees, staleness_s
from .run import load, md_table
from .swing import settlement
from .walkforward import WalkForward, cluster_mean_ci, evaluate, slip_label, wf_settings

ENTRY_TYPES = {"E1": "pre", "E2": "live"}
ABS_T = (0.03, 0.05, 0.10, 0.15, 0.20, 0.30)
REL_K = (1.5, 2.0, 3.0)
ABSOLUTE, RELATIVE = 0.0, 1.0           # rule kind, stored in the walk-forward's "x" column
RULES: tuple[tuple[float, float], ...] = (*((ABSOLUTE, t) for t in ABS_T), *((RELATIVE, k) for k in REL_K))
BAND_EDGES = (0.0, 0.20, 0.40, 0.60, 0.80, 1.0 + 1e-9)
BAND_LABELS = ("<20c", "20-40c", "40-60c", "60-80c", ">=80c")
SLIPPAGES = (0.0, 0.01)

POSITION_COLUMNS = ["match_id", "tier", "mode", "x", "y", "rule", "side", "band", "entry_ts", "entry_phase",
                    "entry_ask", "contracts", "entry_cost", "settle_ts", "settle_side", "hold_pnl", "locked",
                    "exit_ts", "exit_phase", "exit_bid", "exit_value", "minutes_to_exit", "rule_pnl", "pnl"]


def rule_label(kind: float, value: float) -> str:
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
                            col("ask"), col("size"), col("bid"), col("bsize")))
    return out


def _band(ask: float) -> str:
    return BAND_LABELS[int(np.searchsorted(BAND_EDGES, ask, side="right")) - 1]


def _positions(p: CashPath, entry: str, contracts: float, slip: float) -> list[dict]:
    """Rows (one per side x rule) for one match and entry type; [] if there is no such entry."""
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
        for kind, v in RULES:
            target = all_in + v if kind == ABSOLUTE else all_in * v
            hit = np.flatnonzero(net >= target - 1e-12)
            r = dict(base, x=kind, y=v, rule=rule_label(kind, v), locked=bool(hit.size), exit_ts=pd.NaT,
                     exit_phase=None, exit_bid=np.nan, exit_value=np.nan, minutes_to_exit=np.nan, rule_pnl=hold)
            if hit.size:
                j = i + 1 + int(hit[0])
                r.update(exit_ts=p.ts[j], exit_phase=str(p.phase[j]), exit_bid=float(p.bid[side][j]),
                         exit_value=float(value[j - i - 1]),
                         minutes_to_exit=(p.ts[j] - p.ts[i]).total_seconds() / 60,
                         rule_pnl=float(value[j - i - 1]) - entry_cost)
            r["pnl"] = r["rule_pnl"] - hold                              # delta (walk-forward's "pnl")
            rows.append(r)
    return rows


def simulate_cashout(paths: Sequence[CashPath], cfg: dict[str, Any], slippage: float,
                     entries: Sequence[str] = tuple(ENTRY_TYPES)) -> pd.DataFrame:
    """Every (match, entry type, side, rule) position at this slippage; `pnl` is delta vs hold."""
    contracts = float(cfg["backtest"]["contracts_per_entry"])
    rows = [r for p in paths for e in entries for r in _positions(p, e, contracts, slippage)]
    df = pd.DataFrame(rows, columns=POSITION_COLUMNS)
    for c in ("entry_ts", "exit_ts", "settle_ts"):
        df[c] = pd.to_datetime(df[c], utc=True)
    return df


# ---- metrics -----------------------------------------------------------------

SUMMARY_COLUMNS = ["entries", "triggers", "trigger_rate", "delta_trig_pc", "ci_lo", "ci_hi", "delta_all_pc",
                   "sd_hold_pc", "sd_rule_pc", "p10_hold_pc", "p10_rule_pc", "frac_exit_live", "median_min_to_exit"]


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
                median_min_to_exit=float(g.loc[trig, "minutes_to_exit"].median()) if trig.any() else np.nan)


def summarize(positions: pd.DataFrame, by: Sequence[str] = ("mode", "rule"), st: dict[str, Any] | None = None
              ) -> pd.DataFrame:
    """Per-contract metrics (see SUMMARY_COLUMNS) per group; delta CI resamples whole matches."""
    st = st or wf_settings({})
    by = list(by)
    rows = [{**dict(zip(by, k if isinstance(k, tuple) else (k,))), **_stats(g, st)}
            for k, g in positions.groupby(by, sort=True)] if len(positions) else []
    return pd.DataFrame(rows, columns=[*by, *SUMMARY_COLUMNS])


def identity_check(aligned: pd.DataFrame, tol: float = 1e-6) -> dict[str, float]:
    """bid(A) = 1 - ask(B) and bid(B) = 1 - ask(A) on rows with both values (pipeline check)."""
    gaps = []
    for b, a in (("bid_a", "ask_b"), ("bid_b", "ask_a")):
        d = (aligned[b] + aligned[a] - 1.0).abs().dropna()
        gaps.append(d.to_numpy(float))
    g = np.concatenate(gaps) if gaps else np.array([])
    return dict(rows=int(g.size), max_abs_gap=float(g.max()) if g.size else np.nan,
                share_within_tol=float((g <= tol).mean()) if g.size else np.nan)


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

def report_md(data_dir, aligned, ident, summary, bands, gates: dict[str, WalkForward]) -> str:
    fmt = lambda df: md_table(df.round(4))                               # noqa: E731
    lines = ["# Cash-out study: run summary", "",
             f"Data `{data_dir}`; {aligned['match_id'].nunique()} matches, {len(aligned)} aligned observations. "
             "Pre-registration: docs/edge_cashout.md. Per-contract values in dollars; delta = cash-out - hold.", "",
             "## Identity check: bid(A) = 1 - ask(B)",
             f"- rows {ident['rows']}, max |gap| {ident['max_abs_gap']:.2g}, "
             f"share within 1e-6: {ident['share_within_tol']:.4%}", "",
             "## By entry type and rule", "", fmt(summary), "",
             "## By entry band (rule x band, 1c slippage)", "", fmt(bands), ""]
    for entry, wf in gates.items():
        verdict = "PASS" if wf.passed else "FAIL: " + "; ".join(wf.reasons)
        lines += [f"## Walk-forward gate, {entry}", "", f"- Verdict: **{verdict}** (OOS trades = triggers)", "",
                  fmt(wf.gate.assign(slippage=wf.gate["slippage"].map(slip_label))), "",
                  fmt(wf.folds), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cash-out (take-profit) study, docs/edge_cashout.md")
    ap.add_argument("--data", default="data/processed/kalshi", type=Path)
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
    aligned = align(quotes, matches, staleness_s(cfg))
    paths = cash_paths(aligned, matches, cfg)
    by_slip = {s: simulate_cashout(paths, cfg, s).assign(slippage=s) for s in SLIPPAGES}
    allpos = pd.concat(by_slip.values(), ignore_index=True)
    summary = summarize(allpos, ("mode", "rule", "slippage"))
    bands = summarize(by_slip[0.01], ("mode", "rule", "band"))
    phases = summarize(allpos[allpos["locked"]], ("mode", "rule", "slippage", "exit_phase"))
    months = match_months(paths)
    gates = {e: walk_forward_cashout(by_slip, months, e, cfg) for e in ENTRY_TYPES}

    args.out.mkdir(parents=True, exist_ok=True)
    for name, df in [("cashout_summary", summary), ("cashout_bands", bands), ("cashout_exit_phase", phases),
                     ("cashout_positions", allpos)]:
        df.to_csv(args.out / f"{name}.csv", index=False)
    for e, wf in gates.items():
        wf.folds.to_csv(args.out / f"cashout_wf_folds_{e}.csv", index=False)
        wf.gate.to_csv(args.out / f"cashout_wf_gate_{e}.csv", index=False)
    md = report_md(args.data, aligned, identity_check(aligned), summary, bands, gates)
    (args.out / "cashout_summary.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
