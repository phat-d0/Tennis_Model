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

from swinglock.dashboard.server import SAMPLE_STATE, STATIC_DIR, make_server
from swinglock.fees import kalshi_fee_model
from swinglock.locks import Holding, lock_quote

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
    _check(sample, TOP, "state")
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
        assert not re.search(r"(https?:)?//[a-z0-9.-]+\.[a-z]{2,}/", text, re.I), f"external URL in {f.name}"
        assert "kalshi.com" not in text and "polymarket.com" not in text  # never calls venue APIs
        assert not re.search(r"\b(place|submit|send)[ _-]?order|<form|method=.post", text, re.I), f.name
    html = (STATIC_DIR / "index.html").read_text()
    assert "<button" not in html  # no action buttons at all; only sort/theme selects


@pytest.fixture()
def serve(tmp_path):
    servers = []

    def start(state_path: Path) -> str:
        httpd = make_server(state_path, "127.0.0.1", 0)
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
