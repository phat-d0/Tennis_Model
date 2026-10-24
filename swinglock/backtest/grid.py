"""Grid search of swing-lock rules over config backtest.entry_thresholds x lock_thresholds.

Picking the best (X, Y) from this grid is in-sample selection; treat the top row as a
hypothesis to check on later data, not an expected return.
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
import pandas as pd

from .metrics import METRICS, summarize
from .swing import TRADE_COLUMNS, MatchPath, match_paths, simulate

KEYS = ["mode", "x", "y"]


def combos(cfg: dict[str, Any], modes: Sequence[str]) -> list[tuple[str, float, float]]:
    bt = cfg["backtest"]
    return [(m, float(x), float(y)) for m in modes for x in bt["entry_thresholds"] for y in bt["lock_thresholds"]]


def grid_trades(paths: list[MatchPath], cfg: dict[str, Any], modes: Sequence[str] = ("first",)) -> pd.DataFrame:
    """All trades for every (mode, X, Y), tagged with those columns."""
    frames = [simulate(paths, x, y, cfg, m).assign(mode=m, x=x, y=y) for m, x, y in combos(cfg, modes)]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=[*TRADE_COLUMNS, *KEYS])


def grid_metrics(trades: pd.DataFrame, cfg: dict[str, Any], modes: Sequence[str] = ("first",)) -> pd.DataFrame:
    """Tidy metrics per (mode, X, Y); combos without trades are kept with n_trades = 0."""
    groups = {k: g for k, g in trades.groupby(KEYS)} if len(trades) else {}
    rows = [{"mode": m, "x": x, "y": y, **summarize(groups.get((m, x, y), trades.iloc[:0]))}
            for m, x, y in combos(cfg, modes)]
    return pd.DataFrame(rows, columns=[*KEYS, *METRICS])


def grid_search(aligned: pd.DataFrame, matches: pd.DataFrame, cfg: dict[str, Any],
                modes: Sequence[str] = ("first",)) -> pd.DataFrame:
    """Metrics per (mode, X, Y) straight from an aligned quote frame."""
    return grid_metrics(grid_trades(match_paths(aligned, matches, cfg), cfg, modes), cfg, modes)


ENTRY_COLUMNS = ["n_trades", "ask_min", "ask_p10", "ask_p50", "ask_p90", "frac_ask_lt_5c", "frac_ask_lt_10c",
                 "mtc_p10", "mtc_p50", "mtc_p90", "frac_live", "pnl_ask_lt_10c", "pnl_ask_ge_10c"]


def _entry_stats(t: pd.DataFrame) -> dict[str, float]:
    ask, mtc, pnl = t["entry_ask"].astype(float), t["minutes_to_close"].astype(float), t["pnl"].astype(float)
    q = lambda s, p: float(s.quantile(p)) if len(s) else np.nan   # noqa: E731
    low = ask < 0.10
    return dict(n_trades=len(t), ask_min=float(ask.min()) if len(t) else np.nan,
                ask_p10=q(ask, 0.1), ask_p50=q(ask, 0.5), ask_p90=q(ask, 0.9),
                frac_ask_lt_5c=float((ask < 0.05).mean()) if len(t) else np.nan,
                frac_ask_lt_10c=float(low.mean()) if len(t) else np.nan,
                mtc_p10=q(mtc, 0.1), mtc_p50=q(mtc, 0.5), mtc_p90=q(mtc, 0.9),
                frac_live=float((t["entry_phase"] == "live").mean()) if len(t) else np.nan,
                pnl_ask_lt_10c=float(pnl[low].mean()) if low.any() else np.nan,
                pnl_ask_ge_10c=float(pnl[~low].mean()) if (~low).any() else np.nan)


def entry_diagnostics(trades: pd.DataFrame, cfg: dict[str, Any], modes: Sequence[str] = ("first",)) -> pd.DataFrame:
    """Per (mode, X, Y): where entries happen. Entry-ask quantiles and the share under 5c/10c
    (near-decided matches), minutes from entry to the last observation (mtc_*), the share of
    live entries, and mean P&L per trade for entries under vs at/over 10c."""
    groups = {k: g for k, g in trades.groupby(KEYS)} if len(trades) else {}
    rows = [{"mode": m, "x": x, "y": y, **_entry_stats(groups.get((m, x, y), trades.iloc[:0]))}
            for m, x, y in combos(cfg, modes)]
    return pd.DataFrame(rows, columns=[*KEYS, *ENTRY_COLUMNS])
