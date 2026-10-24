"""Align per-side quotes into one row per observation time per match.

Each A quote is paired with the latest B quote at or before its timestamp (and each B quote
with the latest A quote), provided that quote is at most `max_staleness_s` old. Every row
therefore uses only data already observed at its timestamp (no lookahead). Rows where
either side has no fresh ask are dropped.

Fill-realism caveat: candle-sourced quotes are sampled ask levels (e.g. one per minute)
with no depth. Anything between samples is invisible and the sampled level may not have
been fillable in size, so downstream results are optimistic about fills and pessimistic
about short-lived opportunities.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from ..config import kalshi_fees
from ..fees import FeeModel

DEFAULT_STALENESS_S = 60.0
ALIGNED_COLUMNS = ["match_id", "ts", "ask_a", "ask_b", "size_a", "size_b", "bid_a", "bid_b", "phase"]


def staleness_s(cfg: dict[str, Any]) -> float:
    """Max quote age for the as-of join (config backtest.max_staleness_s, default 60s)."""
    return float((cfg.get("backtest") or {}).get("max_staleness_s", DEFAULT_STALENESS_S))


def match_fees(matches: pd.DataFrame, cfg: dict[str, Any]) -> dict[str, FeeModel]:
    """FeeModel per match_id from its fee_type/fee_multiplier (config defaults when missing)."""
    out = {}
    for mid, ft, mult in zip(matches["match_id"], matches["fee_type"], matches["fee_multiplier"]):
        ft = ft if isinstance(ft, str) else "quadratic"
        out[mid] = kalshi_fees(cfg, ft, None if pd.isna(mult) else float(mult))
    return out


def _side(q: pd.DataFrame, side: str) -> pd.DataFrame:
    s = side.lower()
    cols = {"ask": f"ask_{s}", "ask_size": f"size_{s}", "bid": f"bid_{s}"}
    return q.loc[q["side"] == side, ["match_id", "ts", *cols]].rename(columns=cols)


def align(quotes: pd.DataFrame, matches: pd.DataFrame | None = None,
          max_staleness_s: float = DEFAULT_STALENESS_S) -> pd.DataFrame:
    """As-of join of A and B quotes per match, plus phase: pre / live / unknown (no start time)."""
    q = quotes.dropna(subset=["ts"]).sort_values("ts", kind="stable")
    q = q.drop_duplicates(["match_id", "side", "ts"], keep="last")
    a, b = _side(q, "A"), _side(q, "B")
    if a.empty or b.empty:
        return pd.DataFrame(columns=ALIGNED_COLUMNS)
    kw = dict(on="ts", by="match_id", direction="backward",
              tolerance=pd.Timedelta(seconds=max_staleness_s), allow_exact_matches=True)
    rows = pd.concat([pd.merge_asof(a, b, **kw), pd.merge_asof(b, a, **kw)], ignore_index=True)
    rows = rows.dropna(subset=["ask_a", "ask_b"]).drop_duplicates(["match_id", "ts"])
    rows = rows.sort_values(["match_id", "ts"], kind="stable").reset_index(drop=True)

    start = pd.Series(pd.NaT, index=rows.index, dtype="datetime64[ns, UTC]")
    if matches is not None and "scheduled_start" in matches:
        start = rows["match_id"].map(matches.set_index("match_id")["scheduled_start"])
    known = start.notna().to_numpy()
    pre = np.zeros(len(rows), bool)
    pre[known] = (rows["ts"][known] < start[known]).to_numpy()
    rows["phase"] = np.where(~known, "unknown", np.where(pre, "pre", "live"))
    return rows[ALIGNED_COLUMNS]
