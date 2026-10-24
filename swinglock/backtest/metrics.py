"""Performance metrics over swing-lock trade tables (see swing.TRADE_COLUMNS)."""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np
import pandas as pd

METRICS = ["n_trades", "lock_rate", "avg_locked_pnl", "avg_unlocked_pnl", "avg_unlocked_loss",
           "total_pnl", "avg_return", "hit_rate", "max_drawdown", "peak_capital", "avg_capital"]
BREAKDOWN_BY = ("entry_phase", "role", "tier")


def max_drawdown(pnl: Sequence[float]) -> float:
    """Largest peak-to-trough fall of cumulative P&L (peak starts at 0), as a positive number."""
    cum = np.cumsum(np.asarray(pnl, float))
    if not cum.size:
        return 0.0
    peak = np.maximum.accumulate(np.maximum(cum, 0.0))
    return float((peak - cum).max())


def capital_usage(trades: pd.DataFrame) -> tuple[float, float]:
    """(peak, time-weighted average) concurrent capital. Entry cost is tied up from entry,
    lock cost from the lock, and both are released at settlement."""
    if trades.empty:
        return 0.0, 0.0
    lk = trades[trades["locked"].astype(bool)]
    ev = pd.concat([
        pd.DataFrame({"ts": trades["entry_ts"], "d": trades["entry_cost"]}),
        pd.DataFrame({"ts": lk["lock_ts"], "d": lk["lock_cost"]}),
        pd.DataFrame({"ts": trades["settle_ts"], "d": -trades["capital"]}),
    ], ignore_index=True)
    ev = ev.assign(order=-ev["d"]).sort_values(["ts", "order"], kind="stable")  # add before release
    level = ev["d"].cumsum().to_numpy()
    t = (ev["ts"] - ev["ts"].iloc[0]).dt.total_seconds().to_numpy()
    span = t[-1]
    avg = float((level[:-1] * np.diff(t)).sum() / span) if span > 0 else float(level.max())
    return float(level.max()), avg


def summarize(trades: pd.DataFrame) -> dict[str, float]:
    """All METRICS for one set of trades (NaN where undefined, e.g. no locked trades)."""
    if trades.empty:
        return {k: (0 if k == "n_trades" else np.nan) for k in METRICS}
    locked = trades["locked"].astype(bool)
    pnl = trades["pnl"].astype(float)
    unl = pnl[~locked]
    peak, avg = capital_usage(trades)
    ordered = trades.sort_values("settle_ts", kind="stable")["pnl"]
    return dict(
        n_trades=len(trades),
        lock_rate=float(locked.mean()),
        avg_locked_pnl=float(pnl[locked].mean()),
        avg_unlocked_pnl=float(unl.mean()),
        avg_unlocked_loss=float(unl[unl < 0].mean()),
        total_pnl=float(pnl.sum()),
        avg_return=float((pnl / trades["capital"]).mean()),
        hit_rate=float((pnl > 0).mean()),
        max_drawdown=max_drawdown(ordered),
        peak_capital=peak,
        avg_capital=avg,
    )


def breakdown(trades: pd.DataFrame, by: Iterable[str] = BREAKDOWN_BY, keys: Sequence[str] = ()) -> pd.DataFrame:
    """Tidy metrics per value of each `by` column (phase, fav/underdog, tier), within `keys`
    groups (e.g. ("mode", "x", "y") for a grid). Columns: *keys, dimension, value, METRICS."""
    keys = list(keys)
    rows = []
    for dim in by:
        for k, g in trades.groupby([*keys, dim], sort=True, dropna=False):
            rows.append({**dict(zip(keys, k[:-1])), "dimension": dim, "value": k[-1], **summarize(g)})
    return pd.DataFrame(rows, columns=[*keys, "dimension", "value", *METRICS])
