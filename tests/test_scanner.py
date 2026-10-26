"""Scanner tests: effective quotes from real fixtures, positions → locks (worked example),
replay through the scan loop with alert de-duplication, state.json contract, read-only checks."""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from swinglock.config import load_config
from swinglock.fees import FeeModel
from swinglock.positions import PositionRow
from swinglock.scanner.client import KalshiReadClient
from swinglock.scanner.engine import Engine, Settings, holdings_from_positions
from swinglock.scanner.market import MatchPair, match_quote, pairs_from_events
from swinglock.scanner.output import AlertSink, StateWriter
from swinglock.scanner.run import Scanner

FIX = Path(__file__).parent / "fixtures" / "kalshi"
PKG = Path(__file__).resolve().parent.parent / "swinglock"
KALSHI = FeeModel(taker_rate=0.07, maker_rate=0.0175, rounding_increment=0.01)
T0 = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)
EVENT = "KXATPMATCH-26OCT24FARBRU"
FAR, BRU = EVENT + "-FAR", EVENT + "-BRU"


def fixture(name):
    return json.loads((FIX / name).read_text())


def book(yes=(), no=()):
    """Orderbook in API shape from (price, size) bid levels, any order."""
    fmt = lambda lv: [[f"{p:.4f}", f"{s:.2f}"] for p, s in sorted(lv)]
    return {"yes_dollars": fmt(yes), "no_dollars": fmt(no)}


# ---- discovery + effective quotes ------------------------------------------

def test_pairs_from_real_event_and_milestone():
    events = fixture("events_atp_match_faria_brunold_open_2026-10-24.json")["events"]
    ms = fixture("milestones_atp_faria_brunold_2026-10-24.json")["milestones"]
    (p,) = pairs_from_events(events, ms)
    assert (p.match_id, p.series, p.tier, p.tournament) == (EVENT, "KXATPMATCH", "atp", "ATP Basel")
    # A = first ticker sorted: BRU < FAR
    assert (p.ticker_a, p.ticker_b) == (BRU, FAR)
    assert p.player_b == "Jaime Faria"
    assert p.scheduled_start == datetime(2026, 10, 24, 10, 10, tzinfo=timezone.utc)
    assert p.phase(T0) == "pre" and p.phase(T0 + timedelta(hours=2)) == "live"
    assert pairs_from_events(events)[0].phase(T0) == "unknown"


def test_effective_ask_from_real_orderbooks():
    events = fixture("events_atp_match_faria_brunold_open_2026-10-24.json")["events"]
    (p,) = pairs_from_events(events)
    books = {FAR: fixture("orderbook_atp_faria_brunold_FAR_depth10_2026-10-24.json")["orderbook_fp"],
             BRU: fixture("orderbook_atp_faria_brunold_BRU_depth10_2026-10-24.json")["orderbook_fp"]}
    q = match_quote(p, books)
    # FAR: YES bid .53, NO bid .46; BRU: YES bid .47, NO bid .52 (research doc §7)
    # ask(BRU) = min(YES BRU = 1-.52, NO FAR = 1-.53) = .47 via NO on FAR
    assert q.a.ask == pytest.approx(0.47) and q.a.ask_source == f"no:{FAR}"
    assert q.a.ask_size == float(books[FAR]["yes_dollars"][-1][1])
    # ask(FAR) = min(YES FAR = 1-.46, NO BRU = 1-.47) = .53 via NO on BRU
    assert q.b.ask == pytest.approx(0.53) and q.b.ask_source == f"no:{BRU}"
    # bid(FAR) = max(YES bid FAR .53, NO bid BRU .52)
    assert q.b.bid == pytest.approx(0.53)
    assert q.a.ask + q.b.ask == pytest.approx(1.00)


def test_ask_prefers_cheaper_leg_and_handles_empty_side():
    p = MatchPair("E", "KXATPMATCH", "atp", "", "A", "B", "E-A", "E-B")
    q = match_quote(p, {"E-A": book(no=[(0.58, 10)]), "E-B": book()})
    assert q.a.ask == pytest.approx(0.42) and q.a.ask_source == "yes:E-A"
    assert q.b.ask is None and q.b.bid == pytest.approx(0.58)   # NO bid on A = bid for B
    assert match_quote(p, {"E-A": book()}) is None


# ---- positions + worked example ----------------------------------------------

KL = MatchPair("KXATPMATCH-26OCT24KRULI", "KXATPMATCH", "atp", "", "Krueger", "Li",
               "KXATPMATCH-26OCT24KRULI-KRU", "KXATPMATCH-26OCT24KRULI-LI")
KL_ROWS = [PositionRow(KL.match_id, KL.ticker_a, 11.44, 0.427),
           PositionRow(KL.match_id, "Li", 27.62, 0.543)]


def kl_books(ask_kru=0.427, ask_li=0.60, depth=1000.0):
    # YES ask on KRU = 1 - NO bid on KRU; YES ask on LI = 1 - NO bid on LI; keep NO legs pricier
    return {KL.ticker_a: book(no=[(1 - ask_kru, depth)], yes=[(0.01, 1)]),
            KL.ticker_b: book(no=[(1 - ask_li, depth)], yes=[(0.01, 1)])}


def test_positions_map_by_ticker_name_and_letter():
    h = holdings_from_positions(KL_ROWS + [PositionRow(KL.match_id, "a", 1, 0.5),
                                           PositionRow(KL.match_id, "nobody", 5, 0.5)], {KL.match_id: KL})
    assert h[KL.match_id].contracts_a == pytest.approx(12.44)
    assert h[KL.match_id].contracts_b == pytest.approx(27.62)


def test_worked_example_lock_alert():
    eng = Engine(Settings(min_lock_profit=0.05))
    holdings = holdings_from_positions(KL_ROWS, {KL.match_id: KL})
    res = eng.step([KL], {KL.match_id: match_quote(KL, kl_books())}, {"KXATPMATCH": KALSHI}, holdings, T0)
    (pos,) = res.positions
    assert pos["pnl_if_a"] == pytest.approx(-8.44, abs=0.01)
    assert pos["pnl_if_b"] == pytest.approx(7.74, abs=0.01)
    lock = pos["lock"]
    assert lock["side_to_buy"] == "A"
    assert lock["contracts_to_buy"] == pytest.approx(16.18)
    assert lock["cost"] == pytest.approx(16.18 * 0.427 + 0.28, abs=1e-6)
    assert lock["locked_pnl"] == pytest.approx(0.83 - 0.28, abs=0.015)
    assert lock["depth_ok"] is True
    (a,) = res.alerts
    assert a["type"] == "lock" and a["contracts"] == pytest.approx(16.18)
    assert "buy 16.18 A (Krueger) @ 42.7c" in a["message"] and "locked P&L $0.5" in a["message"]


def test_lock_below_threshold_or_short_depth():
    holdings = holdings_from_positions(KL_ROWS, {KL.match_id: KL})
    eng = Engine(Settings(min_lock_profit=1.00))
    res = eng.step([KL], {KL.match_id: match_quote(KL, kl_books())}, {"KXATPMATCH": KALSHI}, holdings, T0)
    assert res.alerts == [] and res.positions[0]["lock"]["locked_pnl"] > 0
    eng = Engine(Settings())
    res = eng.step([KL], {KL.match_id: match_quote(KL, kl_books(depth=5))}, {"KXATPMATCH": KALSHI}, holdings, T0)
    assert res.positions[0]["lock"]["depth_ok"] is False
    assert "DEPTH SHORT" in res.alerts[0]["message"]


# ---- replay through the loop -------------------------------------------------

class FakeClient:
    """Serves the real Faria/Brunold event + series fixtures and a scripted book sequence."""

    def __init__(self, snapshots):
        self.snapshots = list(snapshots)
        self.calls = []
        self.events = fixture("events_atp_match_faria_brunold_open_2026-10-24.json")["events"]
        self.milestones = fixture("milestones_atp_faria_brunold_2026-10-24.json")["milestones"]

    def series(self, s):
        self.calls.append(("series", s))
        return fixture("series_KXATPMATCH_2026-10-24.json")["series"]

    def open_events(self, s):
        self.calls.append(("events", s))
        return (self.events, self.milestones) if s == "KXATPMATCH" else ([], [])

    def orderbooks(self, tickers):
        self.calls.append(("orderbooks", tuple(tickers)))
        return self.snapshots.pop(0)


def fb(ask_bru, ask_far, size=50.0):
    """Faria/Brunold books where the cheapest leg for each side is YES on its own market."""
    return {BRU: book(no=[(1 - ask_bru, size)], yes=[(0.02, 1)]),
            FAR: book(no=[(1 - ask_far, size)], yes=[(0.02, 1)])}


@pytest.fixture
def make_scanner(tmp_path):
    def make(snapshots, positions=None, **scanner_cfg):
        cfg = load_config()
        cfg["scanner"].update(scanner_cfg)
        pos = tmp_path / "positions.json"
        if positions is not None:
            pos.write_text(json.dumps(positions))
        clock = {"t": T0}
        sc = Scanner(cfg, FakeClient(snapshots), positions_path=pos,
                     sink=AlertSink(tmp_path / "alerts.log", stream=None),
                     state=StateWriter(tmp_path / "live" / "state.json", cfg["scanner"]["poll_seconds"]),
                     now=lambda: clock["t"])

        def advance(seconds=5):
            clock["t"] += timedelta(seconds=seconds)
        return sc, advance
    return make


def run_ticks(sc, advance, n):
    sc.load_fees()
    out = []
    for _ in range(n):
        out.append(sc.tick())
        advance()
    return out


def test_replay_arb_episodes(make_scanner, tmp_path):
    snaps = [fb(0.48, 0.53),   # 1.01: nothing
             fb(0.45, 0.50),   # 0.95: arb, new alert
             fb(0.45, 0.50),   # same: no repeat
             fb(0.46, 0.50),   # still arb but smaller: no repeat
             fb(0.40, 0.50),   # bigger profit: improved alert
             fb(0.48, 0.53),   # gone
             fb(0.45, 0.50),   # back within the 30 s gap: same episode, no alert
             *[fb(0.48, 0.53)] * 7,   # gone for > 30 s: episode ends
             fb(0.45, 0.50)]   # new episode: new alert
    sc, advance = make_scanner(snaps)
    results = run_ticks(sc, advance, len(snaps))
    alerts = [(i, a["message"].split(" ")[0] + (" improved" if "improved" in a["message"] else ""))
              for i, r in enumerate(results) for a in r.alerts]
    assert alerts == [(1, "ARB"), (4, "ARB improved"), (14, "ARB")]
    first = results[1].alerts[0]
    # 50 x (.45 + .50) + fees round_up(.07*50*.45*.55)=.87 + round_up(.07*50*.5*.5)=.88
    assert first["contracts"] == 50 and first["cost"] == pytest.approx(47.5 + 0.87 + 0.88)
    assert first["locked_pnl"] == pytest.approx(50 - 49.25)
    assert f"via yes:{BRU}" in first["message"] and "[depth 50.00]" in first["message"]
    log_lines = (tmp_path / "alerts.log").read_text().splitlines()
    assert len(log_lines) == 3 and log_lines[0].startswith(first["ts"] + " [arb] ARB ")
    # only one orderbooks call per tick, discovery once (one call per series), fees once
    kinds = [c[0] for c in sc.client.calls]
    assert kinds.count("orderbooks") == len(snaps)
    assert kinds.count("events") == kinds.count("series") == len(sc.cfg["scanner"]["series"])


def test_poll_interval_stretches_to_stay_under_max_rps():
    assert Scanner.interval(5, 1, 0.5) == 5          # 1 call per 5 s = 0.2 req/s: no stretch
    assert Scanner.interval(5, 6, 0.5) == 12         # 250 matches = 6 calls -> 12 s per tick
    assert Scanner.interval(5, 6, 0) == 5            # cap off


def test_run_loop_respects_max_rps_and_reports_real_interval(make_scanner):
    class Counting(FakeClient):           # every endpoint call counts as one request, like the client
        requests_made = 0

        def series(self, s):
            self.requests_made += 1
            return super().series(s)

        def open_events(self, s):
            self.requests_made += 1
            return super().open_events(s)

        def orderbooks(self, tickers):
            self.requests_made += 1
            return super().orderbooks(tickers)

    sc, _ = make_scanner([fb(0.48, 0.53)] * 3, max_rps=0.5, poll_seconds=5)
    sc.client = Counting([fb(0.48, 0.53)] * 3)
    sc.cfg["scanner"]["series"] = ["KXATPMATCH", "KXWTAMATCH"]
    sleeps = []
    sc.run(sleep=sleeps.append, max_ticks=3)
    # tick 1: 2 events calls (discovery) + 1 orderbooks = 3 calls -> 6 s; then 1 call -> 5 s
    assert [round(x) for x in sleeps] == [6, 5]
    assert sc.state.poll_seconds == 5


def test_replay_small_edge_below_threshold(make_scanner):
    # .49 + .50 = .99 but fees (~1.75c per pair) eat it: no arb
    sc, advance = make_scanner([fb(0.49, 0.50)])
    (r,) = run_ticks(sc, advance, 1)
    assert r.alerts == [] and r.matches[0]["arb_contracts"] == 0.0


def test_replay_lock_on_positions_and_state_contract(make_scanner, tmp_path):
    positions = [{"market": EVENT, "side": FAR, "contracts": 20, "avg_price": 0.40},
                 {"market": EVENT, "side": "Brunold", "contracts": 0, "avg_price": 0}]
    # Holding 20 Faria @ .40. Brunold ask .60 -> 20*.6 + fee .34 = 12.34; locked 20-8-12.34 < 0
    # Brunold ask .50 -> 10 + .35 fee; locked 20 - 8 - 10.35 = 1.65 -> alert
    sc, advance = make_scanner([fb(0.60, 0.42), fb(0.50, 0.52), fb(0.50, 0.52)], positions=positions)
    sc.cfg["scanner"]["series"] = ["KXATPMATCH"]
    results = run_ticks(sc, advance, 3)
    assert [len(r.alerts) for r in results] == [0, 1, 0]
    a = results[1].alerts[0]
    assert a["type"] == "lock" and a["contracts"] == 20
    assert a["locked_pnl"] == pytest.approx(20 - 8 - 10 - 0.35)
    state = json.loads((tmp_path / "live" / "state.json").read_text())
    # exact key sets from the CLAUDE.md live-state contract
    assert set(state) == {"generated_at", "poll_seconds", "venue", "matches", "positions", "alerts"}
    assert state["venue"] == "kalshi" and state["generated_at"].endswith("Z")
    assert set(state["matches"][0]) == {
        "match_id", "series", "tier", "player_a", "player_b", "phase", "quote_ts", "ask_a", "ask_b",
        "size_a", "size_b", "bid_a", "bid_b", "combined", "combined_with_fees", "arb_contracts", "arb_profit"}
    assert state["matches"][0]["phase"] == "pre"
    (pos,) = state["positions"]
    assert set(pos) == {"match_id", "player_a", "player_b", "contracts_a", "avg_a", "contracts_b", "avg_b",
                        "pnl_if_a", "pnl_if_b", "lock"}
    assert set(pos["lock"]) == {"side_to_buy", "contracts_to_buy", "ask", "cost", "locked_pnl", "depth_ok"}
    assert pos["lock"]["side_to_buy"] == "A"     # A = Brunold
    assert set(state["alerts"][0]) == {"ts", "type", "match_id", "message", "contracts", "cost", "locked_pnl"}


def test_state_keeps_newest_200_alerts_across_restart(tmp_path):
    from swinglock.scanner.engine import StepResult
    w = StateWriter(tmp_path / "state.json", 5)
    mk = lambda i: {"ts": str(i), "type": "arb", "match_id": "M", "message": "", "contracts": 1.0,
                    "cost": 0.9, "locked_pnl": 0.1}
    w.write(StepResult([], [], [mk(i) for i in range(250)]), T0)
    w2 = StateWriter(tmp_path / "state.json", 5)
    state = w2.write(StepResult([], [], [mk(250)]), T0)
    assert len(state["alerts"]) == 200
    assert state["alerts"][0]["ts"] == "250" and state["alerts"][-1]["ts"] == "51"


# ---- client: read-only, throttled, backs off ------------------------------------

class FakeResp:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, responses):
        self.responses, self.urls = list(responses), []

    def get(self, url, params=None, timeout=None):
        self.urls.append(url)
        return self.responses.pop(0)


def test_client_backs_off_on_429_and_spaces_requests():
    t = {"now": 0.0}
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        t["now"] += s
    sess = FakeSession([FakeResp(429), FakeResp(429), FakeResp(200, {"orderbooks": []}),
                        FakeResp(200, {"orderbooks": []})])
    c = KalshiReadClient(session=sess, sleep=sleep, clock=lambda: t["now"], min_interval=1.0)
    c.orderbooks(["X"])
    assert sleeps == [2.0, 4.0]          # exponential backoff, no Retry-After
    c.orderbooks(["X"])
    assert c.requests_made == 4 and sleeps == [2.0, 4.0, 1.0]   # min spacing between calls


def test_client_refuses_portfolio_paths_and_has_no_write_methods():
    c = KalshiReadClient(session=FakeSession([]))
    with pytest.raises(PermissionError):
        c.get("/portfolio/orders")
    for name in ("post", "put", "patch", "delete", "create_order", "cancel_order"):
        assert not hasattr(c, name)


def test_no_order_placement_anywhere_in_package():
    """Read-only rule: no write HTTP verbs, no order/portfolio endpoints, no signing of
    write requests anywhere in swinglock/."""
    banned = [
        r"\.\s*(post|put|patch|delete)\s*\(",                 # requests.post(...), session.delete(...)
        r"""request\s*\(\s*["'](POST|PUT|PATCH|DELETE)""",  # session.request("POST", ...)
        r"""method\s*=\s*["'](POST|PUT|PATCH|DELETE)""",
        r"/orders\b", r"/portfolio\b", r"batched", r"amend", r"create_order", r"place_order",
        r"KALSHI-ACCESS-SIGNATURE",                          # signed requests (WS will need review)
    ]
    hits = []
    for f in PKG.rglob("*.py"):
        src = f.read_text()
        for pat in banned:
            for m in re.finditer(pat, src, re.IGNORECASE):
                hits.append(f"{f.relative_to(PKG)}: {m.group(0)!r}")
    assert hits == []
