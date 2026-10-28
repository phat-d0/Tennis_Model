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

Cash-out group (`CashRule`, `CASH_RULES`, pre-registered 2026-10-28) mirrors
`swinglock.backtest.cashout` (`_positions`, DOG50 = level rule L):
- Entry: at a match's first observation with phase `pre` (E1) and its first with phase `live` (E2), buy
  every side with 0 < ask < max_ask, min(contracts, depth) at ask + slippage, taker fee included.
- Exit (level rules): the first strictly later observation where the net bid per contract,
  ((bid - slippage) - fee(bid - slippage, n) / n), is >= level and the bid size covers n; sell all at the
  bid. Otherwise (and always for the control, level None) held to settlement.

Ledger: `data/paper/ledger.jsonl`, append-only, one JSON line per event (open | lock | exit | settle)
holding the full trade snapshot; the latest line per trade_id is its state, so a restart replays it.
`paper_state.json` next to it keeps each rule's `since` (its first poll: start-up entries have
entry_ts == since) and which matches already had their E1/E2 observation.
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
    group: str = "swing"

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



@dataclass(frozen=True)
class CashRule:
    """A cash-out rule in `swinglock.backtest.cashout` terms (E1/E2 entries, level exit L)."""
    id: str
    max_ask: float                          # entry: 0 < ask < max_ask at the E1 / E2 observation
    level: float | None                     # exit: net bid >= level; None = hold to settlement
    contracts: float = 100.0
    entries: tuple[str, ...] = ("E1", "E2")
    group: str = "cashout"

    def describe(self) -> dict[str, Any]:
        d = asdict(self)
        d["entries"] = list(self.entries)
        return d


# Pre-registered 2026-10-28 in docs/scanner_paper.md, before any cash-out backtest result existed.
CASH_RULES: tuple[CashRule, ...] = (
    CashRule("C0-dog20-hold", max_ask=0.20, level=None),
    CashRule("C1-dog20-sell50", max_ask=0.20, level=0.50),
    CashRule("C2-dog30-sell50", max_ask=0.30, level=0.50),
    CashRule("C3-dog20-sell60", max_ask=0.20, level=0.60),     # owner: cash out at 50-50 "or even winning"
    CashRule("C4-dog20-sell70", max_ask=0.20, level=0.70),
)
ENTRY_TYPE = {"pre": "E1", "live": "E2"}


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
    pnl: float | None = None                # final once settled or exited
    group: str = "swing"
    entry_type: str | None = None           # cash-out: "E1" | "E2"
    exit_ts: str | None = None              # cash-out: sold at the bid
    exit_bid: float | None = None
    exit_value: float | None = None         # cash received, after the sell fee

    @property
    def status(self) -> str:
        if self.settle_ts:
            return "settled"
        return "exited" if self.exit_ts else "locked" if self.lock_ts else "open"

    @property
    def final(self) -> bool:
        return self.status in ("settled", "exited")

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
        if self.status == "exited":
            d["pnl_if_a"] = d["pnl_if_b"] = self.pnl
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
                 slippage: float = 0.0, cash_rules: tuple[CashRule, ...] = CASH_RULES):
        if any(r.mode != "first" for r in rules):
            raise ValueError("the live paper engine supports mode 'first' only")
        ids = [r.id for r in (*rules, *cash_rules)]
        if len(set(ids)) != len(ids):
            raise ValueError("paper rule ids must be unique")
        self.rules = rules
        self.cash_rules = cash_rules
        self.slippage = slippage
        self.ledger_path = Path(ledger_path) if ledger_path else None
        self.state_path = self.ledger_path.with_name("paper_state.json") if self.ledger_path else None
        self.trades: dict[str, PaperTrade] = {}
        self.since: dict[str, str] = {}               # rule id -> its first poll (ISO)
        self.cash_seen: dict[str, list[str]] = {}     # match id -> entry types already observed
        if self.ledger_path and self.ledger_path.exists():
            self._replay()
        self._load_state()

    @property
    def all_rules(self) -> tuple:
        return (*self.rules, *self.cash_rules)

    def _load_state(self) -> None:
        state = {}
        if self.state_path and self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text())
            except ValueError as e:
                log.error("paper state unreadable (%s); rebuilt from the ledger", e)
        self.since = dict(state.get("since") or {})
        self.cash_seen = {k: list(v) for k, v in (state.get("cash_seen") or {}).items()}
        first = min((t.entry_ts for t in self.trades.values()), default=None)
        for r in self.all_rules:   # rules that traded before this file existed began at the book's first poll
            if r.id not in self.since and any(t.rule == r.id for t in self.trades.values()):
                self.since[r.id] = first
        for t in self.trades.values():
            if t.entry_type and t.entry_type not in self.cash_seen.setdefault(t.match_id, []):
                self.cash_seen[t.match_id].append(t.entry_type)

    def _save_state(self) -> None:
        if not self.state_path:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"since": self.since, "cash_seen": self.cash_seen}, sort_keys=True))
        tmp.replace(self.state_path)

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
        events, changed = [], False
        for r in self.all_rules:
            if r.id not in self.since:
                self.since[r.id], changed = iso(now), True
        cash = {r.id: r for r in self.cash_rules}
        open_cash: dict[str, list[PaperTrade]] = {}
        for t in self.trades.values():
            if t.rule in cash and t.status == "open":
                open_cash.setdefault(t.match_id, []).append(t)
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
            if not self.cash_rules:
                continue
            for t in open_cash.get(p.match_id, []):         # exits first: strictly after the entry
                if self._try_exit(t, cash[t.rule], q, fm, now):
                    events.append(self._record("exit", t, now))
            etype = ENTRY_TYPE.get(p.phase(now))
            if etype and etype not in self.cash_seen.get(p.match_id, []):
                self.cash_seen.setdefault(p.match_id, []).append(etype)
                changed = True
                for rule in self.cash_rules:
                    if etype not in rule.entries:
                        continue
                    for side, sq in zip(SIDES, (q.a, q.b)):
                        if not (0 < sq.ask < 1) or (sq.ask_size is not None and sq.ask_size <= 0):
                            continue
                        if sq.ask < rule.max_ask:
                            tid = f"{rule.id}:{p.match_id}:{etype}:{side}"
                            t = self._open(tid, rule, p, side, sq, fm, now, etype)
                            events.append(self._record("open", t, now))
        if changed:
            self._save_state()
        return events

    def _open(self, tid: str, rule: PaperRule | CashRule, p: MatchPair, side: str, sq: SideQuote,
              fm: FeeModel, now: datetime, entry_type: str | None = None) -> PaperTrade:
        n = rule.contracts if sq.ask_size is None else min(rule.contracts, sq.ask_size)
        t = PaperTrade(
            trade_id=tid, rule=rule.id, match_id=p.match_id, series=p.series, tier=p.tier,
            player_a=p.player_a, player_b=p.player_b, ticker_a=p.ticker_a, ticker_b=p.ticker_b,
            side=side, entry_ts=iso(now), entry_phase=p.phase(now), entry_ask=sq.ask,
            entry_source=sq.ask_source, contracts=n,
            entry_cost=round(buy_cost(sq.ask, n, fm, self.slippage), 6),
            group=rule.group, entry_type=entry_type)
        self.trades[tid] = t
        return t

    def _try_exit(self, t: PaperTrade, rule: CashRule, q: MatchQuote, fm: FeeModel, now: datetime) -> bool:
        """Sell the whole position at the bid when the net bid reaches the rule's level (cashout L)."""
        if rule.level is None or not t.entry_cost / t.contracts < rule.level:
            return False
        sq = q.a if t.side == "A" else q.b
        if sq.bid is None:
            return False
        sale = min(max(sq.bid - self.slippage, 0.0), 1.0)
        if sale <= 0 or (sq.bid_size is not None and sq.bid_size < t.contracts - 1e-9):
            return False
        value = t.contracts * sale - fm.fee(sale, t.contracts)
        if value / t.contracts < rule.level - 1e-12:
            return False
        t.exit_ts, t.exit_bid, t.exit_value = iso(now), sq.bid, round(value, 6)
        t.pnl = round(value - t.entry_cost, 6)
        return True

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
                if not t.final and (open_match_ids is None or t.match_id not in open_match_ids)}

    def settle(self, match_id: str, pay_a: float, pay_b: float, now: datetime) -> list[dict]:
        events = []
        for t in self.trades.values():
            if t.match_id == match_id and not t.final:
                t.settle_ts, t.settle_a, t.settle_b = iso(now), pay_a, pay_b
                t.pnl = round(t.holding.pnl_settled(pay_a, pay_b), 6)
                events.append(self._record("settle", t, now))
        return events

    # ---- state.json --------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        trades = list(self.trades.values())
        by_rule = []
        for r in self.all_rules:
            ts = [t for t in trades if t.rule == r.id]
            settled = [t for t in ts if t.final]                 # settled, or exited (cash-out)
            locked = [t for t in ts if t.lock_ts or t.exit_ts]   # swing locks / cash-out exits
            pending = [t for t in ts if t.status == "locked"]
            by_rule.append({
                "rule": r.id, "group": r.group, "trades": len(ts),
                "open": sum(t.status == "open" for t in ts), "locked": len(locked), "settled": len(settled),
                "lock_rate": round(len(locked) / len(ts), 4) if ts else None,
                "pnl_settled": round(sum(t.pnl for t in settled), 6),
                "pnl_locked_unsettled": round(sum(t.holding.locked_pnl for t in pending), 6),
                "contracts": round(sum(t.contracts for t in ts), 6),    # entered (per-contract P&L)
                "capital": round(sum(t.holding.total_cost for t in ts), 6),
            })
        live = [t for t in trades if not t.final]
        done = sorted((t for t in trades if t.final), key=lambda t: t.settle_ts or t.exit_ts, reverse=True)
        shown = sorted(live, key=lambda t: t.entry_ts, reverse=True) + done
        return {
            "since": min((t.entry_ts for t in trades), default=None),
            "rules": [{**r.describe(), "since": self.since.get(r.id)} for r in self.all_rules],
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
