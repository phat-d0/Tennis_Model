"""Paper cash-out group (C0/C1/C2): live engine == backtest cashout sim on the same path, exit rules,
ledger/state replay, per-rule `since`, and the nightly lookback."""

import copy
import json
import re
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from swinglock.backtest.align import align
from swinglock.backtest.cashout import cash_paths, simulate_cashout
from swinglock.scanner import lookback
from swinglock.scanner.market import MatchQuote, SideQuote
from swinglock.scanner.paper import CASH_RULES, RULES, PaperBook
from test_scanner_paper import CFG, FEES, MID, PAIR, T0, FakeClient, matches_frame

ROOT = Path(__file__).resolve().parent.parent
C0, C1, C2 = (r.id for r in CASH_RULES)
NAN = float("nan")

# (seconds, ask_a, size_a, bid_a, bid_size_a, ask_b, size_b, bid_b, bid_size_b); start at 600 s
PATH = [
    (0, 0.15, 500, 0.14, 500, 0.87, 500, 0.84, 500),    # E1: A is a dog -> C0, C1, C2 buy A
    (5, 0.16, 500, 0.15, 500, None, None, None, None),  # B has no ask: not an observation
    (10, 0.25, 500, 0.24, 500, 0.76, 500, 0.74, 500),
    (20, 0.56, 500, 0.55, 50, 0.45, 500, 0.44, 500),    # net bid 53.3c but only 50 contracts bid
    (30, 0.56, 500, 0.55, 500, 0.45, 500, 0.44, 500),   # C1, C2 (E1) sell
    (610, 0.28, 500, 0.27, 500, 0.73, 500, 0.72, 500),  # E2 (first live): A at 28c -> C2 only
    (620, 0.51, 500, 0.50, 500, 0.50, 500, 0.49, 500),  # bid 50c, but net of the fee 48.25c: no
    (630, 0.54, 500, 0.53, 500, 0.47, 500, 0.46, 500),  # net 51.25c: C2 (E2) sells
    (640, 0.20, 500, 0.19, 500, 0.81, 500, 0.80, 500),
]
PAY = (0.0, 1.0)                                          # B wins


def side(ask, size, bid, bsize, ticker):
    return SideQuote(ask, size, f"yes:{ticker}" if ask is not None else None, bid, bsize)


def quote(row):
    _, aa, sa, ba, bsa, ab, sb, bb, bsb = row
    return MatchQuote(side(aa, sa, ba, bsa, PAIR.ticker_a), side(ab, sb, bb, bsb, PAIR.ticker_b))


def live_book(ledger=None, path=PATH):
    book = PaperBook(rules=(), cash_rules=CASH_RULES, ledger_path=ledger)
    for row in path:
        book.step([PAIR], {MID: quote(row)}, {"KXATPMATCH": FEES}, T0 + timedelta(seconds=row[0]))
    return book


def quotes_frame(path=PATH):
    """Recorder shape: both sides every snapshot, NaN when a side has no ask/bid."""
    rows = []
    for sec, aa, sa, ba, bsa, ab, sb, bb, bsb in path:
        ts = pd.Timestamp(T0 + timedelta(seconds=sec))
        for s, ask, size, bid, bsize, t in (("A", aa, sa, ba, bsa, PAIR.ticker_a), ("B", ab, sb, bb, bsb, PAIR.ticker_b)):
            f = lambda v: NAN if v is None else float(v)   # noqa: E731
            rows.append({"ts": ts, "match_id": MID, "venue": "kalshi", "side": s, "ask": f(ask), "ask_size": f(size),
                         "bid": f(bid), "bid_size": f(bsize), "ask_source": f"yes:{t}" if ask is not None else None,
                         "source": "orderbook"})
    return pd.DataFrame(rows)


def cashout_positions():
    cfg = copy.deepcopy(CFG)
    cfg["backtest"]["contracts_per_entry"] = 100
    paths = cash_paths(align(quotes_frame(), matches_frame()), matches_frame(), cfg)
    pos = simulate_cashout(paths, cfg, 0.0)
    return pos[pos["rule"] == "L=50c"]


# ---- the core guarantee: same trades as backtest/cashout.py on the same path -------------------

def test_live_cash_engine_matches_backtest_cashout_sim():
    book = live_book()
    book.settle(MID, *PAY, T0 + timedelta(hours=3))
    pos = cashout_positions()
    checked = 0
    for rule in CASH_RULES:
        live = {(t.entry_type, t.side): t for t in book.trades.values() if t.rule == rule.id}
        sim = pos[(pos["entry_ask"] < rule.max_ask) & pos["mode"].isin(rule.entries)]
        assert set(live) == set(zip(sim["mode"], sim["side"])), rule.id
        for r in sim.itertuples():
            t = live[(r.mode, r.side)]
            assert pd.Timestamp(t.entry_ts) == r.entry_ts and t.entry_ask == pytest.approx(r.entry_ask)
            assert t.contracts == pytest.approx(r.contracts) and t.entry_cost == pytest.approx(r.entry_cost)
            if rule.level is None:                          # control: always held
                assert t.exit_ts is None and t.pnl == pytest.approx(r.hold_pnl, abs=1e-6)
            else:
                assert bool(t.exit_ts) == bool(r.locked), rule.id
                if r.locked:
                    assert pd.Timestamp(t.exit_ts) == r.exit_ts
                    assert t.exit_value == pytest.approx(r.exit_value)
                assert t.pnl == pytest.approx(r.rule_pnl, abs=1e-6), rule.id
            checked += 1
    assert checked == 4                                     # C0 E1, C1 E1, C2 E1, C2 E2


def test_path_exercises_every_branch():
    t = live_book().trades
    c1 = t[f"{C1}:{MID}:E1:A"]
    assert c1.exit_ts == "2026-10-27T12:00:30Z"             # blocked at 20 s by bid size 50 < 100
    assert c1.exit_value == pytest.approx(100 * 0.55 - 1.74) and c1.status == "exited"
    assert t[f"{C2}:{MID}:E2:A"].exit_ts == "2026-10-27T12:10:30Z"   # 50c bid nets 48.25c: no exit at 620
    assert f"{C1}:{MID}:E2:A" not in t and f"{C0}:{MID}:E2:A" not in t     # 28c isn't a < 20c dog
    assert t[f"{C0}:{MID}:E1:A"].status == "open"           # the control never exits
    assert t[f"{C0}:{MID}:E1:A"].entry_cost == c1.entry_cost   # same entries as C1


def test_settlement_skips_exited_trades():
    book = live_book()
    assert set(book.unsettled({"other"})) == {MID}          # C0 still needs a result
    events = book.settle(MID, *PAY, T0 + timedelta(hours=3))
    assert [e["rule"] for e in events] == [C0]              # exited trades keep their sale P&L
    c0 = book.trades[f"{C0}:{MID}:E1:A"]
    assert c0.status == "settled" and c0.pnl == pytest.approx(-c0.entry_cost)
    assert book.unsettled() == {}


# ---- ledger, state, per-rule since ---------------------------------------------------------

def test_exit_event_ledger_replay_and_no_reentry(tmp_path):
    ledger = tmp_path / "paper" / "ledger.jsonl"
    book = live_book(ledger, PATH[:5])                      # through the E1 exits, still pre-match
    events = [json.loads(x)["event"] for x in ledger.read_text().splitlines()]
    assert events == ["open", "open", "open", "exit", "exit"]
    state = json.loads((tmp_path / "paper" / "paper_state.json").read_text())
    assert state["cash_seen"] == {MID: ["E1"]} and set(state["since"]) == {r.id for r in CASH_RULES}
    again = PaperBook(rules=(), cash_rules=CASH_RULES, ledger_path=ledger)
    assert {k: v.status for k, v in again.trades.items()} == {k: v.status for k, v in book.trades.items()}
    # another pre-match observation after the restart is not a new E1
    again.step([PAIR], {MID: quote(PATH[0])}, {"KXATPMATCH": FEES}, T0 + timedelta(seconds=40))
    assert len(again.trades) == 3


def test_new_rules_get_their_own_since_and_old_ones_keep_the_first_poll(tmp_path):
    """The server's ledger predates paper_state.json: P rules start at the book's first poll; C rules
    added later start at their own first poll, so their start-up entries are told apart."""
    from test_scanner_paper import live_book as swing_book
    ledger = tmp_path / "ledger.jsonl"
    swing_book(ledger)                                       # P1-P4 trades from 12:00:10
    (tmp_path / "paper_state.json").unlink()                 # the server's ledger has no state file yet
    first = min(json.loads(x)["entry_ts"] for x in ledger.read_text().splitlines())
    book = PaperBook(ledger_path=ledger)                     # now with the cash rules too
    later = T0 + timedelta(hours=1)
    book.step([PAIR], {MID: quote(PATH[5])}, {"KXATPMATCH": FEES}, later)
    rules = {r["id"]: r for r in book.summary()["rules"]}
    assert all(rules[r.id]["since"] == first for r in RULES)
    assert all(rules[r.id]["since"] == "2026-10-27T13:00:00Z" for r in CASH_RULES)
    assert {rules[r.id]["group"] for r in RULES} == {"swing"} and rules[C1]["entries"] == ["E1", "E2"]
    c2 = book.trades[f"{C2}:{MID}:E2:A"]
    assert c2.entry_ts == rules[C2]["since"]                 # a start-up entry for the C group


def test_summary_rows_for_the_cash_group():
    book = live_book()
    book.settle(MID, *PAY, T0 + timedelta(hours=3))
    by = {r["rule"]: r for r in book.summary()["by_rule"]}
    assert by[C1] == {**by[C1], "group": "cashout", "trades": 1, "locked": 1, "settled": 1, "open": 0}
    assert by[C2]["trades"] == 2 and by[C2]["locked"] == 2 and by[C0]["locked"] == 0
    c1 = book.trades[f"{C1}:{MID}:E1:A"]
    assert by[C1]["pnl_settled"] == pytest.approx(c1.exit_value - c1.entry_cost)
    assert by[C0]["pnl_settled"] < 0 < by[C1]["pnl_settled"]
    view = next(t for t in book.summary()["trades"] if t["trade_id"] == c1.trade_id)
    assert view["status"] == "exited" and view["pnl_if_a"] == view["pnl_if_b"] == view["pnl"]
    assert view["entry_type"] == "E1" and view["group"] == "cashout"


# ---- lookback ----------------------------------------------------------------------------------

def test_lookback_cash_rules_match_the_live_engine(tmp_path):
    rec = tmp_path / "recorded"
    (rec / "quotes").mkdir(parents=True)
    quotes_frame().to_parquet(rec / "quotes" / "2026-10-27.parquet", index=False)
    matches_frame().assign(winner=pd.NA, settle_a=NAN, settle_b=NAN).to_parquet(rec / "matches.parquet")
    now = T0 + timedelta(hours=8)
    s = lookback.run(CFG, rec, tmp_path / "paper", FakeClient(), now=now)
    by = {(r["rule"], r["slippage"]): r for r in s["by_rule"]}
    live = live_book()
    live.settle(MID, *PAY, now)
    for r in CASH_RULES:
        ts = [t for t in live.trades.values() if t.rule == r.id]
        row = by[(r.id, 0.0)]
        assert row["group"] == "cashout" and row["trades"] == len(ts)
        assert row["locked"] == sum(bool(t.exit_ts) for t in ts)
        assert row["pnl"] == pytest.approx(sum(t.pnl for t in ts), abs=1e-4), r.id
        assert row["contracts"] == pytest.approx(sum(t.contracts for t in ts))
    assert by[(C1, 0.01)]["pnl"] < by[(C1, 0.0)]["pnl"]       # 1c worse on both trades
    assert s["matches_processed_cashout"] == 1 and {x["group"] for x in s["rules"]} == {"swing", "cashout"}


def test_lookback_adds_cash_rules_to_matches_already_processed_for_swing(tmp_path):
    """On the server the swing lookback ran before the C rules existed: the next run must still
    simulate the C rules on those matches, without duplicating swing trades."""
    rec, out = tmp_path / "recorded", tmp_path / "paper"
    (rec / "quotes").mkdir(parents=True)
    quotes_frame().to_parquet(rec / "quotes" / "2026-10-27.parquet", index=False)
    matches_frame().assign(winner=pd.NA, settle_a=NAN, settle_b=NAN).to_parquet(rec / "matches.parquet")
    now = T0 + timedelta(hours=8)
    lookback.run(CFG, rec, out, FakeClient(), now=now)
    trades = pd.read_parquet(out / "lookback_trades.parquet")
    swing_rows = trades[trades["group"] == "swing"]
    (out / "lookback_trades.parquet").write_bytes(b"")       # simulate the pre-C state on the server
    swing_rows.to_parquet(out / "lookback_trades.parquet", index=False)
    (out / "lookback_state.json").write_text(json.dumps({"processed": [MID]}))
    s = lookback.run(CFG, rec, out, FakeClient(), now=now)
    again = pd.read_parquet(out / "lookback_trades.parquet")
    assert len(again[again["group"] == "swing"]) == len(swing_rows)
    assert len(again[again["group"] == "cashout"]) == len(trades[trades["group"] == "cashout"]) > 0
    assert s["matches_new_this_run"] == 1


def test_preregistration_doc_lists_exactly_the_coded_cash_rules():
    doc = (ROOT / "docs" / "scanner_paper.md").read_text()
    assert "Pre-registered 2026-10-28" in doc
    rows = re.findall(r"^\| `(C\d[^`]*)` \| ([\d.]+) \| (\S+) \|", doc, re.M)
    assert [(i, float(a), None if lv == "hold" else float(lv)) for i, a, lv in rows] == \
        [(r.id, r.max_ask, r.level) for r in CASH_RULES]
