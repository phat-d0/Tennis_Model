"""Paper trading (forward test) of pre-registered swing-lock rules on live Kalshi quotes.

Read-only: positions here are hypothetical. Nothing is sent to Kalshi besides the same public
GETs the scanner already makes (plus `GET /markets?tickers=` to learn results).

One rule definition (`PaperRule`, `RULES`) serves both:
- the live engine below, fed one observation per scanner poll, and
- the nightly lookback (`swinglock.scanner.lookback`), which runs `swinglock.backtest.swing.simulate`
  with `PaperRule.backtest_cfg()` over the recorder's order books.

The live decisions mirror `swing._entries` / `swing._trade` exactly (tests/test_scanner_paper.py
replays one path through both and compares the trades):
- Entry (mode "first"): the first observation where ask(side) <= X, ask > 0, depth > 0 and the
  rule's entry filters pass, on the cheaper side if both qualify (tie: A). Buy min(contracts, depth)
  at ask + slippage, taker fee included.
- Lock: the first strictly later observation where
      entry all-in per contract + (ask(other) + slippage) + fee per contract <= Y
  and the other side's depth covers the position; the fill is `locks.lock_quote` (equal counts).
- Otherwise held to settlement: `Holding.pnl_settled(settle_a, settle_b)` (1/0, or Kalshi's fair
  price for a match that never started).
An observation counts only when both sides have an ask (as the backtest's aligned rows do).

Ledger: `data/paper/ledger.jsonl`, append-only, one JSON line per event (open | lock | settle) holding
the full trade snapshot; the latest line per trade_id is its state, so a restart replays it.
"""

from __future__ import annotations

import copy
import json
import logging
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from ..fees import FeeModel
from ..locks import SIDES, Holding, buy_cost, lock_quote, other
from .engine import iso
from .market import MatchPair, MatchQuote, SideQuote

log = logging.getLogger(__name__)

ENTRY_FILTER_KEYS = ("min_entry_ask", "min_minutes_from_start", "max_minutes_from_start")
MAX_TRADES_IN_STATE = 200


@dataclass(frozen=True)
class PaperRule:
    """A swing-lock rule in the backtest's terms (see swinglock/backtest/swing.py)."""
    id: str
    x: float                                # entry: ask <= x
    y: float                                # lock: all-in cost per matched contract <= y
    entry_phase: str = "any"                # "any" | "pre" | "live"
    min_entry_ask: float | None = None
    min_minutes_from_start: float | None = None
    max_minutes_from_start: float | None = None
    contracts: float = 100.0                # target size; capped by the depth at the ask
    mode: str = "first"

    def backtest_cfg(self, cfg: dict[str, Any], slippage: float | None = None) -> dict[str, Any]:
        """cfg with backtest.* set to this rule, for `swing.simulate(paths, x, y, cfg, mode)`.
        Every entry filter is set explicitly (lookahead `min_minutes_to_close` forced off)."""
        out = copy.deepcopy(cfg)
        bt = out.setdefault("backtest", {})
        bt["contracts_per_entry"] = self.contracts
        bt["entry_phase"] = self.entry_phase
        bt["min_minutes_to_close"] = None
        for k in ENTRY_FILTER_KEYS:
            bt[k] = getattr(self, k)
        if slippage is not None:
            out.setdefault("execution", {})["slippage"] = slippage
        return out

    def describe(self) -> dict[str, Any]:
        return asdict(self)


# Pre-registered 2026-10-27 in docs/scanner_paper.md, before any live paper result existed.
# Change only with a new dated entry there; never re-tune on paper results.
RULES: tuple[PaperRule, ...] = (
    PaperRule("P1-x20-y90", x=0.20, y=0.90),
    PaperRule("P2-x40-y95", x=0.40, y=0.95),
    PaperRule("P3-x30-y94-live", x=0.30, y=0.94, entry_phase="live"),
    PaperRule("P4-x30-y94-pre", x=0.30, y=0.94, entry_phase="pre"),
)


# --------------------------------------------------------------------------
# Trades
# --------------------------------------------------------------------------

@dataclass
class PaperTrade:
    trade_id: str
    rule: str
    match_id: str
    series: str
    tier: str
    player_a: str
    player_b: str
    ticker_a: str
    ticker_b: str
    side: str
    entry_ts: str
    entry_phase: str
    entry_ask: float
    entry_source: str | None
    contracts: float
    entry_cost: float
    lock_ts: str | None = None
    lock_ask: float | None = None
    lock_source: str | None = None
    lock_contracts: float = 0.0
    lock_cost: float = 0.0
    settle_ts: str | None = None
    settle_a: float | None = None
    settle_b: float | None = None
    pnl: float | None = None                # final once settled

    @property
    def status(self) -> str:
        return "settled" if self.settle_ts else "locked" if self.lock_ts else "open"

    @property
    def holding(self) -> Holding:
        h = Holding().add(self.side, self.contracts, self.entry_cost)
        return h.add(other(self.side), self.lock_contracts, self.lock_cost) if self.lock_ts else h

    def view(self) -> dict[str, Any]:
        """state.json row: the stored fields (minus tickers/sources) + status and P&L if A/B wins."""
        h = self.holding
        d = {k: v for k, v in asdict(self).items() if k not in ("ticker_a", "ticker_b")}
        d["status"] = self.status
        d["pnl_if_a"], d["pnl_if_b"] = round(h.pnl_if("A"), 6), round(h.pnl_if("B"), 6)
        if self.status == "locked":
            d["pnl"] = round(h.locked_pnl, 6)
        return d


TRADE_FIELDS = [f.name for f in fields(PaperTrade)]


def _entry(rule: PaperRule, p: MatchPair, q: MatchQuote, now: datetime) -> tuple[str, SideQuote] | None:
    """Side to enter at this observation under `rule`, or None. Mirrors swing._entries/_first_trigger."""
    phase = p.phase(now)
    if rule.entry_phase != "any" and phase != rule.entry_phase:
        return None
    if rule.min_minutes_from_start is not None or rule.max_minutes_from_start is not None:
        if p.scheduled_start is None:
            return None
        mins = (now - p.scheduled_start).total_seconds() / 60
        if rule.min_minutes_from_start is not None and mins < rule.min_minutes_from_start:
            return None
        if rule.max_minutes_from_start is not None and mins > rule.max_minutes_from_start:
            return None
    hits = []
    for side, sq in zip(SIDES, (q.a, q.b)):
        if sq.ask is None or not (0 < sq.ask <= rule.x) or (sq.ask_size is not None and sq.ask_size <= 0):
            continue
        if rule.min_entry_ask is not None and sq.ask < rule.min_entry_ask:
            continue
        hits.append((sq.ask, side, sq))
    if not hits:
        return None
    _, side, sq = min(hits, key=lambda h: h[0])    # same observation: cheaper ask; tie keeps A
    return side, sq


class PaperBook:
    def __init__(self, rules: tuple[PaperRule, ...] = RULES, ledger_path: str | Path | None = None,
                 slippage: float = 0.0):
        if any(r.mode != "first" for r in rules):
            raise ValueError("the live paper engine supports mode 'first' only")
        if len({r.id for r in rules}) != len(rules):
            raise ValueError("paper rule ids must be unique")
        self.rules = rules
        self.slippage = slippage
        self.ledger_path = Path(ledger_path) if ledger_path else None
        self.trades: dict[str, PaperTrade] = {}
        if self.ledger_path and self.ledger_path.exists():
            self._replay()

    # ---- ledger ----------------------------------------------------------

    def _replay(self) -> None:
        for n, line in enumerate(self.ledger_path.read_text().splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                t = PaperTrade(**{k: rec[k] for k in TRADE_FIELDS if k in rec})
            except (ValueError, TypeError, KeyError) as e:
                log.error("paper ledger line %d unreadable (%s); skipped", n, e)
                continue
            self.trades[t.trade_id] = t
        log.info("paper: replayed %d trades from %s", len(self.trades), self.ledger_path)

    def _record(self, event: str, t: PaperTrade, now: datetime) -> dict:
        rec = {"event": event, "ts": iso(now), **asdict(t)}
        if self.ledger_path:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.ledger_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
        log.info("paper %s %s %s %s", event, t.rule, t.match_id, t.side)
        return rec

    # ---- live step ---------------------------------------------------------

    def step(self, pairs: list[MatchPair], quotes: dict[str, MatchQuote], fees: dict[str, FeeModel],
             now: datetime) -> list[dict]:
        """One observation per open match: enter by rule, or lock an open trade. Returns events."""
        events = []
        for p in pairs:
            q = quotes.get(p.match_id)
            if q is None or q.a.ask is None or q.b.ask is None or p.series not in fees:
                continue
            fm = fees[p.series]
            for rule in self.rules:
                tid = f"{rule.id}:{p.match_id}"
                t = self.trades.get(tid)
                if t is None:
                    hit = _entry(rule, p, q, now)
                    if hit:
                        t = self._open(tid, rule, p, *hit, fm, now)
                        events.append(self._record("open", t, now))
                elif t.status == "open" and self._try_lock(t, rule, q, fm, now):
                    events.append(self._record("lock", t, now))
        return events

    def _open(self, tid: str, rule: PaperRule, p: MatchPair, side: str, sq: SideQuote,
              fm: FeeModel, now: datetime) -> PaperTrade:
        n = rule.contracts if sq.ask_size is None else min(rule.contracts, sq.ask_size)
        t = PaperTrade(
            trade_id=tid, rule=rule.id, match_id=p.match_id, series=p.series, tier=p.tier,
            player_a=p.player_a, player_b=p.player_b, ticker_a=p.ticker_a, ticker_b=p.ticker_b,
            side=side, entry_ts=iso(now), entry_phase=p.phase(now), entry_ask=sq.ask,
            entry_source=sq.ask_source, contracts=n,
            entry_cost=round(buy_cost(sq.ask, n, fm, self.slippage), 6))
        self.trades[tid] = t
        return t

    def _try_lock(self, t: PaperTrade, rule: PaperRule, q: MatchQuote, fm: FeeModel, now: datetime) -> bool:
        o = q.b if t.side == "A" else q.a
        fill = min(o.ask + self.slippage, 1.0)
        if t.entry_cost / t.contracts + fill + fm.per_contract(fill) > rule.y:
            return False
        if o.ask_size is not None and o.ask_size < t.contracts - 1e-9:
            return False
        lq = lock_quote(t.holding, q.a.ask, q.b.ask, fm, q.a.ask_size, q.b.ask_size, self.slippage)
        t.lock_ts, t.lock_ask, t.lock_source = iso(now), lq.ask, o.ask_source
        t.lock_contracts, t.lock_cost = lq.contracts_to_buy, round(lq.cost, 6)
        return True

    # ---- settlement ----------------------------------------------------------

    def unsettled(self, open_match_ids: set[str] | None = None) -> dict[str, tuple[str, str]]:
        """{match_id: (ticker_a, ticker_b)} for trades not yet settled whose match is no longer open."""
        return {t.match_id: (t.ticker_a, t.ticker_b) for t in self.trades.values()
                if t.settle_ts is None and (open_match_ids is None or t.match_id not in open_match_ids)}

    def settle(self, match_id: str, pay_a: float, pay_b: float, now: datetime) -> list[dict]:
        events = []
        for t in self.trades.values():
            if t.match_id == match_id and t.settle_ts is None:
                t.settle_ts, t.settle_a, t.settle_b = iso(now), pay_a, pay_b
                t.pnl = round(t.holding.pnl_settled(pay_a, pay_b), 6)
                events.append(self._record("settle", t, now))
        return events

    # ---- state.json --------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        trades = list(self.trades.values())
        by_rule = []
        for r in self.rules:
            ts = [t for t in trades if t.rule == r.id]
            settled = [t for t in ts if t.status == "settled"]
            locked = [t for t in ts if t.lock_ts]
            pending = [t for t in ts if t.status == "locked"]
            by_rule.append({
                "rule": r.id, "trades": len(ts),
                "open": sum(t.status == "open" for t in ts), "locked": len(locked), "settled": len(settled),
                "lock_rate": round(len(locked) / len(ts), 4) if ts else None,
                "pnl_settled": round(sum(t.pnl for t in settled), 6),
                "pnl_locked_unsettled": round(sum(t.holding.locked_pnl for t in pending), 6),
                "capital": round(sum(t.holding.total_cost for t in ts), 6),
            })
        live = [t for t in trades if t.status != "settled"]
        done = sorted((t for t in trades if t.status == "settled"), key=lambda t: t.settle_ts, reverse=True)
        shown = sorted(live, key=lambda t: t.entry_ts, reverse=True) + done
        return {
            "since": min((t.entry_ts for t in trades), default=None),
            "rules": [r.describe() for r in self.rules],
            "by_rule": by_rule,
            "trades": [t.view() for t in shown[:MAX_TRADES_IN_STATE]],
        }


def settlement_from_markets(markets: list[dict], tickers: tuple[str, str]) -> tuple[float, float] | None:
    """(pay_a, pay_b) once both markets have a result, else None."""
    from ..collectors.kalshi_normalize import settle_value
    by = {m.get("ticker"): m for m in markets}
    if tickers[0] not in by or tickers[1] not in by:
        return None
    a, b = settle_value(by[tickers[0]]), settle_value(by[tickers[1]])
    if a != a or b != b:          # NaN: not settled yet
        return None
    return a, b


def load_settlements(path: Path) -> dict[str, list[float]]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save_settlements(path: Path, data: dict[str, list[float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=0, sort_keys=True))
    tmp.replace(path)
