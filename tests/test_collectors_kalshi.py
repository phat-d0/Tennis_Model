"""Kalshi client + normalizer tests on real (trimmed) fixtures in tests/fixtures/kalshi/."""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from swinglock.collectors import backfill
from swinglock.collectors.kalshi import KalshiClient, KalshiError
from swinglock.collectors.kalshi_normalize import (
    candles_to_quotes, fee_in_effect, match_row, matches_frame, order_markets, orderbooks_to_quotes, ts,
)
from swinglock.schema import MATCH_COLUMNS, QUOTE_COLUMNS, validate_quotes

FX = Path(__file__).parent / "fixtures" / "kalshi"


def load(name):
    return json.loads((FX / name).read_text())


SERIES = load("series_KXATPMATCH_2026-10-24.json")["series"]
FEE_CHANGES = [{"fee_multiplier": 1, "fee_type": "quadratic_with_maker_fees",
                "scheduled_ts": "2025-11-15T08:00:00Z", "series_ticker": "KXATPMATCH"}]
VANMUS = load("events_atp_match_vanassche_musetti_settled_2026-10-23.json")["events"][0]
FARBRU = load("events_atp_match_faria_brunold_open_2026-10-24.json")["events"][0]
VAN, MUS = "KXATPMATCH-26OCT23VANMUS-VAN", "KXATPMATCH-26OCT23VANMUS-MUS"


# -- matches ---------------------------------------------------------------------------
def test_settled_match_row():
    row = match_row(VANMUS, VANMUS["markets"], SERIES, FEE_CHANGES, "2026-10-23T21:05:00Z")
    assert row["match_id"] == "KXATPMATCH-26OCT23VANMUS"
    assert (row["player_a"], row["player_b"]) == ("Luca Van Assche", "Lorenzo Musetti")
    assert (row["instrument_a"], row["instrument_b"]) == (VAN, MUS)
    assert row["winner"] == "B"  # Musetti won (MUS result yes, VAN no)
    assert (row["series"], row["tier"], row["tournament"]) == ("KXATPMATCH", "atp", "ATP Lyon")
    assert (row["fee_type"], row["fee_multiplier"]) == ("quadratic_with_maker_fees", 1.0)
    assert row["close_time"] == pd.Timestamp("2026-10-23T23:20:55Z")
    assert row["open_time"] == pd.Timestamp("2026-10-22T18:16:00Z")
    assert row["scheduled_start"] == pd.Timestamp("2026-10-23T21:05:00Z")
    df = matches_frame([row])
    assert list(df.columns) == list(MATCH_COLUMNS)


def test_historical_market_row_and_winner_a():
    mk = load("historical_markets_atp_match_2026-08-24.json")["markets"]
    event = {"event_ticker": "KXATPMATCH-26AUG24SONHER", "series_ticker": "KXATPMATCH",
             "product_metadata": {"competition": "ATP Winston Salem"}}
    row = match_row(event, mk, SERIES, FEE_CHANGES)
    assert (row["player_a"], row["player_b"]) == ("Lorenzo Sonego", "Pierre-Hugues Herbert")
    assert row["winner"] == "A"
    assert pd.isna(row["scheduled_start"])


def test_market_order_follows_event_ticker_not_list_order():
    a, b = order_markets(FARBRU["event_ticker"], list(reversed(FARBRU["markets"])))
    assert (a["ticker"], b["ticker"]) == ("KXATPMATCH-26OCT24FARBRU-FAR", "KXATPMATCH-26OCT24FARBRU-BRU")


def test_open_match_has_no_winner():
    row = match_row(FARBRU, FARBRU["markets"], SERIES, FEE_CHANGES)
    assert pd.isna(row["winner"])


def test_fair_price_settlement_is_not_a_winner():
    ma, mb = (dict(m) for m in VANMUS["markets"])
    ma.update(result="yes", settlement_value_dollars="0.4200")
    mb.update(result="no", settlement_value_dollars="0.5800")
    assert pd.isna(match_row(VANMUS, [ma, mb], SERIES, FEE_CHANGES)["winner"])


def test_fee_type_follows_fee_history():
    before = fee_in_effect(SERIES, FEE_CHANGES, ts("2025-06-01T00:00:00Z"))
    after = fee_in_effect(SERIES, FEE_CHANGES, ts("2026-01-01T00:00:00Z"))
    assert before == ("quadratic", 1.0)
    assert after == ("quadratic_with_maker_fees", 1.0)
    ev = {"fee_type_override": "quadratic", "fee_multiplier_override": 0.5}
    assert fee_in_effect(SERIES, FEE_CHANGES, ts("2026-01-01T00:00:00Z"), ev) == ("quadratic", 0.5)


# -- quotes from candles --------------------------------------------------------------
def vanmus_candle_quotes():
    batch = {m["market_ticker"]: m["candlesticks"]
             for m in load("candlesticks_batch_1m_atp_vanassche_musetti_2026-10-23.json")["markets"]}
    return candles_to_quotes("KXATPMATCH-26OCT23VANMUS", VAN, MUS, batch[VAN], batch[MUS])


def q_at(q, t, side):
    r = q[(q["ts"] == pd.Timestamp(t, unit="s", tz="UTC")) & (q["side"] == side)]
    assert len(r) == 1
    return r.iloc[0]


def test_candle_quotes_effective_ask_and_bid():
    q = vanmus_candle_quotes()
    validate_quotes(q)
    assert list(q.columns) == list(QUOTE_COLUMNS)
    assert len(q) == 4 and set(q["source"]) == {"candle"}
    # 1792789200: VAN yes bid .20 / ask .21; MUS yes bid .78 / ask .79
    a = q_at(q, 1792789200, "A")
    assert a["ask"] == pytest.approx(0.21) and a["ask_source"] == f"yes:{VAN}"   # .21 < 1-.78
    assert a["bid"] == pytest.approx(0.21)                                       # max(.20, 1-.79)
    b = q_at(q, 1792789200, "B")
    assert b["ask"] == pytest.approx(0.79) and b["ask_source"] == f"yes:{MUS}"   # .79 < 1-.20
    assert b["bid"] == pytest.approx(0.79)                                       # max(.78, 1-.21)
    # 1792789260: VAN .17/.18, MUS .82/.83 → YES on A and NO on B both cost .18
    a = q_at(q, 1792789260, "A")
    assert a["ask"] == pytest.approx(0.18) and a["ask_source"] == f"yes:{VAN}|no:{MUS}"
    assert q["ask_size"].isna().all() and q["bid_size"].isna().all()  # candles carry no size


def test_candle_quotes_take_no_trade_prices():
    """The 'price' block (trades) must never leak into ask/bid: blank it and nothing changes."""
    raw = load("candlesticks_batch_1m_atp_vanassche_musetti_2026-10-23.json")["markets"]
    stripped = {m["market_ticker"]: [{**c, "price": {}} for c in m["candlesticks"]] for m in raw}
    q2 = candles_to_quotes("KXATPMATCH-26OCT23VANMUS", VAN, MUS, stripped[VAN], stripped[MUS])
    pd.testing.assert_frame_equal(vanmus_candle_quotes(), q2)


def test_historical_candles_one_leg_missing_stays_nan():
    son = load("historical_candlesticks_1m_atp_sonego_herbert_SON_2026-08-24.json")["candlesticks"]
    q = candles_to_quotes("KXATPMATCH-26AUG24SONHER", "KXATPMATCH-26AUG24SONHER-SON",
                          "KXATPMATCH-26AUG24SONHER-HER", son, [])
    a, b = q_at(q, 1787604000, "A"), q_at(q, 1787604000, "B")
    # historical field names (no _dollars suffix): SON yes bid .53, yes ask .72
    assert a["ask"] == pytest.approx(0.72) and a["bid"] == pytest.approx(0.53)
    assert b["ask"] == pytest.approx(0.47) and b["ask_source"] == "no:KXATPMATCH-26AUG24SONHER-SON"
    assert b["bid"] == pytest.approx(0.28)


def test_sparse_candles_carry_forward_only_after_first_candle():
    def c(t, yb, ya):
        return {"end_period_ts": t, "yes_bid": {"close_dollars": yb}, "yes_ask": {"close_dollars": ya}}
    ca = [c(60, "0.40", "0.42"), c(180, "0.45", "0.47")]
    cb = [c(120, "0.55", "0.57")]
    q = candles_to_quotes("M", "M-A", "M-B", ca, cb)
    assert sorted(q["ts"].unique()) == [pd.Timestamp(t, unit="s", tz="UTC") for t in (60, 120, 180)]
    # t=60: B has no candle yet → only A's own YES ask counts
    assert q_at(q, 60, "A")["ask"] == pytest.approx(0.42)
    assert math.isnan(q_at(q, 60, "B")["ask"]) is False  # NO on A: 1 - .40
    assert q_at(q, 60, "B")["ask_source"] == "no:M-A"
    # t=120: A carried from t=60 (.40/.42), B .55/.57 → ask(A) = min(.42, 1-.55=.45)
    assert q_at(q, 120, "A")["ask"] == pytest.approx(0.42)
    assert q_at(q, 120, "B")["ask"] == pytest.approx(0.57)  # min(.57, 1-.40=.60)
    # t=180: A .45/.47, B carried .55/.57 → ask(A)=min(.47, .45)=.45 via NO on B
    a = q_at(q, 180, "A")
    assert a["ask"] == pytest.approx(0.45) and a["ask_source"] == "no:M-B"


def test_no_ask_or_bid_levels_become_nan():
    def c(t, yb, ya):
        return {"end_period_ts": t, "yes_bid": {"close_dollars": yb}, "yes_ask": {"close_dollars": ya}}
    # A: no bids (0) and no offers (1.00); B: no bids and no offers either
    q = candles_to_quotes("M", "M-A", "M-B", [c(60, "0.0000", "1.0000")], [c(60, "0.0000", "1.0000")])
    assert q["ask"].isna().all() and q["bid"].isna().all()
    assert q["ask_source"].isna().all()


def test_candles_after_close_are_dropped():
    def c(t):
        return {"end_period_ts": t, "yes_bid": {"close_dollars": "0.5"}, "yes_ask": {"close_dollars": "0.52"}}
    q = candles_to_quotes("M", "M-A", "M-B", [c(60), c(120), c(600)], [c(60)], until=pd.Timestamp(100, unit="s", tz="UTC"))
    assert q["ts"].max() == pd.Timestamp(120, unit="s", tz="UTC")


# -- quotes from order books ----------------------------------------------------------
def test_orderbook_effective_quotes_with_depth():
    far = load("orderbook_atp_faria_brunold_FAR_depth10_2026-10-24.json")["orderbook_fp"]
    bru = load("orderbook_atp_faria_brunold_BRU_depth10_2026-10-24.json")["orderbook_fp"]
    F, B = "KXATPMATCH-26OCT24FARBRU-FAR", "KXATPMATCH-26OCT24FARBRU-BRU"
    q = orderbooks_to_quotes("KXATPMATCH-26OCT24FARBRU", F, B, far, bru, at="2026-10-24T08:42:00Z")
    validate_quotes(q)
    a, b = q[q["side"] == "A"].iloc[0], q[q["side"] == "B"].iloc[0]
    # FAR: best YES bid .53 (664.85), best NO bid .46 (21698.12)
    # BRU: best YES bid .47 (1538.02), best NO bid .52 (1657.62)
    assert a["ask"] == pytest.approx(0.53) and a["ask_size"] == pytest.approx(1538.02)  # NO on BRU
    assert a["ask_source"] == f"no:{B}"
    assert a["bid"] == pytest.approx(0.53) and a["bid_size"] == pytest.approx(664.85)
    assert b["ask"] == pytest.approx(0.47) and b["ask_size"] == pytest.approx(664.85)   # NO on FAR
    assert b["ask_source"] == f"no:{F}"
    assert b["bid"] == pytest.approx(0.47) and b["bid_size"] == pytest.approx(1538.02)
    assert a["ask"] + b["ask"] == pytest.approx(1.00)  # research doc §7: best combo is exactly $1
    assert (q["source"] == "orderbook").all()


def test_orderbook_empty_side_is_nan():
    q = orderbooks_to_quotes("M", "M-A", "M-B", {"yes_dollars": [["0.40", "5"]]}, {})
    a, b = q[q["side"] == "A"].iloc[0], q[q["side"] == "B"].iloc[0]
    assert math.isnan(a["ask"]) and a["bid"] == pytest.approx(0.40)
    assert b["ask"] == pytest.approx(0.60) and b["ask_size"] == pytest.approx(5)  # NO on A


# -- client ---------------------------------------------------------------------------
class FakeResp:
    def __init__(self, status, data=None):
        self.status_code, self._data, self.text, self.url = status, data, json.dumps(data), "u"

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)


def client(tmp_path, responses):
    sleeps = []
    c = KalshiClient(raw_dir=tmp_path, session=FakeSession(responses), sleep=sleeps.append,
                     clock=lambda: 0.0)
    return c, sleeps


def test_client_caches_and_reuses(tmp_path):
    c, _ = client(tmp_path, [FakeResp(200, {"series": {"ticker": "X"}})])
    assert c.series("X") == {"ticker": "X"}
    assert c.series("X") == {"ticker": "X"}           # second call from disk
    assert c.requests_made == 1 and c.cache_hits == 1
    c2, _ = client(tmp_path, [])                       # a fresh run reuses the same files
    assert c2.series("X") == {"ticker": "X"} and c2.requests_made == 0


def test_client_backs_off_on_429(tmp_path):
    c, sleeps = client(tmp_path, [FakeResp(429, {}), FakeResp(429, {}), FakeResp(200, {"ok": 1})])
    assert c.get("/x") == {"ok": 1}
    assert c.requests_made == 3 and c.rate_limited == 2
    assert [s for s in sleeps if s >= 2] == [2.0, 4.0]
    assert c.min_interval_s > 0.5                      # gap widened after 429s


def test_client_raises_on_404(tmp_path):
    c, _ = client(tmp_path, [FakeResp(404, {"error": "not found"})])
    with pytest.raises(KalshiError):
        c.get("/nope")


def test_client_paginates_by_cursor(tmp_path):
    c, _ = client(tmp_path, [FakeResp(200, {"events": [1, 2], "cursor": "c1"}),
                             FakeResp(200, {"events": [3], "cursor": ""})])
    assert list(c.events("S", status="settled")) == [1, 2, 3]
    assert c.session.calls[1][1]["cursor"] == "c1"


def test_candle_windows_cover_range_without_gaps():
    w = backfill.windows(pd.Timestamp(0, unit="s", tz="UTC"), pd.Timestamp(10_000 * 60, unit="s", tz="UTC"))
    assert w[0][0] == -60 and w[-1][1] == 10_000 * 60 + 60
    assert all(b == c for (_, b), (c, _) in zip(w, w[1:]))
    assert all((b - a) <= backfill.CHUNK_MIN * 60 for a, b in w)


def test_client_eases_back_after_clean_run(tmp_path):
    c, _ = client(tmp_path, [FakeResp(429, {})] + [FakeResp(200, {"ok": i}) for i in range(51)])
    c.get("/x0", cache=False)
    widened = c.min_interval_s
    for i in range(1, 51):
        c.get(f"/x{i}", cache=False)
    assert c.base_interval_s < c.min_interval_s < widened
