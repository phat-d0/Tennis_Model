"""Dashboard: sample state.json matches the live contract, server serves page + state."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

import pytest

from swinglock.dashboard.server import SAMPLE_LOOKBACK, SAMPLE_STATE, STATIC_DIR, default_lookback, make_server
from swinglock.fees import kalshi_fee_model
from swinglock.locks import Holding, buy_cost, lock_quote

# The live state contract from CLAUDE.md (key -> allowed JSON types).
NUM, STR, NULLNUM = (int, float), (str,), (int, float, type(None))
TOP = {"generated_at": STR, "poll_seconds": NUM, "venue": STR, "matches": (list,),
       "positions": (list,), "alerts": (list,)}
MATCH = {"match_id": STR, "series": STR, "tier": STR, "player_a": STR, "player_b": STR,
         "phase": STR, "quote_ts": STR, "ask_a": NULLNUM, "ask_b": NULLNUM, "size_a": NULLNUM,
         "size_b": NULLNUM, "bid_a": NULLNUM, "bid_b": NULLNUM, "combined": NULLNUM,
         "combined_with_fees": NULLNUM, "arb_contracts": NUM, "arb_profit": NUM}
POSITION = {"match_id": STR, "player_a": STR, "player_b": STR, "contracts_a": NUM, "avg_a": NUM,
            "contracts_b": NUM, "avg_b": NUM, "pnl_if_a": NUM, "pnl_if_b": NUM,
            "lock": (dict, type(None))}
LOCK = {"side_to_buy": STR, "contracts_to_buy": NUM, "ask": NUM, "cost": NUM,
        "locked_pnl": NUM, "depth_ok": (bool,)}
ALERT = {"ts": STR, "type": STR, "match_id": STR, "message": STR, "contracts": NUM,
         "cost": NUM, "locked_pnl": NUM}


def _check(obj: dict, spec: dict, where: str) -> None:
    assert set(obj) == set(spec), f"{where}: keys differ from contract: {set(obj) ^ set(spec)}"
    for k, types in spec.items():
        assert isinstance(obj[k], types), f"{where}.{k}={obj[k]!r} has wrong type"


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


@pytest.fixture(scope="module")
def sample() -> dict:
    return json.loads(SAMPLE_STATE.read_text())


def test_sample_matches_contract(sample):
    _check({k: v for k, v in sample.items() if k != "paper"}, TOP, "state")   # `paper` is optional (Scanner)
    _iso(sample["generated_at"])
    for m in sample["matches"]:
        _check(m, MATCH, m["match_id"])
        assert m["phase"] in ("pre", "live", "unknown")
        _iso(m["quote_ts"])
    for p in sample["positions"]:
        _check(p, POSITION, p["match_id"])
        if p["lock"] is not None:
            _check(p["lock"], LOCK, p["match_id"] + ".lock")
            assert p["lock"]["side_to_buy"] in ("A", "B")
    for a in sample["alerts"]:
        _check(a, ALERT, a["match_id"])
        assert a["type"] in ("arb", "lock", "cross_venue")
        _iso(a["ts"])
    assert len(sample["alerts"]) <= 200


def test_sample_covers_display_cases(sample):
    ms = sample["matches"]
    edge = lambda m: m["arb_profit"] / m["arb_contracts"] if m["arb_contracts"] else 0  # noqa: E731
    assert any(edge(m) >= 0.005 for m in ms)                          # an open arb
    assert any(0 < edge(m) < 0.005 for m in ms)                       # a break-even one (below the alert threshold)
    assert {m["tier"] for m in ms} <= {"atp", "wta", "challenger", "itf", "other"}   # the scanner's own values
    assert any(m["ask_b"] is None and m["combined"] is None for m in ms)  # a side with no ask
    locks = [p["lock"] for p in sample["positions"]]
    assert None in locks                                              # balanced holding
    assert any(lk and lk["locked_pnl"] > 0 for lk in locks)           # profitable lock
    assert any(lk and lk["locked_pnl"] < 0 for lk in locks)           # unprofitable lock


def test_sample_worked_example_position(sample):
    """Krueger 11.44 @ 42.7c / Li 27.62 @ 54.3c, lock priced with the core math (Kalshi fees)."""
    p = next(p for p in sample["positions"] if p["player_a"] == "Mitchell Krueger")
    assert (p["contracts_a"], p["avg_a"], p["contracts_b"], p["avg_b"]) == (11.44, 0.427, 27.62, 0.543)
    m = next(m for m in sample["matches"] if m["match_id"] == p["match_id"])
    h = Holding.from_avg(11.44, 0.427, 27.62, 0.543)
    q = lock_quote(h, m["ask_a"], m["ask_b"], kalshi_fee_model("quadratic_with_maker_fees"),
                   m["size_a"], m["size_b"])
    assert p["pnl_if_a"] == pytest.approx(h.pnl_if("A"), abs=1e-6) == pytest.approx(-8.44, abs=0.01)
    assert p["pnl_if_b"] == pytest.approx(h.pnl_if("B"), abs=1e-6) == pytest.approx(7.74, abs=0.01)
    lk = p["lock"]
    assert lk["side_to_buy"] == q.side_to_buy == "A"
    assert lk["contracts_to_buy"] == pytest.approx(16.18)
    assert lk["cost"] == pytest.approx(q.cost, abs=1e-6)
    assert lk["locked_pnl"] == pytest.approx(q.locked_pnl, abs=1e-6) == pytest.approx(0.55, abs=0.01)


def test_static_is_self_contained_and_read_only():
    for f in STATIC_DIR.iterdir():
        text = f.read_text()
        text = text.replace("http://www.w3.org/2000/svg", "")   # the SVG namespace id, never fetched
        assert not re.search(r"(https?:)?//[a-z0-9.-]+\.[a-z]{2,}/", text, re.I), f"external URL in {f.name}"
        assert "kalshi.com" not in text and "polymarket.com" not in text  # never calls venue APIs
        assert not re.search(r"\b(place|submit|send)[ _-]?order|<form|method=.post", text, re.I), f.name
    html = (STATIC_DIR / "index.html").read_text()
    # no action buttons: the only buttons switch between the Live and Paper views
    buttons = re.findall(r"<button[^>]*>", html)
    assert buttons and all("data-view=" in b for b in buttons), buttons


# ---------------------------------------------------------------- paper contract (Scanner, docs/scanner_paper.md)

RULE_KEYS = {"id", "x", "y", "entry_phase", "min_entry_ask", "min_minutes_from_start", "max_minutes_from_start",
             "contracts", "mode"}
BY_RULE_KEYS = {"rule", "trades", "open", "locked", "settled", "lock_rate", "pnl_settled", "pnl_locked_unsettled",
                "capital", "contracts"}
TRADE_KEYS = {"trade_id", "rule", "match_id", "series", "tier", "player_a", "player_b", "side", "status", "entry_ts",
              "entry_phase", "entry_ask", "entry_source", "contracts", "entry_cost", "lock_ts", "lock_ask",
              "lock_source", "lock_contracts", "lock_cost", "settle_ts", "settle_a", "settle_b", "pnl", "pnl_if_a",
              "pnl_if_b"}
LB_KEYS = {"generated_at", "source", "data_from", "data_to", "matches_recorded", "matches_processed",
           "matches_with_trades", "matches_new_this_run", "matches_awaiting_result", "settlement_requests",
           "rules", "by_rule", "by_day"}
LB_RULE_KEYS = {"rule", "slippage", "trades", "locked", "lock_rate", "pnl", "pnl_per_trade", "win_rate",
                "pnl_locked", "pnl_unlocked", "capital", "contracts"}


def test_sample_paper_matches_contract(sample):
    paper = sample["paper"]
    assert set(paper) == {"since", "rules", "by_rule", "trades"}
    for r in paper["rules"]:
        assert set(r) == RULE_KEYS
    ids = [r["id"] for r in paper["rules"]]
    assert [b["rule"] for b in paper["by_rule"]] == ids
    for t in paper["trades"]:
        assert set(t) == TRADE_KEYS, t["trade_id"]
        assert t["status"] in ("open", "locked", "settled") and t["side"] in ("A", "B") and t["rule"] in ids
        assert (t["pnl"] is None) == (t["status"] == "open")
        assert (t["lock_ts"] is None) == (t["lock_ask"] is None)
    order = [t["status"] for t in paper["trades"]]
    assert order == sorted(order, key=lambda st: st == "settled")      # open/locked before settled
    for b in paper["by_rule"]:
        assert set(b) == BY_RULE_KEYS
        ts = [t for t in paper["trades"] if t["rule"] == b["rule"]]
        assert b["trades"] == len(ts)
        for st in ("open", "locked", "settled"):
            assert b[st] == sum(t["status"] == st for t in ts)
        assert b["pnl_settled"] == pytest.approx(sum(t["pnl"] for t in ts if t["status"] == "settled"))
        assert b["pnl_locked_unsettled"] == pytest.approx(sum(t["pnl"] for t in ts if t["status"] == "locked"))
    assert {t["status"] for t in paper["trades"]} == {"open", "locked", "settled"}


def test_sample_paper_trades_priced_with_core_math(sample):
    """Entry cost = ask x contracts + Kalshi taker fee; a locked trade's P&L = lock_quote's locked P&L."""
    for t in sample["paper"]["trades"]:
        fees = kalshi_fee_model("quadratic" if "CHALLENGER" in t["series"] else "quadratic_with_maker_fees")
        assert t["entry_cost"] == pytest.approx(buy_cost(t["entry_ask"], t["contracts"], fees), abs=1e-6)
        if t["lock_ask"] is not None:
            n, c = t["contracts"], t["entry_cost"]
            h = Holding(n, c, 0, 0) if t["side"] == "A" else Holding(0, 0, n, c)
            ask_a, ask_b = (0.99, t["lock_ask"]) if t["side"] == "A" else (t["lock_ask"], 0.99)
            q = lock_quote(h, ask_a, ask_b, fees)
            assert t["lock_cost"] == pytest.approx(q.cost, abs=1e-6)
            if t["status"] == "locked":
                assert t["pnl"] == pytest.approx(q.locked_pnl, abs=1e-6)


def test_sample_lookback_matches_contract():
    lb = json.loads(SAMPLE_LOOKBACK.read_text())
    assert set(lb) == LB_KEYS
    for r in lb["rules"]:
        assert set(r) == RULE_KEYS
    for b in lb["by_rule"]:
        assert set(b) == LB_RULE_KEYS and b["slippage"] in (0.0, 0.01)
    assert len(lb["by_rule"]) == 2 * len(lb["rules"])                 # one row per rule per slippage
    for d in lb["by_day"]:
        assert set(d) == {"day", "rule", "trades", "locked", "pnl"}
        datetime.strptime(d["day"], "%Y-%m-%d")


def test_default_lookback_path():
    assert default_lookback("data/live/state.json") == Path("data/paper/lookback.json")


@pytest.fixture()
def serve(tmp_path):
    servers = []

    def start(state_path: Path, lookback: Path | None = None) -> str:
        # default: a lookback that doesn't exist yet (the normal state before the first nightly run)
        httpd = make_server(state_path, "127.0.0.1", 0, lookback or tmp_path / "missing-lookback.json")
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}"

    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


def _get(url: str) -> tuple[int, str, bytes]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers["Content-Type"], r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers["Content-Type"], e.read()


def test_server_serves_page_and_state(serve, tmp_path):
    state = tmp_path / "state.json"
    shutil.copy(SAMPLE_STATE, state)
    base = serve(state)
    code, ctype, body = _get(base + "/")
    assert code == 200 and ctype.startswith("text/html") and b"app.js" in body
    for path, kind in (("/app.js", "javascript"), ("/style.css", "css")):
        code, ctype, _ = _get(base + path)
        assert code == 200 and kind in ctype
    code, ctype, body = _get(base + "/state.json?t=1")
    assert code == 200 and ctype == "application/json"
    assert json.loads(body) == json.loads(SAMPLE_STATE.read_text())

    # Re-read on every request: the scanner overwrites the file and the page sees it.
    s = json.loads(body)
    s["generated_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    state.write_text(json.dumps(s))
    assert json.loads(_get(base + "/state.json")[2])["generated_at"] == s["generated_at"]


def test_server_errors(serve, tmp_path):
    missing = serve(tmp_path / "nope.json")
    code, _, body = _get(missing + "/state.json")
    assert code == 503 and "not found" in json.loads(body)["error"]

    bad = tmp_path / "bad.json"
    bad.write_text('{"generated_at": "2026-')   # scanner caught mid-write
    code, _, body = _get(serve(bad) + "/state.json")
    assert code == 502 and "not valid JSON" in json.loads(body)["error"]

    assert _get(missing + "/../../CLAUDE.md")[0] == 404
    # lookback: 204 while the nightly job hasn't run yet, 502 when half-written, 200 when there
    state = tmp_path / "state.json"
    shutil.copy(SAMPLE_STATE, state)
    assert _get(serve(state) + "/lookback.json")[0] == 204
    lb = tmp_path / "lookback.json"
    lb.write_text("{")
    assert _get(serve(state, lb) + "/lookback.json")[0] == 502
    code, ctype, body = _get(serve(state, SAMPLE_LOOKBACK) + "/lookback.json")
    assert code == 200 and json.loads(body) == json.loads(SAMPLE_LOOKBACK.read_text())
    assert _get(missing + "/server.py")[0] == 404


def _node_playwright() -> bool:
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


def _run_check(base: str, search: str = "") -> list[dict]:
    script = Path(__file__).parents[1] / "swinglock" / "dashboard" / "check_page.js"
    r = subprocess.run(["node", str(script), base + "/", "", search],
                       capture_output=True, text=True, timeout=180)
    out = json.loads(r.stdout)
    assert r.returncode == 0 and out["problems"] == [], out["problems"] or r.stderr
    assert len(out["results"]) == 4
    return out["results"]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.skipif(not _node_playwright(), reason="needs node + playwright")
@pytest.mark.parametrize("fresh", [True, False])
def test_page_in_browser(serve, tmp_path, fresh):
    """Phone + laptop, light + dark: no page errors, no horizontal overflow, stale banner, filters."""
    s = json.loads(SAMPLE_STATE.read_text())
    if fresh:
        s["generated_at"] = _now()
    state = tmp_path / "state.json"
    state.write_text(json.dumps(s))
    for res in _run_check(serve(state), "swiatek"):
        assert res["status"] == ("ok" if fresh else "stale")
        assert res["markets"] == 5 and res["noMarket"] == 1 and res["alerts"] == 3
        assert res["arbRows"] == 1 and res["lockRows"] == 1
        assert res["breakEven"] == 1 and res["arbTile"] == "1"     # the $0.09 / 19.34 ct arb doesn't count
        assert res["tierLabels"] == ["ATP", "ATP Challenger", "WTA", "WTA 125"]
        p = res["paper"]
        assert p["liveHidden"] and p["rules"] == 4 and p["trades"] == 7 and p["locked"] == 1
        assert res["paperSettled"] == 4 and p["lookbackRows"] == 0 and not p["chart"]
        assert any("No lookback yet" in n for n in p["notes"])
        assert p["hypo"] == "Hypothetical, no orders"
        # headline excludes the two start-up entries (entry_ts == paper.since); P4's other trade is still open
        assert p["perContract"] == ["+82.0¢", "+6.6¢", "+8.0¢", "—"] and p["total"] == "+35.9¢"
        assert p["startup"] == 2 and p["startupBadges"] == 2
        assert p["intro"].startswith("Expected result (pre-registered): about −3 to −5¢ per contract.")
        assert res["firstMarket"] == "Jaime Faria vs Nicolas Brunold"   # sorted by combined + fees
        f = res["filters"]
        assert f["search"] == {"rows": 1, "noMarket": 0, "label": "1 of 6 matches"}
        assert f["pre"] == {"rows": 1, "noMarket": 0, "label": "1 of 6 matches"}
        assert f["all"] == {"rows": 5, "noMarket": 1, "label": "6 matches"}


@pytest.mark.skipif(not _node_playwright(), reason="needs node + playwright")
def test_page_with_many_matches(serve, tmp_path):
    """~100 matches (the real scanner lists 95+): still no overflow or errors; filters scale."""
    s = json.loads(SAMPLE_STATE.read_text())
    s["generated_at"] = _now()
    base = s["matches"]
    s["matches"] = []
    for i in range(100):
        m = dict(base[i % len(base)])
        m["match_id"] = f"{m['match_id']}-{i}"
        m["player_a"] = f"{m['player_a']} {i}"
        m["phase"] = ("live", "pre", "unknown")[i % 3]
        s["matches"].append(m)
    state = tmp_path / "state.json"
    state.write_text(json.dumps(s))
    no_ask = sum(1 for m in s["matches"] if m["ask_b"] is None)
    pre = [m for m in s["matches"] if m["phase"] == "pre"]
    for res in _run_check(serve(state), "krueger 4"):   # every search word must match
        assert res["markets"] == 100 - no_ask and res["noMarket"] == no_ask
        hay = [" ".join(m[k] for k in ("player_a", "player_b", "tier", "series", "match_id")).lower()
               for m in s["matches"] if m["ask_b"] is not None]
        hits = [h for h in hay if "krueger" in h and "4" in h]
        assert 0 < res["filters"]["search"]["rows"] == len(hits) < 100 - no_ask
        assert res["filters"]["pre"]["rows"] + res["filters"]["pre"]["noMarket"] == len(pre)
        assert res["filters"]["all"]["label"] == "100 matches"


@pytest.mark.skipif(not _node_playwright(), reason="needs node + playwright")
def test_arb_threshold_from_state(serve, tmp_path):
    """If the scanner sends `min_arb_profit_per_contract`, the page uses it instead of the config default."""
    s = json.loads(SAMPLE_STATE.read_text())
    s["generated_at"] = _now()
    s["min_arb_profit_per_contract"] = 0.004     # the Bonardi-Souza arb (0.48c/ct) now clears it
    state = tmp_path / "state.json"
    state.write_text(json.dumps(s))
    for res in _run_check(serve(state)):
        assert res["arbRows"] == 2 and res["breakEven"] == 0 and res["arbTile"] == "2"


def _fresh(dt_hours_ago: float = 0) -> str:
    from datetime import timedelta
    return (datetime.now(UTC) - timedelta(hours=dt_hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.mark.skipif(not _node_playwright(), reason="needs node + playwright")
def test_paper_tab_with_lookback(serve, tmp_path):
    """Lookback present: per-rule rows (0c and 1c), last 14 days; an old run gets a warning."""
    s = json.loads(SAMPLE_STATE.read_text())
    s["generated_at"] = _now()
    state = tmp_path / "state.json"
    state.write_text(json.dumps(s))
    lb = json.loads(SAMPLE_LOOKBACK.read_text())
    lb["generated_at"] = _fresh(3)
    lbf = tmp_path / "lookback.json"
    lbf.write_text(json.dumps(lb))
    for res in _run_check(serve(state, lbf)):
        p = res["paper"]
        assert p["lookbackRows"] == len(lb["rules"]) and p["days"] == 14 and p["notes"] == []
        assert p["chart"] and p["chartLines"] == len(lb["rules"])
        assert "—" not in p["lbPerCt"] and not any("needs a `contracts` total" in m for m in p["metaLines"])
    want = [f"{'+' if b['pnl'] > 0 else '−'}{abs(b['pnl'] / b['contracts'] * 100):.1f}¢"
            for b in lb["by_rule"] if b["slippage"] == 0.0]
    for res in _run_check(serve(state, lbf)):
        assert res["paper"]["lbPerCt"] == want
    # an older lookback without `contracts`: dashes and a note
    for b in lb["by_rule"]:
        b.pop("contracts")
    lbf.write_text(json.dumps(lb))
    for res in _run_check(serve(state, lbf)):
        assert set(res["paper"]["lbPerCt"]) == {"—"}
        assert any("needs a `contracts` total" in m for m in res["paper"]["metaLines"])
    lb["generated_at"] = _fresh(60)
    lbf.write_text(json.dumps(lb))
    for res in _run_check(serve(state, lbf)):
        assert any("nightly run may have failed" in n for n in res["paper"]["notes"])


@pytest.mark.skipif(not _node_playwright(), reason="needs node + playwright")
def test_paper_tab_without_paper_key(serve, tmp_path):
    """Scanner run with --no-paper: the tab says so and stays usable."""
    s = json.loads(SAMPLE_STATE.read_text())
    s["generated_at"] = _now()
    s.pop("paper")
    state = tmp_path / "state.json"
    state.write_text(json.dumps(s))
    for res in _run_check(serve(state)):
        p = res["paper"]
        assert p["rules"] == 0 and p["trades"] == 0
        assert any("isn't paper trading" in n for n in p["notes"])


# ---------------------------------------------------------------- Scanner's own synthetic output

def _scanner_samples(tmp_path) -> tuple[dict, dict]:
    """state.paper and lookback.json produced by Scanner's code from its synthetic test fixtures
    (tests/test_scanner_paper.py; no Kalshi data). If Scanner renames a field, these tests fail."""
    import importlib.util
    from datetime import timedelta

    import pandas as pd

    from swinglock.scanner import lookback

    spec = importlib.util.spec_from_file_location("tsp", Path(__file__).parent / "test_scanner_paper.py")
    tsp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tsp)
    paper = tsp.live_book().summary()
    rec = tmp_path / "recorded"
    (rec / "quotes").mkdir(parents=True)
    tsp.quotes_frame().to_parquet(rec / "quotes" / "2026-10-27.parquet", index=False)
    tsp.matches_frame().assign(winner=pd.NA, settle_a=float("nan"), settle_b=float("nan")).to_parquet(
        rec / "matches.parquet", index=False)
    lb = lookback.run(tsp.CFG, rec, tmp_path / "paper", tsp.FakeClient(), now=tsp.T0 + timedelta(hours=8))
    return json.loads(json.dumps(paper)), json.loads((tmp_path / "paper" / "lookback.json").read_text()) or lb


def test_contract_matches_scanner_output(sample, tmp_path):
    paper, lb = _scanner_samples(tmp_path)
    mine = sample["paper"]
    assert set(paper) == set(mine)
    assert set(paper["rules"][0]) == set(mine["rules"][0]) == RULE_KEYS
    assert set(paper["by_rule"][0]) == set(mine["by_rule"][0]) == BY_RULE_KEYS
    assert set(paper["trades"][0]) == set(mine["trades"][0]) == TRADE_KEYS
    assert [r["id"] for r in paper["rules"]] == [r["id"] for r in mine["rules"]]   # same frozen rules
    mine_lb = json.loads(SAMPLE_LOOKBACK.read_text())
    assert set(lb) == set(mine_lb) == LB_KEYS
    assert set(lb["by_rule"][0]) == set(mine_lb["by_rule"][0]) == LB_RULE_KEYS
    assert set(lb["by_day"][0]) == set(mine_lb["by_day"][0])


@pytest.mark.skipif(not _node_playwright(), reason="needs node + playwright")
def test_paper_tab_on_scanner_output(serve, tmp_path):
    """The page on Scanner's real code output: P2's only trade is a start-up entry, so it's split out."""
    paper, lb = _scanner_samples(tmp_path)
    s = json.loads(SAMPLE_STATE.read_text())
    s["generated_at"] = _now()
    s["paper"] = paper
    state = tmp_path / "state.json"
    state.write_text(json.dumps(s))
    lbf = tmp_path / "lb.json"
    lbf.write_text(json.dumps(lb))
    for res in _run_check(serve(state, lbf)):
        p = res["paper"]
        assert p["rules"] == 4 and p["trades"] == len(paper["trades"]) and p["startup"] == 1
        assert p["perContract"] == ["+21.2¢", "—", "+15.0¢", "+11.9¢"] and p["total"] == "+16.0¢"
        assert p["lookbackRows"] == 4 and p["chart"]
