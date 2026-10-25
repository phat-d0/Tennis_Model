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


def test_carry_forward_is_capped():
    def c(t, yb, ya):
        return {"end_period_ts": t, "yes_bid": {"close_dollars": yb}, "yes_ask": {"close_dollars": ya}}
    ca = [c(60, "0.40", "0.42"), c(1000, "0.41", "0.43")]
    cb = [c(300, "0.55", "0.57"), c(400, "0.56", "0.58")]
    q = candles_to_quotes("M", "M-A", "M-B", ca, cb, max_carry_s=300)
    # t=300: A's close from t=60 is 240 s old → still carried
    assert q_at(q, 300, "A")["ask"] == pytest.approx(0.42)
    # t=400: A is 340 s old → dropped; only NO on B prices side A (1 - .56)
    a = q_at(q, 400, "A")
    assert a["ask"] == pytest.approx(0.44) and a["ask_source"] == "no:M-B"
    assert q_at(q, 400, "B")["ask"] == pytest.approx(0.58)  # NO on A unavailable
    # t=1000: B is 600 s old → side A only from its own YES ask
    assert q_at(q, 1000, "A")["ask"] == pytest.approx(0.43) and q_at(q, 1000, "A")["ask_source"] == "yes:M-A"
    # uncapped: the stale A leg would still price side B via NO on A at t=400
    q2 = candles_to_quotes("M", "M-A", "M-B", ca, cb, max_carry_s=None)
    assert q_at(q2, 400, "B")["ask"] == pytest.approx(0.58)
    assert q_at(q2, 400, "A")["ask"] == pytest.approx(0.42)


# -- backfill planning ----------------------------------------------------------------
def _item(i, open_s, close_s, tier_="atp", hist=False):
    return {"open": pd.Timestamp(open_s, unit="s", tz="UTC"), "close": pd.Timestamp(close_s, unit="s", tz="UTC"),
            "tickers": [f"E{i}-A", f"E{i}-B"], "tier": tier_, "historical": hist}


def test_plan_batches_respects_requested_candle_cap():
    # 40 matches, each live ~13 h, opening 20 min apart → several share a request
    items = [_item(i, i * 1200, i * 1200 + 800 * 60) for i in range(40)]
    batches = backfill.plan_batches(items)
    assert sum(map(len, batches)) == 40
    for bt in batches:
        lo = min(backfill._span(r)[0] for r in bt)
        hi = max(backfill._span(r)[1] for r in bt)
        assert backfill.requested_candles(2 * len(bt), lo, hi) <= backfill.BATCH_CANDLE_CAP
        assert 2 * len(bt) <= backfill.MAX_TICKERS
    assert max(map(len, batches)) >= 4
    # the live 400 seen on 2026-10-24: 2 tickers × 5,001 minutes = 10,002 requested
    assert backfill.requested_candles(2, 0, 5000 * 60) == 10_002
    lo, hi = backfill.windows(pd.Timestamp(0, unit="s", tz="UTC"), pd.Timestamp(10**6, unit="s", tz="UTC"))[0]
    assert backfill.requested_candles(2, lo, hi) <= backfill.BATCH_CANDLE_CAP


def test_prefetch_batch_seeds_per_match_cache(tmp_path):
    def cand(t):
        return {"end_period_ts": t, "yes_bid": {"close_dollars": "0.4"}, "yes_ask": {"close_dollars": "0.42"}}
    r1, r2 = _item(1, 600, 3600), _item(2, 3000, 7200)
    resp = {"markets": [{"market_ticker": "E1-A", "candlesticks": [cand(660), cand(3600)]},
                        {"market_ticker": "E1-B", "candlesticks": [cand(660)]},
                        {"market_ticker": "E2-A", "candlesticks": [cand(3060), cand(7200)]},
                        {"market_ticker": "E2-B", "candlesticks": []}]}
    c, _ = client(tmp_path, [FakeResp(200, resp)])
    stats = {"group_errors": 0, "grouped_matches": 0}
    backfill.prefetch_batch(c, [r1, r2], stats)
    assert c.requests_made == 1 and stats["grouped_matches"] == 2
    assert c.session.calls[0][1]["market_tickers"] == "E1-A,E1-B,E2-A,E2-B"
    # fetch_candles for each match is now a pure cache hit with only that match's window
    got1 = backfill.fetch_candles(c, r1["tickers"], r1["open"], r1["close"], historical=False)
    got2 = backfill.fetch_candles(c, r2["tickers"], r2["open"], r2["close"], historical=False)
    assert c.requests_made == 1
    assert [x["end_period_ts"] for x in got1["E1-A"]] == [660, 3600]
    assert [x["end_period_ts"] for x in got2["E2-A"]] == [3060, 7200] and got2["E2-B"] == []


def test_prefetch_batch_falls_back_on_error(tmp_path):
    c, _ = client(tmp_path, [FakeResp(400, {"error": "bad request"})])
    stats = {"group_errors": 0, "grouped_matches": 0}
    backfill.prefetch_batch(c, [_item(1, 600, 3600), _item(2, 600, 3600)], stats)
    assert stats["group_errors"] == 1 and stats["grouped_matches"] == 0


def test_work_order_priority():
    now = pd.Timestamp("2026-10-24", tz="UTC")
    recent, old = now - pd.Timedelta(days=10), now - pd.Timedelta(days=400)
    def it(t, close):
        return {"tier": t, "close": close}
    assert backfill.priority(it("atp", recent), now, 183) == 0
    assert backfill.priority(it("wta", recent), now, 183) == 0
    assert backfill.priority(it("challenger", recent), now, 183) == 1
    assert backfill.priority(it("itf", recent), now, 183) == 2
    assert backfill.priority(it("atp", old), now, 183) == 2


def test_network_failure_becomes_kalshi_error_status_0(tmp_path):
    import requests

    class Down(FakeSession):
        def get(self, url, params=None, timeout=None):
            self.calls.append(url)
            raise requests.ConnectionError("proxy closed")
    c = KalshiClient(raw_dir=tmp_path, session=Down([]), sleep=lambda s: None, clock=lambda: 0.0, max_retries=2)
    with pytest.raises(KalshiError) as e:
        c.get("/x")
    assert e.value.status == 0 and len(c.session.calls) == 3


def test_backfill_pauses_on_outage_instead_of_dropping_quotes(monkeypatch):
    calls, sleeps = [], []

    def flaky(client, r, starts, stats, max_carry_s, raise_network=False):
        calls.append(raise_network)
        if len(calls) < 3:
            raise KalshiError(0, "u", "network error")
        return {"match_id": "M"}, "quotes"
    monkeypatch.setattr(backfill, "normalize_one", flaky)
    stats = {"network_pauses": 0}
    assert backfill.normalize_one_patiently(None, {}, {}, stats, 300, sleep=sleeps.append) == ({"match_id": "M"}, "quotes")
    assert stats["network_pauses"] == 2 and sleeps == [backfill.NETWORK_PAUSE_S] * 2 and all(calls)
    monkeypatch.setattr(backfill, "normalize_one",
                        lambda *a, **k: (_ for _ in ()).throw(KalshiError(404, "u")))
    with pytest.raises(KalshiError):            # non-network errors are not retried here
        backfill.normalize_one_patiently(None, {}, {}, stats, 300, sleep=sleeps.append)


# -- live score -----------------------------------------------------------------------
def test_score_row_ended_match_maps_competitors_to_sides():
    from swinglock.collectors.kalshi_normalize import competitor_sides, score_row
    ld = load("live_data_atp_vanassche_musetti_ended_2026-10-23.json")["live_data"]
    a, b = order_markets(VANMUS["event_ticker"], VANMUS["markets"])
    sides = competitor_sides(a, b)                    # VAN market → A, MUS market → B
    row = score_row("KXATPMATCH-26OCT23VANMUS", ld, sides, "2026-10-23T23:21:00Z")
    assert (row["status"], row["match_status"]) == ("closed", "ended")
    assert (row["sets_a"], row["sets_b"]) == (1, 2)
    assert (row["games_a"], row["games_b"]) == (4, 6)   # last set
    assert row["set_scores"] == "6-7(5) 7-6(7) 4-6"
    assert row["winner"] == "B"                         # Musetti won, as the markets settled
    assert "statistics" not in row["raw"]


def test_score_row_live_formats():
    """Live batch fixture (2026-10-24): points are 0/15/30/40 as given; server and advantage
    are competitor ids."""
    from swinglock.collectors.kalshi_normalize import score_row
    lives = load("live_data_batch_tennis_live_2026-10-24.json")["live_datas"]
    deuce = lives[1]["details"]
    sides = {deuce["competitor1_id"]: "A", deuce["competitor2_id"]: "B"}
    row = score_row("M", lives[1], sides, "2026-10-24T10:42:00Z")
    assert (row["status"], row["match_status"]) == ("started", "")
    assert (row["points_a"], row["points_b"]) == (40, 40)
    assert row["advantage"] == "B" and row["server"] == "B"
    assert (row["games_a"], row["games_b"], row["sets_a"], row["sets_b"]) == (3, 5, 0, 0)
    assert pd.isna(row["winner"]) and row["delayed"] is False
    # swapped orientation: competitor1 is side B
    flipped = score_row("M", lives[1], {k: ("B" if v == "A" else "A") for k, v in sides.items()}, "2026-10-24")
    assert (flipped["games_a"], flipped["games_b"], flipped["advantage"]) == (5, 3, "A")
    not_started = lives[3]["details"]
    ns = score_row("M", lives[3], {not_started["competitor1_id"]: "A", not_started["competitor2_id"]: "B"}, "2026-10-24")
    assert ns["status"] == "not_started" and pd.isna(ns["games_a"]) and pd.isna(ns["server"]) and ns["set_scores"] == ""


def test_score_row_refuses_unmapped_competitors():
    from swinglock.collectors.kalshi_normalize import score_row
    live = load("live_data_batch_tennis_live_2026-10-24.json")["live_datas"][0]
    assert score_row("M", live, {}, "2026-10-24") is None
    c1 = live["details"]["competitor1_id"]
    assert score_row("M", live, {c1: "A"}, "2026-10-24") is None


def test_settle_values():
    row = match_row(VANMUS, VANMUS["markets"], SERIES, FEE_CHANGES)
    assert (row["settle_a"], row["settle_b"]) == (0.0, 1.0)        # Musetti (B) won
    hist = load("historical_markets_atp_match_2026-08-24.json")["markets"]
    ev = {"event_ticker": "KXATPMATCH-26AUG24SONHER", "series_ticker": "KXATPMATCH"}
    row = match_row(ev, hist, SERIES, FEE_CHANGES)
    assert (row["settle_a"], row["settle_b"]) == (1.0, 0.0)        # Sonego (A) won
    # not-started match: both legs settle "scalar" at a fair price (synthesized from the
    # pattern seen in 39/39 backfilled cases, e.g. KXATPMATCH-26SEP29MOLRIN 0.40/0.60)
    ma, mb = (dict(m) for m in VANMUS["markets"])
    ma.update(result="scalar", settlement_value_dollars="0.4000")
    mb.update(result="scalar", settlement_value_dollars="0.6000")
    row = match_row(VANMUS, [ma, mb], SERIES, FEE_CHANGES)
    assert (row["settle_a"], row["settle_b"]) == (0.4, 0.6) and pd.isna(row["winner"])
    open_row = match_row(FARBRU, FARBRU["markets"], SERIES, FEE_CHANGES)
    assert np.isnan(open_row["settle_a"]) and np.isnan(open_row["settle_b"])
    df = matches_frame([open_row, row])
    assert df["settle_a"].dtype == "float64"


def test_run_only_groups_skips_other_groups(tmp_path, monkeypatch):
    """--groups: matches outside the selected work groups are neither fetched nor written."""
    now = pd.Timestamp.now(tz="UTC")
    items = [dict(_item(1, 0, 0, "atp"), close=now - pd.Timedelta(days=5)),
             dict(_item(2, 0, 0, "challenger"), close=now - pd.Timedelta(days=5))]
    for i, r in enumerate(items):
        r.update(event={"event_ticker": f"E{i}"}, markets=[], series={}, fee_changes=[])
    monkeypatch.setattr(backfill, "collect_series", lambda *a, **k: items if a[1] == "S" else [])
    monkeypatch.setattr(backfill, "scheduled_starts", lambda *a, **k: {})
    monkeypatch.setattr(backfill.KalshiClient, "historical_cutoff", lambda self: {"market_settled_ts": "2026-08-25T00:00:00Z"})
    done = []
    monkeypatch.setattr(backfill, "normalize_one_patiently",
                        lambda c, r, *a, **k: (done.append(r["tier"]) or ({"match_id": r["event"]["event_ticker"]}, backfill.empty(backfill.QUOTE_COLUMNS))))
    monkeypatch.setattr(backfill, "write_outputs", lambda out, rows, q: (backfill.matches_frame([]), backfill.empty(backfill.QUOTE_COLUMNS)))
    backfill.run(["S"], tmp_path, tmp_path / "raw", only_groups=[1])
    assert done == ["challenger"]


def test_crossed_candle_ask_is_dropped():
    """Real historical candles (SAKMUL, 2026-05-13): the ask close froze at 0.62 while the
    bid traded up to 0.79-0.80. A YES ask below the same market's YES bid is not a real quote."""
    sak = load("historical_candlesticks_1m_challenger_sakmul_SAK_crossed_2026-05-13.json")["candlesticks"]
    q = candles_to_quotes("M", "M-SAK", "M-MUL", sak, [])
    ok = q_at(q, 1778672400, "A")                     # 11:40: bid .39 < ask .62, kept
    assert ok["ask"] == pytest.approx(0.62) and ok["bid"] == pytest.approx(0.39)
    for t in (1778672460, 1778672520, 1778672580):    # 11:41-11:43: crossed
        a, b = q_at(q, t, "A"), q_at(q, t, "B")
        assert math.isnan(a["ask"])                   # dropped, nothing filled in
        assert a["bid"] >= 0.75                       # the traded bid is kept
        assert b["ask"] == pytest.approx(1 - a["bid"])  # NO on SAK still prices side B
        assert math.isnan(b["bid"])                   # 1 - YES ask(SAK) is gone with the ask
