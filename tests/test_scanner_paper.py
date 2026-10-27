"""Paper trading: live engine == backtest swing sim on the same path, ledger replay, settlement,
lookback over recorded books, and the pre-registration doc matching the code."""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from swinglock.backtest.align import align
from swinglock.backtest.swing import match_paths, simulate
from swinglock.config import kalshi_fees, load_config
from swinglock.scanner import lookback
from swinglock.scanner.market import MatchPair, MatchQuote, SideQuote
from swinglock.scanner.output import AlertSink, StateWriter
from swinglock.scanner.paper import RULES, PaperBook, PaperRule
from swinglock.scanner.run import Scanner

ROOT = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 10, 27, 12, 0, tzinfo=timezone.utc)
START = T0 + timedelta(seconds=600)
MID = "KXATPMATCH-26OCT27AAABBB"
PAIR = MatchPair(MID, "KXATPMATCH", "atp", "Test Open", "Aaa", "Bbb", MID + "-AAA", MID + "-BBB", START)
CFG = load_config()
FEES = kalshi_fees(CFG, "quadratic_with_maker_fees", 1.0)

# (seconds, ask_a, size_a, ask_b, size_b); scheduled start at 600 s
PATH = [
    (0, 0.45, 500, 0.57, 500),     # nothing qualifies
    (5, 0.39, 500, None, None),    # B has no ask: not an observation
    (10, 0.38, 60, 0.64, 500),     # P2 enters A, capped at 60 contracts by depth
    (20, 0.28, 500, 0.74, 500),    # P4 (pre) enters A
    (30, 0.19, 500, 0.83, 500),    # P1 enters A
    (610, 0.25, 500, 0.77, 500),   # live: P3 enters A
    (620, 0.45, 500, 0.57, 30),    # P1/P3/P4 would lock, but only 30 contracts at B's ask
    (630, 0.45, 500, 0.57, 500),   # locks fill
    (640, 0.50, 500, 0.55, 500),   # P2 still can't lock (needs B <= ~53.6c)
]
PAY = (0.0, 1.0)                   # B wins


def quote(ask_a, size_a, ask_b, size_b):
    side = lambda ask, size, t: SideQuote(ask, size, f"yes:{t}" if ask is not None else None, None, None)  # noqa: E731
    return MatchQuote(side(ask_a, size_a, PAIR.ticker_a), side(ask_b, size_b, PAIR.ticker_b))


def live_book(ledger=None):
    book = PaperBook(ledger_path=ledger)
    for sec, *q in PATH:
        book.step([PAIR], {MID: quote(*q)}, {"KXATPMATCH": FEES}, T0 + timedelta(seconds=sec))
    return book


def quotes_frame():
    """The recorder's shape: every snapshot writes both sides, with a NaN ask when a side has none
    (kalshi_normalize.orderbooks_to_quotes), so the as-of join can't carry a stale ask forward."""
    nan, rows = float("nan"), []
    for sec, aa, sa, ab, sb in PATH:
        ts = pd.Timestamp(T0 + timedelta(seconds=sec))
        for side, ask, size, t in (("A", aa, sa, PAIR.ticker_a), ("B", ab, sb, PAIR.ticker_b)):
            rows.append({"ts": ts, "match_id": MID, "venue": "kalshi", "side": side,
                         "ask": nan if ask is None else ask, "ask_size": nan if size is None else float(size),
                         "bid": nan, "bid_size": nan, "ask_source": f"yes:{t}" if ask is not None else None,
                         "source": "orderbook"})
    return pd.DataFrame(rows)


def matches_frame():
    return pd.DataFrame([{
        "match_id": MID, "venue": "kalshi", "series": "KXATPMATCH", "tier": "atp", "tournament": "Test Open",
        "player_a": "Aaa", "player_b": "Bbb", "instrument_a": PAIR.ticker_a, "instrument_b": PAIR.ticker_b,
        "scheduled_start": pd.Timestamp(START), "open_time": pd.Timestamp(T0 - timedelta(days=1)),
        "close_time": pd.Timestamp(T0 + timedelta(days=14)), "winner": "B", "settle_a": PAY[0],
        "settle_b": PAY[1], "fee_type": "quadratic_with_maker_fees", "fee_multiplier": 1.0}])


# ---- the core guarantee: one rule definition, same trades live and in the backtest sim -------

def test_live_engine_matches_backtest_swing_sim():
    book = live_book()
    book.settle(MID, *PAY, T0 + timedelta(hours=3))
    paths = match_paths(align(quotes_frame(), matches_frame()), matches_frame(), CFG)
    for rule in RULES:
        sim = simulate(paths, rule.x, rule.y, rule.backtest_cfg(CFG, 0.0), rule.mode)
        live = book.trades.get(f"{rule.id}:{MID}")
        assert len(sim) == 1 and live is not None, rule.id
        s = sim.iloc[0]
        assert live.side == s.side and live.entry_phase == s.entry_phase, rule.id
        assert pd.Timestamp(live.entry_ts) == s.entry_ts and live.entry_ask == pytest.approx(s.entry_ask)
        assert live.contracts == pytest.approx(s.contracts) and live.entry_cost == pytest.approx(s.entry_cost)
        assert bool(live.lock_ts) == bool(s.locked), rule.id
        if s.locked:
            assert pd.Timestamp(live.lock_ts) == s.lock_ts and live.lock_cost == pytest.approx(s.lock_cost)
        assert live.pnl == pytest.approx(s.pnl, abs=1e-6), rule.id


def test_path_exercises_every_branch():
    t = live_book().trades
    p1, p2, p3, p4 = (t[f"{r.id}:{MID}"] for r in RULES)
    assert p2.contracts == 60 and p2.lock_ts is None                  # depth-capped, never locks
    assert p4.entry_phase == "pre" and p3.entry_phase == "live"
    assert all(x.lock_ts == "2026-10-27T12:10:30Z" for x in (p1, p3, p4))  # blocked at 620 by depth
    assert p1.lock_contracts == p1.contracts == 100


# ---- ledger: append-only, replayed on restart, no re-entry ----------------------------------

def test_ledger_replay_restores_state_and_blocks_reentry(tmp_path):
    ledger = tmp_path / "paper" / "ledger.jsonl"
    book = live_book(ledger)
    lines = [json.loads(x) for x in ledger.read_text().splitlines()]
    assert [x["event"] for x in lines].count("open") == 4 and [x["event"] for x in lines].count("lock") == 3
    again = PaperBook(ledger_path=ledger)
    assert {k: v.status for k, v in again.trades.items()} == {k: v.status for k, v in book.trades.items()}
    events = again.step([PAIR], {MID: quote(0.10, 500, 0.40, 500)}, {"KXATPMATCH": FEES}, T0 + timedelta(hours=1))
    assert [e["event"] for e in events] == ["lock"]                   # P2 locks; nobody re-enters
    n = len(ledger.read_text().splitlines())
    again.settle(MID, *PAY, T0 + timedelta(hours=3))
    assert len(ledger.read_text().splitlines()) == n + 4              # one settle line per trade


def test_summary_shape_and_pnl():
    book = live_book()
    s = book.summary()
    assert set(s) == {"since", "rules", "by_rule", "trades"}
    assert [r["id"] for r in s["rules"]] == [r.id for r in RULES]
    p1 = next(r for r in s["by_rule"] if r["rule"] == RULES[0].id)
    assert p1["trades"] == 1 and p1["locked"] == 1 and p1["open"] == 0 and p1["pnl_locked_unsettled"] > 0
    row = next(t for t in s["trades"] if t["rule"] == RULES[0].id)
    assert row["status"] == "locked" and row["pnl"] == pytest.approx(min(row["pnl_if_a"], row["pnl_if_b"]))
    book.settle(MID, *PAY, T0 + timedelta(hours=3))
    s = book.summary()
    assert all(t["status"] == "settled" for t in s["trades"])
    assert next(r for r in s["by_rule"] if r["rule"] == RULES[1].id)["pnl_settled"] < 0   # unlocked A lost


def test_rule_backtest_cfg_forces_lookahead_filter_off():
    cfg = {"backtest": {"min_minutes_to_close": 30, "entry_phase": "live", "contracts_per_entry": 10}}
    out = PaperRule("R", 0.3, 0.9, min_entry_ask=0.05).backtest_cfg(cfg, 0.01)
    assert out["backtest"]["min_minutes_to_close"] is None and out["backtest"]["entry_phase"] == "any"
    assert out["backtest"]["contracts_per_entry"] == 100 and out["execution"]["slippage"] == 0.01
    assert cfg["backtest"]["min_minutes_to_close"] == 30                # input not mutated


def test_preregistration_doc_lists_exactly_the_coded_rules():
    doc = (ROOT / "docs" / "scanner_paper.md").read_text()
    rows = re.findall(r"^\| `(P\d[^`]*)` \| ([\d.]+) \| ([\d.]+) \| (\w+) \|", doc, re.M)
    assert [(i, float(x), float(y), ph) for i, x, y, ph in rows] == \
        [(r.id, r.x, r.y, r.entry_phase) for r in RULES]
    assert "Pre-registered 2026-10-27" in doc


# ---- scanner integration: settle via GET /markets once the match leaves the open list --------

class FakeClient:
    requests_made = 0

    def __init__(self):
        self.calls = []

    def markets(self, tickers):
        self.calls.append(tuple(tickers))
        return [{"ticker": PAIR.ticker_a, "result": "no", "settlement_value_dollars": "0.0000"},
                {"ticker": PAIR.ticker_b, "result": "yes", "settlement_value_dollars": "1.0000"}]


def test_scanner_settles_paper_trades_and_shares_the_cache(tmp_path):
    book = live_book()
    sc = Scanner(CFG, FakeClient(), positions_path=tmp_path / "none.json",
                 sink=AlertSink(None, stream=None), state=StateWriter(tmp_path / "state.json", 5),
                 now=lambda: T0 + timedelta(hours=3), paper=book, settlements_path=tmp_path / "settlements.json")
    sc.pairs = [PAIR]
    sc.settle_paper()
    assert sc.client.calls == [] and all(t.settle_ts is None for t in book.trades.values())   # still open
    sc.pairs = []
    sc.settle_paper()
    assert sc.client.calls == [(PAIR.ticker_a, PAIR.ticker_b)]
    assert all(t.status == "settled" for t in book.trades.values())
    assert json.loads((tmp_path / "settlements.json").read_text()) == {MID: [0.0, 1.0]}


def test_paper_is_independent_of_positions_and_lands_in_state(tmp_path):
    from swinglock.scanner.engine import StepResult
    w = StateWriter(tmp_path / "state.json", 5)
    state = w.write(StepResult([], [], []), T0, live_book().summary())
    assert set(state) == {"generated_at", "poll_seconds", "venue", "matches", "positions", "alerts", "paper"}
    assert state["positions"] == [] and len(state["paper"]["trades"]) == 4


# ---- lookback over recorded books -----------------------------------------------------------

def test_lookback_runs_rules_over_recorded_books_incrementally(tmp_path):
    rec = tmp_path / "recorded"
    (rec / "quotes").mkdir(parents=True)
    quotes_frame().to_parquet(rec / "quotes" / "2026-10-27.parquet", index=False)
    m = matches_frame().assign(winner=pd.NA, settle_a=float("nan"), settle_b=float("nan"))
    m.to_parquet(rec / "matches.parquet", index=False)
    out = tmp_path / "paper"
    client = FakeClient()
    now = T0 + timedelta(hours=8)
    s = lookback.run(CFG, rec, out, client, now=now)
    assert s["matches_new_this_run"] == 1 and s["settlement_requests"] == 0   # fake doesn't count
    assert client.calls == [(PAIR.ticker_a, PAIR.ticker_b)]
    by = {(r["rule"], r["slippage"]): r for r in s["by_rule"]}
    assert set(by) == {(r.id, sl) for r in RULES for sl in (0.0, 0.01)}
    assert by[(RULES[0].id, 0.0)]["trades"] == 1 and by[(RULES[0].id, 0.0)]["locked"] == 1
    assert by[(RULES[1].id, 0.0)]["locked"] == 0 and by[(RULES[1].id, 0.0)]["pnl"] < 0
    # same P&L as the live engine at 0c
    live = live_book()
    live.settle(MID, *PAY, now)
    assert by[(RULES[0].id, 0.0)]["pnl"] == pytest.approx(live.trades[f"{RULES[0].id}:{MID}"].pnl, abs=1e-4)
    on_disk = json.loads((out / "lookback.json").read_text())
    assert on_disk["by_rule"] == s["by_rule"] and on_disk["by_day"][0]["day"] == "2026-10-27"
    # second run: nothing new, no duplicate trades, no new requests
    s2 = lookback.run(CFG, rec, out, client, now=now)
    assert s2["matches_new_this_run"] == 0 and len(client.calls) == 1
    assert s2["by_rule"] == s["by_rule"]
    assert len(pd.read_parquet(out / "lookback_trades.parquet")) == 8   # 4 rules x 2 slippages


def test_lookback_waits_for_results_before_processing(tmp_path):
    rec = tmp_path / "recorded"
    (rec / "quotes").mkdir(parents=True)
    quotes_frame().to_parquet(rec / "quotes" / "2026-10-27.parquet", index=False)
    matches_frame().assign(settle_a=float("nan"), settle_b=float("nan")).to_parquet(rec / "matches.parquet")
    s = lookback.run(CFG, rec, tmp_path / "paper", None, now=T0 + timedelta(hours=1))   # too soon, no client
    assert s["matches_new_this_run"] == 0 and s["matches_processed"] == 0
    assert all(r["trades"] == 0 for r in s["by_rule"])


# ---- repo hygiene: Kalshi data never goes into git ------------------------------------------

def test_nothing_under_data_is_tracked():
    """data/ holds live Kalshi-derived files (state, ledger, recorded books): never commit them.
    Test fixtures live in tests/fixtures/."""
    import shutil
    import subprocess
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    tracked = subprocess.run(["git", "ls-files", "data"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.split()
    assert tracked == [], f"files under data/ are tracked: {tracked[:5]}"


def test_state_writer_extra_keys(tmp_path):
    from swinglock.scanner.engine import StepResult
    w = StateWriter(tmp_path / "state.json", 5, extra={"min_arb_profit_per_contract": 0.005})
    assert w.write(StepResult([], [], []), T0)["min_arb_profit_per_contract"] == 0.005
