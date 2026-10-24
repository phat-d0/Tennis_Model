"""True-arb scan: buy A and B at the same aligned timestamp.

Per observation: combined ask, guaranteed profit after fees and slippage via `true_arb`, at
matched depth min(size_a, size_b, execution.max_contracts_per_trade). With unknown depth
(candles) the check is for 1 contract and `depth_known` is False; Kalshi's per-order fee
rounding makes a 1-contract fill the most fee-heavy case.

Consecutive arb observations in a match form an episode (a gap longer than the staleness
limit splits it). Duration runs from first to last arb observation, so it is a lower bound;
dollar profit is ONE fill at the best observation's depth (resting liquidity can't be
assumed to refill). Sampled candle asks overstate fillability and miss arbs that open and
close between samples.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..config import kalshi_fees
from ..locks import true_arb
from .align import match_fees, staleness_s

EPISODE_COLUMNS = ["match_id", "start", "end", "duration_s", "n_obs", "phase", "best_edge",
                   "min_combined", "contracts", "profit", "depth_known"]
SUMMARY_COLUMNS = ["match_id", "n_obs", "n_arb", "frac_arb", "n_episodes", "best_edge",
                   "min_combined", "episode_profit"]


def arb_observations(aligned: pd.DataFrame, matches: pd.DataFrame, cfg: dict[str, Any]) -> pd.DataFrame:
    """Aligned rows plus combined, contracts, profit, edge (per contract), depth_known, is_arb."""
    ex = cfg.get("execution") or {}
    slip = float(ex.get("slippage", 0.0))
    cap = ex.get("max_contracts_per_trade")
    min_edge = float((cfg.get("backtest") or {}).get("min_arb_profit", 0.0))
    fees, default = match_fees(matches, cfg), kalshi_fees(cfg)

    df = aligned.sort_values(["match_id", "ts"], kind="stable").reset_index(drop=True)
    n = len(df)
    ask_a, ask_b = df["ask_a"].to_numpy(float), df["ask_b"].to_numpy(float)
    size_a, size_b = df["size_a"].to_numpy(float), df["size_b"].to_numpy(float)
    known = ~(np.isnan(size_a) | np.isnan(size_b))
    contracts, profit, edge = np.zeros(n), np.zeros(n), np.full(n, np.nan)
    mids = df["match_id"].to_numpy(object)
    # fees are >= 0, so only rows with combined + slippage < 1 can be arbs
    for i in np.flatnonzero(ask_a + ask_b + 2 * slip < 1.0):
        fm = fees.get(mids[i], default)
        if known[i]:
            r = true_arb(ask_a[i], ask_b[i], fm, size_a[i], size_b[i], cap, slip)
        else:
            r = true_arb(ask_a[i], ask_b[i], fm, max_contracts=1.0, slippage=slip)
        contracts[i], profit[i], edge[i] = r.contracts, r.profit, r.edge_per_contract
    return df.assign(combined=ask_a + ask_b, contracts=contracts, profit=profit, edge=edge,
                     depth_known=known, is_arb=(contracts > 0) & (profit > 0) & (edge >= min_edge))


def scan_arb(aligned: pd.DataFrame, matches: pd.DataFrame, cfg: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (episodes, per-match summary incl. fraction of observations in arb)."""
    if aligned.empty:
        return pd.DataFrame(columns=EPISODE_COLUMNS), pd.DataFrame(columns=SUMMARY_COLUMNS)
    df = arb_observations(aligned, matches, cfg)
    mids = df["match_id"].to_numpy(object)
    same = np.r_[False, mids[1:] == mids[:-1]]
    close = (df["ts"].diff() <= pd.Timedelta(seconds=staleness_s(cfg))).to_numpy()
    arb = df["is_arb"].to_numpy()
    cont = arb & np.r_[False, arb[:-1]] & same & close
    df["episode"] = np.cumsum(arb & ~cont)

    eps = []
    for _, g in df[df["is_arb"]].groupby("episode", sort=True):
        best = g.loc[g["profit"].idxmax()]
        start, end = g["ts"].iloc[0], g["ts"].iloc[-1]
        eps.append(dict(match_id=g["match_id"].iloc[0], start=start, end=end,
                        duration_s=(end - start).total_seconds(), n_obs=len(g), phase=g["phase"].iloc[0],
                        best_edge=g["edge"].max(), min_combined=g["combined"].min(),
                        contracts=best["contracts"], profit=best["profit"],
                        depth_known=bool(g["depth_known"].all())))
    episodes = pd.DataFrame(eps, columns=EPISODE_COLUMNS)

    summary = df.groupby("match_id", sort=True).agg(
        n_obs=("is_arb", "size"), n_arb=("is_arb", "sum"),
        best_edge=("edge", "max"), min_combined=("combined", "min")).reset_index()
    summary["frac_arb"] = summary["n_arb"] / summary["n_obs"]
    per_ep = episodes.groupby("match_id").agg(n_episodes=("profit", "size"), episode_profit=("profit", "sum"))
    summary = summary.merge(per_ep, on="match_id", how="left")
    summary["n_episodes"] = summary["n_episodes"].fillna(0).astype(int)
    summary["episode_profit"] = summary["episode_profit"].fillna(0.0)
    return episodes, summary[SUMMARY_COLUMNS]
