"""Scan logic: quotes → state rows, lock quotes on holdings, de-duplicated alerts.

Pure (no I/O) so the loop and the replay tests drive the same code.

Alert rules
- arb: `locks.true_arb` at the best ask of each side, sized to the smaller resting depth
  (capped at `execution.max_contracts_per_trade`), per-series fees and config slippage.
  Fires when profit > 0 and profit per contract >= `scanner.min_arb_profit_per_contract`.
- lock: `locks.lock_quote` on a `positions.json` holding. Fires when the locked P&L after
  buying the short side >= `scanner.min_lock_profit`.
- One alert per opportunity episode, keyed by (type, match_id). It re-alerts when the
  profit improves by at least max(`realert_min_improvement`, `realert_min_improvement_pct`
  of the last alerted value). The episode ends once the opportunity has been gone for
  `episode_gap_seconds`, so a book that flickers doesn't re-trigger the alert.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..fees import FeeModel
from ..locks import Holding, lock_quote, true_arb
from ..positions import PositionRow
from .market import MatchPair, MatchQuote

log = logging.getLogger(__name__)
_warned: set[tuple[str, str]] = set()   # unmapped position rows already logged (once per row)


def iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


@dataclass
class Settings:
    min_arb_profit_per_contract: float = 0.005
    min_lock_profit: float = 0.05
    slippage: float = 0.0
    max_contracts: float | None = 100
    realert_min_improvement: float = 0.05
    realert_min_improvement_pct: float = 0.25
    episode_gap_seconds: float = 30.0

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Settings":
        s, ex = cfg.get("scanner", {}), cfg.get("execution", {})
        d = cls()
        return cls(
            min_arb_profit_per_contract=s.get("min_arb_profit_per_contract", d.min_arb_profit_per_contract),
            min_lock_profit=s.get("min_lock_profit", d.min_lock_profit),
            slippage=ex.get("slippage", d.slippage),
            max_contracts=ex.get("max_contracts_per_trade", d.max_contracts),
            realert_min_improvement=s.get("realert_min_improvement", d.realert_min_improvement),
            realert_min_improvement_pct=s.get("realert_min_improvement_pct", d.realert_min_improvement_pct),
            episode_gap_seconds=s.get("episode_gap_seconds", d.episode_gap_seconds),
        )


# --------------------------------------------------------------------------
# Positions → holdings
# --------------------------------------------------------------------------

def side_of(row: PositionRow, pair: MatchPair | None) -> str | None:
    """Map a position row's `side` ("A"/"B", a market ticker, or a player name) to A/B."""
    s = row.side.strip()
    if s.upper() in ("A", "B"):
        return s.upper()
    if pair is None:
        return None
    if s == pair.ticker_a or s.lower() == pair.player_a.lower():
        return "A"
    if s == pair.ticker_b or s.lower() == pair.player_b.lower():
        return "B"
    return None


def holdings_from_positions(rows: list[PositionRow], pairs: dict[str, MatchPair]) -> dict[str, Holding]:
    out: dict[str, Holding] = {}
    for r in rows:
        side = side_of(r, pairs.get(r.market))
        if side is None:
            if (r.market, r.side) in _warned:
                continue
            _warned.add((r.market, r.side))
            log.warning("position %s/%s: can't map side to A/B (match not open or unknown side)",
                        r.market, r.side)
            continue
        h = out.get(r.market, Holding())
        out[r.market] = h.add(side, r.contracts, r.contracts * r.avg_price)
    return out


# --------------------------------------------------------------------------
# Alert de-duplication
# --------------------------------------------------------------------------

@dataclass
class _Episode:
    last_value: float
    last_seen: datetime


@dataclass
class Deduper:
    settings: Settings
    episodes: dict[tuple[str, str], _Episode] = field(default_factory=dict)

    def check(self, key: tuple[str, str], value: float, now: datetime) -> str | None:
        """Call when the opportunity is present. Returns "new", "improved" or None."""
        ep = self.episodes.get(key)
        if ep is None:
            self.episodes[key] = _Episode(value, now)
            return "new"
        ep.last_seen = now
        step = max(self.settings.realert_min_improvement,
                   self.settings.realert_min_improvement_pct * abs(ep.last_value))
        if value >= ep.last_value + step - 1e-12:
            ep.last_value = value
            return "improved"
        return None

    def expire(self, now: datetime) -> None:
        gap = timedelta(seconds=self.settings.episode_gap_seconds)
        for key in [k for k, ep in self.episodes.items() if now - ep.last_seen >= gap]:
            del self.episodes[key]


# --------------------------------------------------------------------------
# One scan step
# --------------------------------------------------------------------------

@dataclass
class StepResult:
    matches: list[dict]
    positions: list[dict]
    alerts: list[dict]


def _fmt(x: float | None, cents: bool = True) -> str:
    if x is None:
        return "-"
    return f"{x * 100:.1f}c" if cents else f"{x:.2f}"


class Engine:
    def __init__(self, settings: Settings):
        self.s = settings
        self.dedupe = Deduper(settings)

    def step(
        self,
        pairs: list[MatchPair],
        quotes: dict[str, MatchQuote],
        fees: dict[str, FeeModel],
        holdings: dict[str, Holding],
        now: datetime,
        quote_ts: datetime | None = None,
    ) -> StepResult:
        quote_ts = quote_ts or now
        by_id = {p.match_id: p for p in pairs}
        matches, positions, alerts = [], [], []

        for p in pairs:
            q = quotes.get(p.match_id)
            if q is None:
                continue
            fm = fees[p.series]
            row = {
                "match_id": p.match_id, "series": p.series, "tier": p.tier,
                "player_a": p.player_a, "player_b": p.player_b, "phase": p.phase(now),
                "quote_ts": iso(quote_ts),
                "ask_a": q.a.ask, "ask_b": q.b.ask, "size_a": q.a.ask_size, "size_b": q.b.ask_size,
                "bid_a": q.a.bid, "bid_b": q.b.bid,
                "combined": None, "combined_with_fees": None, "arb_contracts": 0.0, "arb_profit": 0.0,
            }
            if q.a.ask is not None and q.b.ask is not None:
                arb = true_arb(q.a.ask, q.b.ask, fm, depth_a=q.a.ask_size, depth_b=q.b.ask_size,
                               max_contracts=self.s.max_contracts, slippage=self.s.slippage)
                row["combined"] = round(q.a.ask + q.b.ask, 6)
                if arb.contracts > 0:
                    row["combined_with_fees"] = round(arb.cost / arb.contracts, 6)
                if arb.is_arb:
                    row["arb_contracts"], row["arb_profit"] = arb.contracts, round(arb.profit, 6)
                if arb.is_arb and arb.edge_per_contract >= self.s.min_arb_profit_per_contract:
                    kind = self.dedupe.check(("arb", p.match_id), arb.profit, now)
                    if kind:
                        alerts.append({
                            "ts": iso(now), "type": "arb", "match_id": p.match_id,
                            "message": (
                                f"{'ARB' if kind == 'new' else 'ARB improved'} {p.player_a} vs {p.player_b}: "
                                f"buy {arb.contracts:.2f} A ({p.player_a}) @ {_fmt(q.a.ask)} via {q.a.ask_source} "
                                f"[depth {q.a.ask_size:.2f}] + {arb.contracts:.2f} B ({p.player_b}) @ "
                                f"{_fmt(q.b.ask)} via {q.b.ask_source} [depth {q.b.ask_size:.2f}]; "
                                f"cost ${arb.cost:.2f} incl. fees, locked P&L ${arb.profit:.2f} "
                                f"(quote {iso(quote_ts)})"),
                            "contracts": arb.contracts, "cost": round(arb.cost, 6),
                            "locked_pnl": round(arb.profit, 6),
                        })
            matches.append(row)

        for match_id, h in holdings.items():
            p = by_id.get(match_id)
            q = quotes.get(match_id)
            entry = {
                "match_id": match_id, "player_a": p.player_a if p else "", "player_b": p.player_b if p else "",
                "contracts_a": h.contracts_a, "avg_a": h.cost_a / h.contracts_a if h.contracts_a else 0.0,
                "contracts_b": h.contracts_b, "avg_b": h.cost_b / h.contracts_b if h.contracts_b else 0.0,
                "pnl_if_a": round(h.pnl_if("A"), 6), "pnl_if_b": round(h.pnl_if("B"), 6), "lock": None,
            }
            positions.append(entry)
            if p is None or q is None or h.short_side is None:
                continue
            short = q.a if h.short_side == "A" else q.b
            if short.ask is None:
                continue
            lq = lock_quote(h, q.a.ask if q.a.ask is not None else 1.0, q.b.ask if q.b.ask is not None else 1.0,
                            fees[p.series], depth_a=q.a.ask_size, depth_b=q.b.ask_size, slippage=self.s.slippage)
            entry["lock"] = {
                "side_to_buy": lq.side_to_buy, "contracts_to_buy": round(lq.contracts_to_buy, 6),
                "ask": lq.ask, "cost": round(lq.cost, 6), "locked_pnl": round(lq.locked_pnl, 6),
                "depth_ok": lq.depth_ok,
            }
            if lq.locked_pnl >= self.s.min_lock_profit:
                kind = self.dedupe.check(("lock", match_id), lq.locked_pnl, now)
                if kind:
                    name = p.player_a if lq.side_to_buy == "A" else p.player_b
                    depth_note = "" if lq.depth_ok else f" (DEPTH SHORT: only {short.ask_size:.2f} at this ask)"
                    alerts.append({
                        "ts": iso(now), "type": "lock", "match_id": match_id,
                        "message": (
                            f"{'LOCK' if kind == 'new' else 'LOCK improved'} {p.player_a} vs {p.player_b}: "
                            f"buy {lq.contracts_to_buy:.2f} {lq.side_to_buy} ({name}) @ {_fmt(lq.ask)} "
                            f"via {short.ask_source} [depth {short.ask_size:.2f}]{depth_note}; "
                            f"cost ${lq.cost:.2f} incl. fees, locked P&L ${lq.locked_pnl:.2f} "
                            f"(now: ${lq.pnl_if_a:.2f} if A, ${lq.pnl_if_b:.2f} if B; quote {iso(quote_ts)})"),
                        "contracts": round(lq.contracts_to_buy, 6), "cost": round(lq.cost, 6),
                        "locked_pnl": round(lq.locked_pnl, 6),
                    })

        self.dedupe.expire(now)
        return StepResult(matches, positions, alerts)
