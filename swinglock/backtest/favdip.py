"""Fallen-favourite study, pre-registered in docs/edge_favdip.md.

The original favourite = the player with the higher ask at a match's last pre-match row with a formed
book (ask_a + ask_b <= $1.05; placeholder listing books are never used). Banded by that ask:

    START   buy the favourite at that row's ask, hold to settlement (baseline, not gated)
    DIP50   buy it at the first live row with a formed book where its ask <= 0.50, hold (gated per band)
    DIP45 / DIP40   the same at deeper dips (descriptive)

Fills: ask + slippage, taker fee rounded up per order, `backtest.contracts_per_entry` contracts capped by
ask depth when known. P&L = contracts x settlement (1/0 or fair price) - entry cost. No lookahead: the
favourite and each entry use only their own aligned row; settlement is used only for P&L.

    python -m swinglock.backtest.favdip --data data/processed/kalshi --out reports/

Outputs are aggregates only (no per-position rows): Kalshi data stays private.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from ..config import load_config
from ..locks import SIDES
from .align import align, staleness_s
from .cashout import (E1R_MAX_COMBINED, SLIPPAGES, CashPath, FixedGate, cash_paths, cluster_ratio_ci,
                      fixed_rule_gate, load_sets, match_months)
from .run import load, md_table
from .walkforward import cluster_mean_ci, slip_label, wf_settings

FORMED_MAX = E1R_MAX_COMBINED                       # ask_a + ask_b <= $1.05 = a formed book
FAV_BANDS = (("50-60", 0.50, 0.60, False), ("60-80", 0.60, 0.80, False), ("80-97", 0.80, 0.97, True))
GATED_BANDS = ("60-80", "80-97")                    # 50-60 is context only
DIPS = (("DIP50", 0.50), ("DIP45", 0.45), ("DIP40", 0.40))
GATED_RULE = "DIP50"

POSITION_COLUMNS = ["match_id", "tier", "band", "rule", "side", "fav_ask", "entry_ts", "entry_ask", "contracts",
                    "entry_cost", "settle_side", "rule_pnl", "locked", "minutes_from_start"]
STATS_COLUMNS = ["entries", "win_rate", "mean_ask", "mean_all_in", "roi", "roi_ci_lo", "roi_ci_hi", "pnl_pc",
                 "pnl_ci_lo", "pnl_ci_hi", "sd_pc"]


def fav_band(ask: float) -> str | None:
    for label, lo, hi, closed in FAV_BANDS:
        if lo - 1e-9 <= ask < hi or (closed and abs(ask - hi) <= 1e-9):
            return label
    return None


def favourite(p: CashPath) -> tuple[int, str] | None:
    """(row, side) of the original favourite: the higher ask at the last formed pre-match row."""
    idx = np.flatnonzero((p.phase == "pre") & (p.ask["A"] + p.ask["B"] <= FORMED_MAX + 1e-9))
    if not idx.size:
        return None
    i = int(idx[-1])
    a, b = float(p.ask["A"][i]), float(p.ask["B"][i])
    if a == b:
        return None
    return i, ("A" if a > b else "B")


def _entry(p: CashPath, i: int, side: str, contracts: float, slip: float) -> dict | None:
    ask, size = float(p.ask[side][i]), p.ask_size[side][i]
    if not 0 < ask < 1 or (not np.isnan(size) and size <= 0):
        return None
    n = contracts if np.isnan(size) else min(contracts, float(size))
    fill = min(ask + slip, 1.0)
    cost = n * fill + p.fees.fee(fill, n)
    return dict(entry_ts=p.ts[i], entry_ask=ask, contracts=n, entry_cost=cost, settle_side=p.pay[side],
                rule_pnl=n * p.pay[side] - cost, locked=True)


def _positions(p: CashPath, contracts: float, slip: float, start: pd.Timestamp | None,
               dips: Sequence[tuple[str, float]] = DIPS) -> list[dict]:
    fav = favourite(p)
    if fav is None:
        return []
    i, side = fav
    fav_ask = float(p.ask[side][i])
    band = fav_band(fav_ask)
    if band is None:
        return []
    base = dict(match_id=p.match_id, tier=p.tier, band=band, side=side, fav_ask=fav_ask)
    t0 = start if start is not None and not pd.isna(start) else None
    mins = lambda ts: (ts - t0).total_seconds() / 60 if t0 is not None else np.nan   # noqa: E731
    rows = []
    if (e := _entry(p, i, side, contracts, slip)) is not None:
        rows.append(dict(base, rule="START", **e, minutes_from_start=mins(e["entry_ts"])))
    live_formed = (p.phase == "live") & (p.ask["A"] + p.ask["B"] <= FORMED_MAX + 1e-9)
    for rule, level in dips:
        for j in np.flatnonzero(live_formed & (p.ask[side] <= level + 1e-9)):
            if (e := _entry(p, int(j), side, contracts, slip)) is not None:
                rows.append(dict(base, rule=rule, **e, minutes_from_start=mins(e["entry_ts"])))
                break
    return rows


def simulate_favdip(paths: Sequence[CashPath], cfg: dict[str, Any], slippage: float,
                    starts: dict[str, pd.Timestamp] | None = None) -> pd.DataFrame:
    """START and DIP positions on each match's original favourite at this slippage."""
    contracts = float(cfg["backtest"]["contracts_per_entry"])
    starts = starts or {}
    rows = [r for p in paths for r in _positions(p, contracts, slippage, starts.get(p.match_id))]
    df = pd.DataFrame(rows, columns=POSITION_COLUMNS)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    return df.assign(slippage=slippage)


def favourites(paths: Sequence[CashPath]) -> pd.DataFrame:
    """One row per match with a banded original favourite (the denominator of the dip shares)."""
    rows = []
    for p in paths:
        if (fav := favourite(p)) is not None and (band := fav_band(float(p.ask[fav[1]][fav[0]]))) is not None:
            rows.append(dict(match_id=p.match_id, tier=p.tier, band=band))
    return pd.DataFrame(rows, columns=["match_id", "tier", "band"])


# ---- metrics -----------------------------------------------------------------

def _stats(g: pd.DataFrame, st: dict[str, Any]) -> dict[str, float]:
    n, mid = g["contracts"].to_numpy(float), g["match_id"].to_numpy()
    pnl = g["rule_pnl"].to_numpy(float) / n
    pm, plo, phi = cluster_mean_ci(pnl, mid, st["ci_level"], st["n_boot"], st["seed"])
    roi, rlo, rhi = cluster_ratio_ci(g["rule_pnl"].to_numpy(float), g["entry_cost"].to_numpy(float), mid,
                                     st["ci_level"], st["n_boot"], st["seed"])
    return dict(entries=len(g), win_rate=float(g["settle_side"].mean()), mean_ask=float(g["entry_ask"].mean()),
                mean_all_in=float((g["entry_cost"] / g["contracts"]).mean()), roi=roi, roi_ci_lo=rlo,
                roi_ci_hi=rhi, pnl_pc=pm, pnl_ci_lo=plo, pnl_ci_hi=phi, sd_pc=float(pnl.std()))


def summarize(pos: pd.DataFrame, by: Sequence[str], st: dict[str, Any] | None = None) -> pd.DataFrame:
    st = st or wf_settings({})
    by = list(by)
    rows = [{**dict(zip(by, k if isinstance(k, tuple) else (k,))), **_stats(g, st)}
            for k, g in pos.groupby(by, sort=True)] if len(pos) else []
    return pd.DataFrame(rows, columns=[*by, *STATS_COLUMNS])


def dip_share(favs: pd.DataFrame, pos: pd.DataFrame, by: Sequence[str] = ("band", "tier")) -> pd.DataFrame:
    """Share of banded favourites with an entry at each dip level (slippage-independent)."""
    by = list(by)
    out = favs.groupby(by).size().rename("favourites").reset_index()
    for rule, _ in DIPS:
        hit = favs.assign(hit=favs["match_id"].isin(pos.loc[pos["rule"] == rule, "match_id"]))
        out = out.merge(hit.groupby(by)["hit"].mean().rename(f"share_{rule.lower()}").reset_index(), on=by)
    return out


def paired(pos: pd.DataFrame, by: Sequence[str], st: dict[str, Any] | None = None,
           rule: str = GATED_RULE) -> pd.DataFrame:
    """DIP vs START per contract on matches with both entries (selects START's bad matches)."""
    st = st or wf_settings({})
    by = list(by)
    key = ["slippage", "match_id"]
    s = pos.loc[pos["rule"] == "START", [*key, "rule_pnl", "contracts", "entry_cost"]]
    j = pos[pos["rule"] == rule].merge(s, on=key, how="inner", suffixes=("", "_start"))
    rows = []
    for k, g in (j.groupby(by, sort=True) if len(j) else []):
        mid = g["match_id"].to_numpy()
        dpc = g["rule_pnl"].to_numpy(float) / g["contracts"].to_numpy(float)
        spc = g["rule_pnl_start"].to_numpy(float) / g["contracts_start"].to_numpy(float)
        dm, dlo, dhi = cluster_mean_ci(dpc - spc, mid, st["ci_level"], st["n_boot"], st["seed"])
        rows.append({**dict(zip(by, k if isinstance(k, tuple) else (k,))), "matches": len(g),
                     "win_rate": float(g["settle_side"].mean()),
                     "start_pnl_pc": float(spc.mean()), "dip_pnl_pc": float(dpc.mean()),
                     "diff_pc": dm, "diff_ci_lo": dlo, "diff_ci_hi": dhi,
                     "start_roi": float(g["rule_pnl_start"].sum() / g["entry_cost_start"].sum()),
                     "dip_roi": float(g["rule_pnl"].sum() / g["entry_cost"].sum())})
    return pd.DataFrame(rows, columns=[*by, "matches", "win_rate", "start_pnl_pc", "dip_pnl_pc", "diff_pc",
                                       "diff_ci_lo", "diff_ci_hi", "start_roi", "dip_roi"])


def dip_minutes(pos: pd.DataFrame, by: Sequence[str] = ("band", "tier"), rule: str = GATED_RULE) -> pd.DataFrame:
    d = pos[(pos["rule"] == rule) & (pos["slippage"] == pos["slippage"].min())]
    by = list(by)
    rows = [{**dict(zip(by, k if isinstance(k, tuple) else (k,))), "dips": len(g),
             "min_p25": float(g["minutes_from_start"].quantile(0.25)),
             "min_p50": float(g["minutes_from_start"].quantile(0.50)),
             "min_p75": float(g["minutes_from_start"].quantile(0.75))}
            for k, g in d.groupby(by, sort=True)] if len(d) else []
    return pd.DataFrame(rows, columns=[*by, "dips", "min_p25", "min_p50", "min_p75"])


def tag_set1(pos: pd.DataFrame, sets: pd.DataFrame | None) -> pd.DataFrame:
    """`set1`: "before" / "after" the set-1 close_time of that match, or "no_set1_data"."""
    out = pos.assign(set1="no_set1_data")
    if sets is None or sets.empty or "set_no" not in sets:
        return out
    s1 = sets[sets["set_no"] == 1].dropna(subset=["close_time"])
    close = pd.to_datetime(s1.set_index(s1["match_id"].astype(str))["close_time"], utc=True)
    close = close[~close.index.duplicated()]
    c = out["match_id"].astype(str).map(close)
    has = c.notna()
    out.loc[has, "set1"] = np.where(out.loc[has, "entry_ts"] <= c[has], "before", "after")
    return out


def band_gate(by_slip: dict[float, pd.DataFrame], months: pd.Series, band: str, st: dict[str, Any],
              rule: str = GATED_RULE) -> FixedGate:
    """The fixed-rule gate (cashout.fixed_rule_gate) on one band's DIP entries; every entry is a trade."""
    g = fixed_rule_gate({s: d[(d["rule"] == rule) & (d["band"] == band)] for s, d in by_slip.items()}, months, st)
    g.reasons = [r.replace(" triggers; need", " entries; need").replace("no DOG positions", "no entries")
                 for r in g.reasons]
    return g


# ---- CLI -----------------------------------------------------------------------

def report_md(data_dir, n_matches: int, t: dict[str, pd.DataFrame], gates: dict[str, FixedGate]) -> str:
    fmt = lambda df: md_table(df.round(4))                               # noqa: E731
    lines = ["# Fallen-favourite study: run summary", "",
             f"Data `{data_dir}`; {n_matches} settled matches with aligned quotes. Pre-registration: "
             "docs/edge_favdip.md. Favourite = higher ask at the last formed pre-match row (ask_a + ask_b <= "
             f"${FORMED_MAX:.2f}); bands 60-80 and 80-97 gated, 50-60 context. win_rate = mean settlement; "
             "per-contract values in dollars.", "",
             "## Gate: DIP50 per band (fixed rule, absolute P&L, monthly)", ""]
    for band, g in gates.items():
        verdict = "PASS" if g.passed else "FAIL: " + "; ".join(g.reasons)
        lines += [f"- DIP50, band {band}: **{verdict}**", "",
                  fmt(g.gate.assign(slippage=g.gate["slippage"].map(slip_label))), "", fmt(g.folds), ""]
    lines += ["## START vs DIP: calibration, ROI and P&L per contract (by band x tier x rule)", "",
              fmt(t["summary"]), "",
              "## Share of favourites that dip (any slippage)", "", fmt(t["dip_share"]), "",
              "## Paired: DIP50 vs START on the matches where the dip happened",
              "This pairing selects START's bad matches (the favourite was losing when it dipped); the owner's "
              "comparison is the unconditional ROI of each rule above.", "", fmt(t["paired"]), "",
              "## Minutes from scheduled start to the DIP50 entry", "", fmt(t["dip_minutes"]), "",
              "## DIP50 before vs after the end of set 1 (descriptive; ATP/WTA only)", "", fmt(t["set1"]), ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fallen-favourite study, docs/edge_favdip.md")
    ap.add_argument("--data", default="data/processed/kalshi", type=Path)
    ap.add_argument("--sets", default=None, type=Path, help="set-winner table (default <data>/sets.parquet)")
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
    paths = cash_paths(align(quotes, matches, staleness_s(cfg)), matches, cfg)
    starts = pd.to_datetime(matches.drop_duplicates("match_id").set_index("match_id")["scheduled_start"],
                            utc=True).to_dict()
    by_slip = {s: simulate_favdip(paths, cfg, s, starts) for s in SLIPPAGES}
    allpos = pd.concat(by_slip.values(), ignore_index=True)
    months = match_months(paths)
    favs = favourites(paths)
    dip50 = allpos[allpos["rule"] == GATED_RULE]
    t = {"summary": summarize(allpos, ("band", "tier", "rule", "slippage"), st),
         "dip_share": dip_share(favs, by_slip[SLIPPAGES[0]]),
         "paired": paired(allpos, ("band", "tier", "slippage"), st),
         "dip_minutes": dip_minutes(allpos),
         "set1": summarize(tag_set1(dip50, load_sets(args.sets or args.data / "sets.parquet")),
                           ("band", "set1", "slippage"), st)}
    gates = {b: band_gate(by_slip, months, b, st) for b in GATED_BANDS}

    args.out.mkdir(parents=True, exist_ok=True)
    for k, v in t.items():
        v.to_csv(args.out / f"favdip_{k}.csv", index=False)
    for b, g in gates.items():
        g.gate.to_csv(args.out / f"favdip_gate_{b}.csv", index=False)
        g.folds.to_csv(args.out / f"favdip_months_{b}.csv", index=False)
    md = report_md(args.data, len(paths), t, gates)
    (args.out / "favdip_summary.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
