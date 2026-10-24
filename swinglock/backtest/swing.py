"""Swing-lock simulation for an entry/lock rule (X, Y) on settled matches.

Entry: first aligned timestamp where ask(side) <= X; buy backtest.contracts_per_entry
(capped by ask depth when known) at ask + slippage, paying the fee.
Lock: first strictly later timestamp where
    entry all-in per contract + (ask(other) + slippage) + fee per contract <= Y
and the other side's depth (when known) covers the position; the fill itself comes from
`lock_quote`. Otherwise the position is held to settlement.

Modes: "first" (default) takes one entry per match on whichever side triggers first (tie:
cheaper ask); "both" treats each side as an independent candidate entry.

No lookahead: decisions at a row use only that row (built from quotes at or before its
timestamp); the winner is only used to settle. Settlement time is the match's last aligned
observation (a proxy for when the market resolves).

Fill-realism caveat: candle data gives sampled ask levels without depth, so fills are
assumed at the sampled ask in full size (optimistic), while dips between samples are
missed (pessimistic for short-lived locks).
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

import numpy as np
import pandas as pd

from ..fees import FeeModel
from ..locks import SIDES, Holding, buy_cost, lock_quote, other
from .align import match_fees

MODES = ("first", "both")


@dataclass
class MatchPath:
    """Pre-extracted arrays for one settled match (built once, reused across the grid)."""
    match_id: str
    tier: str
    winner: str
    fees: FeeModel
    ts: list[pd.Timestamp]
    ask: dict[str, np.ndarray]
    size: dict[str, np.ndarray]
    phase: np.ndarray

    @property
    def settle_ts(self) -> pd.Timestamp:
        return self.ts[-1]


@dataclass(frozen=True)
class Trade:
    match_id: str
    tier: str
    side: str
    role: str                 # "favorite" if entry ask > 0.5 else "underdog"
    entry_ts: pd.Timestamp
    entry_phase: str
    entry_ask: float
    entry_all_in: float       # per contract incl. slippage and fee
    contracts: float
    entry_cost: float
    locked: bool
    lock_ts: pd.Timestamp     # NaT if not locked
    lock_ask: float           # NaN if not locked
    lock_cost: float
    settle_ts: pd.Timestamp
    winner: str
    pnl: float
    capital: float            # total dollars spent (entry + lock)
    hold_s: float             # seconds exposed: entry -> lock, or entry -> settlement
    depth_known: bool


TRADE_COLUMNS = [f.name for f in fields(Trade)]


def match_paths(aligned: pd.DataFrame, matches: pd.DataFrame, cfg: dict[str, Any]) -> list[MatchPath]:
    """One MatchPath per match with a settled winner (A/B) and aligned quotes."""
    fees = match_fees(matches, cfg)
    m = matches.drop_duplicates("match_id").set_index("match_id")
    out = []
    for mid, g in aligned.groupby("match_id", sort=True):
        if mid not in m.index:
            continue
        winner, tier = m.at[mid, "winner"], m.at[mid, "tier"]
        if not (isinstance(winner, str) and winner in SIDES):
            continue
        g = g.sort_values("ts", kind="stable")
        out.append(MatchPath(
            str(mid), tier if isinstance(tier, str) else "unknown", winner, fees[mid],
            list(pd.DatetimeIndex(g["ts"])),
            {"A": g["ask_a"].to_numpy(float), "B": g["ask_b"].to_numpy(float)},
            {"A": g["size_a"].to_numpy(float), "B": g["size_b"].to_numpy(float)},
            g["phase"].to_numpy(object)))
    return out


def _first_trigger(p: MatchPath, side: str, x: float) -> int | None:
    ask, size = p.ask[side], p.size[side]
    hit = np.flatnonzero((ask <= x) & (ask > 0) & (np.isnan(size) | (size > 0)))
    return int(hit[0]) if hit.size else None


def _entries(p: MatchPath, x: float, mode: str) -> list[tuple[str, int]]:
    hits = [(s, i) for s in SIDES if (i := _first_trigger(p, s, x)) is not None]
    if mode == "both" or not hits:
        return hits
    if mode != "first":
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    return [min(hits, key=lambda h: (h[1], p.ask[h[0]][h[1]]))]


def _depth(v: float) -> float | None:
    return None if np.isnan(v) else float(v)


def _trade(p: MatchPath, side: str, i: int, y: float, contracts: float, slip: float) -> Trade:
    o, fm = other(side), p.fees
    ask_i, size_i = float(p.ask[side][i]), p.size[side][i]
    n = contracts if np.isnan(size_i) else min(contracts, float(size_i))
    entry_cost = buy_cost(ask_i, n, fm, slip)
    held = Holding().add(side, n, entry_cost)

    fill = np.minimum(p.ask[o][i + 1:] + slip, 1.0)
    depth = p.size[o][i + 1:]
    ok = (entry_cost / n + fill + fm.per_contract(fill) <= y) & (np.isnan(depth) | (depth >= n - 1e-9))
    hits = np.flatnonzero(ok)
    lock_ts, lock_ask, lock_cost, known = pd.NaT, np.nan, 0.0, not np.isnan(size_i)
    if hits.size:
        j = i + 1 + int(hits[0])
        q = lock_quote(held, float(p.ask["A"][j]), float(p.ask["B"][j]), fm,
                       _depth(p.size["A"][j]), _depth(p.size["B"][j]), slip)
        held = held.add(q.side_to_buy, q.contracts_to_buy, q.cost)
        lock_ts, lock_ask, lock_cost = p.ts[j], q.ask, q.cost
        known = known and not np.isnan(p.size[o][j])

    locked = hits.size > 0
    end = lock_ts if locked else p.settle_ts
    return Trade(
        match_id=p.match_id, tier=p.tier, side=side,
        role="favorite" if ask_i > 0.5 else "underdog",
        entry_ts=p.ts[i], entry_phase=str(p.phase[i]), entry_ask=ask_i,
        entry_all_in=entry_cost / n, contracts=n, entry_cost=entry_cost,
        locked=bool(locked), lock_ts=lock_ts, lock_ask=lock_ask, lock_cost=lock_cost,
        settle_ts=p.settle_ts, winner=p.winner, pnl=held.pnl_if(p.winner),
        capital=held.total_cost, hold_s=(end - p.ts[i]).total_seconds(), depth_known=bool(known))


def simulate(paths: list[MatchPath], x: float, y: float, cfg: dict[str, Any], mode: str = "first") -> pd.DataFrame:
    """Trades (one row per entry, TRADE_COLUMNS) for rule (X, Y) over the given match paths."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    contracts = float(cfg["backtest"]["contracts_per_entry"])
    slip = float((cfg.get("execution") or {}).get("slippage", 0.0))
    rows = [vars(_trade(p, s, i, y, contracts, slip)) for p in paths for s, i in _entries(p, x, mode)]
    df = pd.DataFrame(rows, columns=TRADE_COLUMNS)
    for c in ("entry_ts", "lock_ts", "settle_ts"):
        df[c] = pd.to_datetime(df[c], utc=True)
    return df
