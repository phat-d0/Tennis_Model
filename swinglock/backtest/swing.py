"""Swing-lock simulation for an entry/lock rule (X, Y) on settled matches.

Entry: first aligned timestamp where ask(side) <= X; buy backtest.contracts_per_entry
(capped by ask depth when known) at ask + slippage, paying the fee.
Lock: first strictly later timestamp where
    entry all-in per contract + (ask(other) + slippage) + fee per contract <= Y
and the other side's depth (when known) covers the position; the fill itself comes from
`lock_quote`. Otherwise the position is held to settlement.

Entry filters (config backtest.*, all off by default) also require, at the entry row:
- `min_entry_ask`: ask >= this (skips near-decided matches quoted at a few cents);
- `min_minutes_from_start` / `max_minutes_from_start`: a window in minutes after scheduled_start
  (known live; negative = before the start), e.g. 0 and 60 for the first hour of play only;
- `entry_phase`: "live" or "pre" (row phase from align); "any" = off;
- `min_minutes_to_close`: at least this many minutes before the match's last observation.
  LOOKAHEAD: the end time isn't known live, so this one is a diagnostic only and results
  using it don't count for the gate.

Modes: "first" (default) takes one entry per match on whichever side triggers first (tie:
cheaper ask); "both" treats each side as an independent candidate entry.

Settlement: each side pays matches.settle_a / settle_b per contract (1/0 normally; Kalshi's
fair price, summing to $1, for a match that never started). Files without those columns fall
back to winner -> 1/0; matches with neither are unsettled and skipped.

No lookahead: decisions at a row use only that row (built from quotes at or before its
timestamp); the outcome is only used to settle. Settlement time is the match's last aligned
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
ENTRY_FILTERS = ("min_entry_ask", "min_minutes_from_start", "max_minutes_from_start", "min_minutes_to_close")
ENTRY_PHASES = ("any", "pre", "live")
LOOKAHEAD_FILTERS = ("min_minutes_to_close",)


def entry_filters(cfg: dict[str, Any]) -> dict[str, Any]:
    """Active entry filters from config backtest.* (unset or null = off; entry_phase "any" = off)."""
    bt = cfg.get("backtest") or {}
    out: dict[str, Any] = {k: float(bt[k]) for k in ENTRY_FILTERS if bt.get(k) is not None}
    phase = bt.get("entry_phase") or "any"
    if phase not in ENTRY_PHASES:
        raise ValueError(f"backtest.entry_phase must be one of {ENTRY_PHASES}, got {phase!r}")
    if phase != "any":
        out["entry_phase"] = phase
    return out


@dataclass
class MatchPath:
    """Pre-extracted arrays for one settled match (built once, reused across the grid)."""
    match_id: str
    tier: str
    winner: str               # "A" | "B" | "NA" (fair-price settlement with no winner)
    pay_a: float              # dollars paid per side-A contract at settlement
    pay_b: float
    fees: FeeModel
    ts: list[pd.Timestamp]
    ask: dict[str, np.ndarray]
    size: dict[str, np.ndarray]
    phase: np.ndarray
    start: pd.Timestamp = pd.NaT    # scheduled_start (NaT if unknown)

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
    settle_a: float           # payout per contract used to settle (1/0, or a fair price)
    settle_b: float
    pnl: float
    capital: float            # total dollars spent (entry + lock)
    hold_s: float             # seconds exposed: entry -> lock, or entry -> settlement
    depth_known: bool
    minutes_to_close: float   # entry -> settlement proxy (last observation)
    minutes_from_start: float # scheduled_start -> entry (negative pre-match; NaN if unknown)


TRADE_COLUMNS = [f.name for f in fields(Trade)]


def match_paths(aligned: pd.DataFrame, matches: pd.DataFrame, cfg: dict[str, Any]) -> list[MatchPath]:
    """One MatchPath per settled match (payouts or an A/B winner) with aligned quotes."""
    fees = match_fees(matches, cfg)
    m = matches.drop_duplicates("match_id").set_index("match_id")
    out = []
    for mid, g in aligned.groupby("match_id", sort=True):
        if mid not in m.index:
            continue
        pay = settlement(m.loc[mid])
        if pay is None:
            continue
        winner, tier = m.at[mid, "winner"], m.at[mid, "tier"]
        start = m.at[mid, "scheduled_start"] if "scheduled_start" in m.columns else pd.NaT
        winner = winner if isinstance(winner, str) and winner in SIDES else "NA"
        g = g.sort_values("ts", kind="stable")
        out.append(MatchPath(
            str(mid), tier if isinstance(tier, str) else "unknown", winner, *pay, fees[mid],
            list(pd.DatetimeIndex(g["ts"])),
            {"A": g["ask_a"].to_numpy(float), "B": g["ask_b"].to_numpy(float)},
            {"A": g["size_a"].to_numpy(float), "B": g["size_b"].to_numpy(float)},
            g["phase"].to_numpy(object), pd.Timestamp(start) if pd.notna(start) else pd.NaT))
    return out


def settlement(row: pd.Series) -> tuple[float, float] | None:
    """(pay_a, pay_b) per contract: settle_a/settle_b when both are present, else winner -> 1/0,
    else None (unsettled)."""
    a, b = row.get("settle_a"), row.get("settle_b")
    if a is not None and b is not None and not (pd.isna(a) or pd.isna(b)):
        return float(a), float(b)
    w = row.get("winner")
    if isinstance(w, str) and w in SIDES:
        return (1.0, 0.0) if w == "A" else (0.0, 1.0)
    return None


def _minutes(p: MatchPath) -> tuple[np.ndarray, np.ndarray]:
    """(minutes to the last observation, minutes since scheduled_start) per row."""
    ts = pd.DatetimeIndex(p.ts)
    to_close = (p.settle_ts - ts).total_seconds().to_numpy() / 60
    from_start = ((ts - p.start).total_seconds().to_numpy() / 60 if pd.notna(p.start)
                  else np.full(len(ts), np.nan))
    return to_close, from_start


def _allowed(p: MatchPath, filters: dict[str, Any]) -> np.ndarray | None:
    """Rows where entry filters pass (None = no filters). Unknown start time fails a
    minutes-from-start window."""
    if not filters:
        return None
    to_close, from_start = _minutes(p)
    ok = np.ones(len(p.ts), bool)
    if "min_minutes_from_start" in filters or "max_minutes_from_start" in filters:
        lo = filters.get("min_minutes_from_start", -np.inf)
        hi = filters.get("max_minutes_from_start", np.inf)
        with np.errstate(invalid="ignore"):
            ok &= ~np.isnan(from_start) & (from_start >= lo) & (from_start <= hi)
    if "entry_phase" in filters:
        ok &= p.phase == filters["entry_phase"]
    if "min_minutes_to_close" in filters:
        ok &= to_close >= filters["min_minutes_to_close"]
    return ok


def _first_trigger(p: MatchPath, side: str, x: float, filters: dict[str, Any] | None = None,
                   allowed: np.ndarray | None = None) -> int | None:
    ask, size = p.ask[side], p.size[side]
    ok = (ask <= x) & (ask > 0) & (np.isnan(size) | (size > 0))
    if filters and "min_entry_ask" in filters:
        ok &= ask >= filters["min_entry_ask"]
    if allowed is not None:
        ok &= allowed
    hit = np.flatnonzero(ok)
    return int(hit[0]) if hit.size else None


def _entries(p: MatchPath, x: float, mode: str, filters: dict[str, Any] | None = None) -> list[tuple[str, int]]:
    allowed = _allowed(p, filters or {})
    hits = [(s, i) for s in SIDES if (i := _first_trigger(p, s, x, filters, allowed)) is not None]
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
    from_start = (p.ts[i] - p.start).total_seconds() / 60 if pd.notna(p.start) else np.nan
    return Trade(
        match_id=p.match_id, tier=p.tier, side=side,
        role="favorite" if ask_i > 0.5 else "underdog",
        entry_ts=p.ts[i], entry_phase=str(p.phase[i]), entry_ask=ask_i,
        entry_all_in=entry_cost / n, contracts=n, entry_cost=entry_cost,
        locked=bool(locked), lock_ts=lock_ts, lock_ask=lock_ask, lock_cost=lock_cost,
        settle_ts=p.settle_ts, winner=p.winner, settle_a=p.pay_a, settle_b=p.pay_b,
        pnl=held.pnl_settled(p.pay_a, p.pay_b),
        capital=held.total_cost, hold_s=(end - p.ts[i]).total_seconds(), depth_known=bool(known),
        minutes_to_close=(p.settle_ts - p.ts[i]).total_seconds() / 60, minutes_from_start=from_start)


def simulate(paths: list[MatchPath], x: float, y: float, cfg: dict[str, Any], mode: str = "first") -> pd.DataFrame:
    """Trades (one row per entry, TRADE_COLUMNS) for rule (X, Y) over the given match paths."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    contracts = float(cfg["backtest"]["contracts_per_entry"])
    slip = float((cfg.get("execution") or {}).get("slippage", 0.0))
    filters = entry_filters(cfg)
    rows = [vars(_trade(p, s, i, y, contracts, slip)) for p in paths for s, i in _entries(p, x, mode, filters)]
    df = pd.DataFrame(rows, columns=TRADE_COLUMNS)
    for c in ("entry_ts", "lock_ts", "settle_ts"):
        df[c] = pd.to_datetime(df[c], utc=True)
    return df
