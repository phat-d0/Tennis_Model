"""Order-book recorder tests: fixtures in, parquet out, no network."""

import json
from pathlib import Path

import pandas as pd
import pytest

from swinglock.collectors import recorder as rec
from swinglock.collectors.kalshi import KalshiClient, KalshiError
from swinglock.schema import QUOTE_COLUMNS, validate_quotes

FX = Path(__file__).parent / "fixtures" / "kalshi"
F, B = "KXATPMATCH-26OCT24FARBRU-FAR", "KXATPMATCH-26OCT24FARBRU-BRU"


def load(name):
    return json.loads((FX / name).read_text())


class FakeClient:
    """Stands in for KalshiClient: answers /events and /markets/orderbooks from fixtures."""

    def __init__(self, fail_books=False):
        self.calls, self.requests_made, self.rate_limited, self.fail_books = [], 0, 0, fail_books

    def series(self, ticker, max_age_s=None):
        return load("series_KXATPMATCH_2026-10-24.json")["series"]

    def get(self, path, params=None, cache=True, max_age_s=None):
        self.calls.append((path, dict(params or {})))
        self.requests_made += 1
        assert path == "/events" and params["status"] == "open"
        page = load("events_atp_match_faria_brunold_open_2026-10-24.json")
        page["milestones"] = load("milestones_atp_faria_brunold_2026-10-24.json")["milestones"]
        return page

    def orderbooks(self, tickers, depth=10):
        self.calls.append(("/markets/orderbooks", {"tickers": list(tickers), "depth": depth}))
        self.requests_made += 1
        if self.fail_books:
            raise KalshiError(500, "u")
        return {F: load("orderbook_atp_faria_brunold_FAR_depth10_2026-10-24.json")["orderbook_fp"],
                B: load("orderbook_atp_faria_brunold_BRU_depth10_2026-10-24.json")["orderbook_fp"]}


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def make(tmp_path, client=None, t0=1792836000.0):   # 2026-10-24 09:20 UTC
    clk = Clock(t0)
    r = rec.Recorder(client or FakeClient(), ["KXATPMATCH"], tmp_path, poll_s=10, discovery_s=600,
                     flush_s=60, depth=5, clock=clk, sleep=clk.sleep)
    return r, clk


def test_records_quotes_depth_and_matches(tmp_path):
    r, clk = make(tmp_path)
    r.run(duration_s=125)        # 13 polls, flushes at 60 s, 120 s and on exit
    q = pd.read_parquet(tmp_path / "quotes" / "2026-10-24")
    validate_quotes(q)
    assert list(q.columns) == list(QUOTE_COLUMNS)
    assert len(q) == 2 * r.snapshots and r.snapshots == 13
    assert (q["source"] == "orderbook").all()
    a = q[q["side"] == "A"].iloc[0]
    # same numbers as the normalizer test: ask(A=FAR) = 1 - best YES bid on BRU (.47) = .53
    assert a["ask"] == pytest.approx(0.53) and a["ask_size"] == pytest.approx(1538.02)
    assert a["ask_source"] == f"no:{B}"

    d = pd.read_parquet(tmp_path / "depth" / "2026-10-24")
    one = d[d["ts"] == d["ts"].min()]
    assert len(one) == 2 * 2 * 5     # 2 markets × yes/no × 5 levels
    far_no = one[(one["ticker"] == F) & (one["book"] == "no")].sort_values("level")
    assert far_no["price"].tolist() == pytest.approx([0.46, 0.45, 0.44, 0.43, 0.42])   # best first
    assert far_no["size"].iloc[0] == pytest.approx(21698.12)

    m = pd.read_parquet(tmp_path / "matches.parquet")
    assert m["match_id"].tolist() == ["KXATPMATCH-26OCT24FARBRU"]
    assert m["scheduled_start"].iloc[0] == pd.Timestamp("2026-10-24T10:10:00Z")   # from milestones
    assert pd.isna(m["winner"].iloc[0])


def test_request_pattern(tmp_path):
    c = FakeClient()
    r, clk = make(tmp_path, c)
    r.run(duration_s=35)
    paths = [p for p, _ in c.calls]
    assert paths.count("/events") == 1                  # discovery once per 600 s
    books = [p for p in c.calls if p[0] == "/markets/orderbooks"]
    assert len(books) == 4 and books[0][1] == {"tickers": [F, B], "depth": 5}   # both legs, one call


def test_failed_poll_writes_nothing_and_keeps_running(tmp_path):
    r, clk = make(tmp_path, FakeClient(fail_books=True))
    r.run(duration_s=25)
    assert r.snapshots == 3
    assert not (tmp_path / "quotes").exists()           # no half or empty quotes
    assert (tmp_path / "matches.parquet").exists()


def test_past_days_are_compacted(tmp_path):
    r, clk = make(tmp_path, t0=1792886000.0)            # 2026-10-24 23:13 UTC
    r.run(duration_s=2400)                              # runs past midnight
    root = tmp_path / "quotes"
    assert (root / "2026-10-24.parquet").exists() and not (root / "2026-10-24").exists()
    assert (root / "2026-10-25").is_dir()               # today stays as parts
    day1 = pd.read_parquet(root / "2026-10-24.parquet")
    day2 = pd.read_parquet(root / "2026-10-25")
    assert len(day1) + len(day2) == 2 * r.snapshots
    assert day1["ts"].max() < pd.Timestamp("2026-10-25", tz="UTC") <= day2["ts"].min()
    assert day1["ts"].is_monotonic_increasing


def test_depth_rows_handle_empty_side():
    rows = rec.depth_rows(pd.Timestamp("2026-10-24", tz="UTC"), "M", "M-A",
                          {"yes_dollars": [["0.40", "5"], ["0.41", "7"]]}, depth=5)
    assert [(r["book"], r["level"], r["price"]) for r in rows] == [("yes", 0, 0.41), ("yes", 1, 0.40)]
