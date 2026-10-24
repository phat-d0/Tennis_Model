"""Grid search of swing-lock rules over config backtest.entry_thresholds x lock_thresholds.

Picking the best (X, Y) from this grid is in-sample selection; treat the top row as a
hypothesis to check on later data, not an expected return.
"""

from __future__ import annotations

from typing import Any, Sequence

import pandas as pd

from .metrics import METRICS, summarize
from .swing import TRADE_COLUMNS, MatchPath, match_paths, simulate

KEYS = ["mode", "x", "y"]


def _combos(cfg: dict[str, Any], modes: Sequence[str]) -> list[tuple[str, float, float]]:
    bt = cfg["backtest"]
    return [(m, float(x), float(y)) for m in modes for x in bt["entry_thresholds"] for y in bt["lock_thresholds"]]


def grid_trades(paths: list[MatchPath], cfg: dict[str, Any], modes: Sequence[str] = ("first",)) -> pd.DataFrame:
    """All trades for every (mode, X, Y), tagged with those columns."""
    frames = [simulate(paths, x, y, cfg, m).assign(mode=m, x=x, y=y) for m, x, y in _combos(cfg, modes)]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=[*TRADE_COLUMNS, *KEYS])


def grid_metrics(trades: pd.DataFrame, cfg: dict[str, Any], modes: Sequence[str] = ("first",)) -> pd.DataFrame:
    """Tidy metrics per (mode, X, Y); combos without trades are kept with n_trades = 0."""
    groups = {k: g for k, g in trades.groupby(KEYS)} if len(trades) else {}
    rows = [{"mode": m, "x": x, "y": y, **summarize(groups.get((m, x, y), trades.iloc[:0]))}
            for m, x, y in _combos(cfg, modes)]
    return pd.DataFrame(rows, columns=[*KEYS, *METRICS])


def grid_search(aligned: pd.DataFrame, matches: pd.DataFrame, cfg: dict[str, Any],
                modes: Sequence[str] = ("first",)) -> pd.DataFrame:
    """Metrics per (mode, X, Y) straight from an aligned quote frame."""
    return grid_metrics(grid_trades(match_paths(aligned, matches, cfg), cfg, modes), cfg, modes)
