"""Kalshi raw JSON → `matches` / `quotes` rows (swinglock/schema.py).

A Kalshi tennis match is one event with two markets, one per player. Side A pays on player
A, and there are two ways to buy it: YES on A's market, or NO on B's market. So

    ask(A) = min(YES ask on A, NO ask on B) = min(1 − best NO bid(A), 1 − best YES bid(B))
    bid(A) = max(YES bid on A, NO bid on B) = max(best YES bid(A), 1 − best YES ask(B))

and the same with A and B swapped. Only quoted ask/bid levels go in; never trade prices,
mid or last. A side with no quote stays NaN.

Candles (1-minute) carry only YES bid/ask OHLC and no size; we use the `close` of each
period (the quote at period end). Kalshi omits candles for minutes with no update, so each
market's last close is carried forward until its next candle (for at most `max_carry_s`,
config `data.max_carry_s`, default 300 s), and the two legs are combined at the union of
their candle times.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any, Iterable

import numpy as np
import pandas as pd

from ..schema import MATCH_COLUMNS, QUOTE_COLUMNS, conform, empty

VENUE = "kalshi"

TIERS = {
    "KXATPMATCH": "atp",
    "KXWTAMATCH": "wta",
    "KXATPCHALLENGERMATCH": "challenger",
    "KXWTACHALLENGERMATCH": "challenger",
    "KXCHALLENGERMATCH": "challenger",
    "KXITFMATCH": "itf",
    "KXITFWMATCH": "itf",
}

# Fee type before a series' first recorded fee change. KXATP/KXWTAMATCH moved from plain
# quadratic to quadratic_with_maker_fees on 2025-11-15 (GET /series/fee_changes).
DEFAULT_PRIOR_FEE_TYPE = "quadratic"


def num(x: Any) -> float:
    """Kalshi dollar/count string → float; None/''/bad → NaN."""
    if x is None or x == "":
        return math.nan
    try:
        return float(x)
    except (TypeError, ValueError):
        return math.nan


def ts(x: Any) -> pd.Timestamp:
    if x is None or x == "" or (not isinstance(x, str) and pd.isna(x)):
        return pd.NaT
    t = pd.Timestamp(x)
    return t.tz_convert("UTC") if t.tzinfo else t.tz_localize("UTC")


def tier(series: str) -> str:
    return TIERS.get(series, "other")


def order_markets(event_ticker: str, markets: list[dict]) -> tuple[dict, dict]:
    """(market_A, market_B). A is the player listed first in the event ticker
    (KXATPMATCH-26OCT23VANMUS → VAN is A), which matches the event title order.
    Falls back to ticker order when the suffixes can't be placed."""
    if len(markets) != 2:
        raise ValueError(f"{event_ticker}: expected 2 markets, got {len(markets)}")
    code = event_ticker.split("-", 1)[1] if "-" in event_ticker else event_ticker
    sfx = [m["ticker"].rsplit("-", 1)[-1] for m in markets]
    pos = [code.find(s) for s in sfx]
    if min(pos) >= 0 and pos[0] != pos[1]:
        a, b = sorted(markets, key=lambda m: code.find(m["ticker"].rsplit("-", 1)[-1]))
    else:
        a, b = sorted(markets, key=lambda m: m["ticker"])
    return a, b


def fee_in_effect(series: dict, fee_changes: list[dict], at: pd.Timestamp,
                  event: dict | None = None) -> tuple[str, float]:
    """(fee_type, fee_multiplier) at time `at`: event override, else the series' fee
    history (last change at or before `at`), else the series' current values."""
    if event and event.get("fee_type_override"):
        mult = event.get("fee_multiplier_override")
        return event["fee_type_override"], float(mult if mult is not None else series.get("fee_multiplier", 1))
    changes = sorted(fee_changes, key=lambda c: c["scheduled_ts"])
    if changes and pd.notna(at):
        past = [c for c in changes if ts(c["scheduled_ts"]) <= at]
        if past:
            return past[-1]["fee_type"], float(past[-1]["fee_multiplier"])
        return DEFAULT_PRIOR_FEE_TYPE, float(series.get("fee_multiplier", 1))
    return series.get("fee_type", DEFAULT_PRIOR_FEE_TYPE), float(series.get("fee_multiplier", 1))


def winner(ma: dict, mb: dict) -> Any:
    """'A'/'B' when one market settled Yes at $1 and the other No; NA otherwise
    (unsettled, or a not-started match settled at a fair price)."""
    ra, rb = ma.get("result") or "", mb.get("result") or ""
    va, vb = num(ma.get("settlement_value_dollars")), num(mb.get("settlement_value_dollars"))
    if ra == "yes" and rb == "no" and (math.isnan(va) or va == 1.0):
        return "A"
    if rb == "yes" and ra == "no" and (math.isnan(vb) or vb == 1.0):
        return "B"
    return pd.NA


def settle_value(m: dict) -> float:
    """Dollars a YES contract on this market paid: settlement_value_dollars when settled
    (1/0, or the fair price for a not-started match), 1/0 from `result` if the value is
    missing, NaN while unsettled."""
    result = m.get("result") or ""
    if result not in ("yes", "no", "scalar"):
        return math.nan
    v = num(m.get("settlement_value_dollars"))
    if math.isnan(v) and result != "scalar":
        v = 1.0 if result == "yes" else 0.0
    return v


def match_row(event: dict, markets: list[dict], series: dict, fee_changes: list[dict] = (),
              scheduled_start: Any = None) -> dict:
    ma, mb = order_markets(event["event_ticker"], markets)
    open_t = min(ts(ma.get("open_time")), ts(mb.get("open_time")))
    close_t = max(ts(ma.get("close_time")), ts(mb.get("close_time")))
    fee_type, mult = fee_in_effect(series, list(fee_changes), open_t, event)
    return {
        "match_id": event["event_ticker"],
        "venue": VENUE,
        "series": event.get("series_ticker") or series.get("ticker"),
        "tier": tier(event.get("series_ticker") or series.get("ticker", "")),
        "tournament": (event.get("product_metadata") or {}).get("competition") or "",
        "player_a": ma.get("yes_sub_title") or "",
        "player_b": mb.get("yes_sub_title") or "",
        "instrument_a": ma["ticker"],
        "instrument_b": mb["ticker"],
        "scheduled_start": ts(scheduled_start),
        "open_time": open_t,
        "close_time": close_t,
        "winner": winner(ma, mb),
        "settle_a": settle_value(ma),
        "settle_b": settle_value(mb),
        "fee_type": fee_type,
        "fee_multiplier": mult,
    }


def matches_frame(rows: Iterable[dict]) -> pd.DataFrame:
    rows = list(rows)
    return conform(pd.DataFrame(rows), MATCH_COLUMNS) if rows else empty(MATCH_COLUMNS)


# -- quotes ---------------------------------------------------------------------------
def _close(c: dict, group: str) -> float:
    g = c.get(group) or {}
    return num(g.get("close_dollars", g.get("close")))  # live vs historical field names


def _valid_ask(x):
    return np.where((x > 0) & (x < 1), x, np.nan)


def _valid_bid(x):
    return np.where((x > 0) & (x < 1), x, np.nan)


def _pick(yes_px, no_px, yes_sz, no_sz, yes_label, no_label, better):
    """Choose per row between the YES-leg price and the NO-leg price (better = np.less for
    asks, np.greater for bids). Ties sum the sizes and name both legs."""
    yes_px, no_px = np.asarray(yes_px, float), np.asarray(no_px, float)
    yes_sz, no_sz = np.asarray(yes_sz, float), np.asarray(no_sz, float)
    has_y, has_n = ~np.isnan(yes_px), ~np.isnan(no_px)
    tie = has_y & has_n & np.isclose(yes_px, no_px, rtol=0, atol=1e-9)
    use_y = has_y & (~has_n | better(yes_px, no_px)) & ~tie
    use_n = has_n & ~use_y & ~tie
    px = np.where(use_y | tie, yes_px, np.where(use_n, no_px, np.nan))
    sz = np.where(use_y, yes_sz, np.where(use_n, no_sz, np.where(tie, yes_sz + no_sz, np.nan)))
    label = np.where(use_y, yes_label, np.where(use_n, no_label,
                     np.where(tie, f"{yes_label}|{no_label}", None)))
    return px, sz, label


def effective_quotes(match_id: str, ticker_a: str, ticker_b: str, t, yb_a, ya_a, yb_b, ya_b,
                     size: dict[str, np.ndarray] | None = None, source: str = "candle") -> pd.DataFrame:
    """Two-leg → per-side quotes. Inputs are arrays aligned on `t`: best YES bid/ask of each
    market (NaN = none). `size` (orderbook only) holds the sizes of those four levels under
    keys yb_a, ya_a, yb_b, ya_b; candles have no size."""
    yb_a, ya_a, yb_b, ya_b = (_valid_bid(np.asarray(yb_a, float)), _valid_ask(np.asarray(ya_a, float)),
                              _valid_bid(np.asarray(yb_b, float)), _valid_ask(np.asarray(ya_b, float)))
    n = len(yb_a)
    nan = np.full(n, np.nan)
    s = {k: np.asarray(v, float) for k, v in (size or {}).items()}
    s_yb_a, s_ya_a = s.get("yb_a", nan), s.get("ya_a", nan)
    s_yb_b, s_ya_b = s.get("yb_b", nan), s.get("ya_b", nan)
    out = []
    for side, (y_t, n_t, ya_y, yb_n, yb_y, ya_n, sya_y, syb_n, syb_y, sya_n) in {
        # side: own market's YES ask/bid vs the other market's NO (derived from its YES bid/ask)
        "A": (ticker_a, ticker_b, ya_a, yb_b, yb_a, ya_b, s_ya_a, s_yb_b, s_yb_a, s_ya_b),
        "B": (ticker_b, ticker_a, ya_b, yb_a, yb_b, ya_a, s_ya_b, s_yb_a, s_yb_b, s_ya_a),
    }.items():
        ask, ask_sz, ask_src = _pick(ya_y, 1 - yb_n, sya_y, syb_n, f"yes:{y_t}", f"no:{n_t}", np.less)
        bid, bid_sz, _ = _pick(yb_y, 1 - ya_n, syb_y, sya_n, "", "", np.greater)
        out.append(pd.DataFrame({
            "ts": t, "match_id": match_id, "venue": VENUE, "side": side,
            "ask": np.round(ask, 6), "ask_size": ask_sz, "bid": np.round(bid, 6), "bid_size": bid_sz,
            "ask_source": ask_src, "source": source,
        }))
    df = pd.concat(out, ignore_index=True).sort_values(["ts", "side"], kind="stable")
    return conform(df.reset_index(drop=True), QUOTE_COLUMNS)


def candle_frame(candles: list[dict]) -> pd.DataFrame:
    """One market's candles → ts, yes_bid, yes_ask (period-end closes), deduped and sorted.

    A crossed candle (yes_ask close < yes_bid close on the same market) can't come from a real
    book; its ask is set to NaN. Seen only in historical candles: 84 of 13.8 M, all in 5 markets on
    2026-05-13 11-15 UTC, where the ask close sat frozen while the bid traded (docs/data_kalshi_collector.md)."""
    if not candles:
        return pd.DataFrame({"ts": pd.Series(dtype="datetime64[ns, UTC]"),
                             "yes_bid": pd.Series(dtype=float), "yes_ask": pd.Series(dtype=float)})
    df = pd.DataFrame({
        "ts": pd.to_datetime([c["end_period_ts"] for c in candles], unit="s", utc=True)
              .astype("datetime64[ns, UTC]"),
        "yes_bid": [_close(c, "yes_bid") for c in candles],
        "yes_ask": [_close(c, "yes_ask") for c in candles],
    })
    df.loc[df["yes_ask"] < df["yes_bid"], "yes_ask"] = np.nan
    return df.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)


DEFAULT_MAX_CARRY_S = 300.0


def candles_to_quotes(match_id: str, ticker_a: str, ticker_b: str, candles_a: list[dict],
                      candles_b: list[dict], until: Any = None,
                      max_carry_s: float | None = DEFAULT_MAX_CARRY_S) -> pd.DataFrame:
    """Candles of both legs → quotes (source 'candle'). Each leg's last close is carried
    forward to the other leg's candle times for at most `max_carry_s` (None = no cap); an
    older leg counts as missing (NaN). Nothing before a leg's first candle is filled.
    Candles ending more than one period after `until` (match close) are dropped."""
    a, b = candle_frame(candles_a), candle_frame(candles_b)
    if a.empty and b.empty:
        return empty(QUOTE_COLUMNS)
    grid = pd.DataFrame({"ts": pd.concat([a["ts"], b["ts"]]).drop_duplicates().sort_values()})
    tol = None if max_carry_s is None else pd.Timedelta(seconds=max_carry_s)
    m = pd.merge_asof(grid, a.rename(columns={"yes_bid": "yb_a", "yes_ask": "ya_a"}), on="ts", tolerance=tol)
    m = pd.merge_asof(m, b.rename(columns={"yes_bid": "yb_b", "yes_ask": "ya_b"}), on="ts", tolerance=tol)
    if until is not None and pd.notna(ts(until)):
        m = m[m["ts"] <= ts(until) + pd.Timedelta(minutes=1)]
    return effective_quotes(match_id, ticker_a, ticker_b, m["ts"].to_numpy(),
                            m["yb_a"], m["ya_a"], m["yb_b"], m["ya_b"])


def best_bid(levels: list | None) -> tuple[float, float]:
    """(price, size) of the best bid in a Kalshi bids-only list (ascending, best last)."""
    if not levels:
        return math.nan, math.nan
    p, q = levels[-1]
    return num(p), num(q)


def orderbooks_to_quotes(match_id: str, ticker_a: str, ticker_b: str, book_a: dict, book_b: dict,
                         at: Any = None) -> pd.DataFrame:
    """One snapshot of both legs' `orderbook_fp` → two quote rows (source 'orderbook').
    YES ask = 1 − best NO bid, with that NO bid's size."""
    at = ts(at) if at is not None else pd.Timestamp(datetime.now(timezone.utc))
    yb_a, s_yb_a = best_bid(book_a.get("yes_dollars"))
    nb_a, s_nb_a = best_bid(book_a.get("no_dollars"))
    yb_b, s_yb_b = best_bid(book_b.get("yes_dollars"))
    nb_b, s_nb_b = best_bid(book_b.get("no_dollars"))
    return effective_quotes(match_id, ticker_a, ticker_b, [at], [yb_a], [1 - nb_a], [yb_b], [1 - nb_b],
                            size={"yb_a": [s_yb_a], "ya_a": [s_nb_a], "yb_b": [s_yb_b], "ya_b": [s_nb_b]},
                            source="orderbook")


# -- live score (GET /live_data/batch, type tennis_tournament_singles) -----------------
SCORE_COLUMNS = {
    "ts": "datetime64[ns, UTC]",
    "match_id": "string",
    "milestone_id": "string",
    "status": "string",         # not_started | started | live | closed (details.status)
    "match_status": "string",   # "" | 1st_set | 2nd_set | ... | ended
    "delayed": "boolean",       # details.live_data_delayed (False when absent; not always set)
    "sets_a": "Int64", "sets_b": "Int64",       # sets won
    "games_a": "Int64", "games_b": "Int64",     # games in the current (last listed) set
    "tb_a": "Int64", "tb_b": "Int64",           # that set's tiebreak points, if any
    "points_a": "Int64", "points_b": "Int64",   # current game: 0/15/30/40 as given
    "server": "string",         # "A" | "B" | <NA>
    "advantage": "string",      # "A" | "B" | <NA> (player with AD at deuce)
    "set_scores": "string",     # "6-7(5) 7-6(9) 4-6", A first
    "winner": "string",         # "A" | "B" | <NA>
    "raw": "string",            # details JSON without statistics, for re-deriving later
}
SCORE_KEY = ("status", "match_status", "sets_a", "sets_b", "games_a", "games_b", "tb_a", "tb_b",
             "points_a", "points_b", "server", "advantage", "winner")


def competitor_sides(market_a: dict, market_b: dict) -> dict[str, str]:
    """competitor id → 'A'/'B' from each market's custom_strike.tennis_competitor."""
    out = {}
    for side, m in (("A", market_a), ("B", market_b)):
        cid = (m.get("custom_strike") or {}).get("tennis_competitor")
        if cid:
            out[cid] = side
    return out


def _int(x) -> Any:
    try:
        return pd.NA if x is None or x == "" else int(x)
    except (TypeError, ValueError):
        return pd.NA


def score_row(match_id: str, live: dict, sides: dict[str, str], at: Any) -> dict | None:
    """One live_data entry → a score row with competitor 1/2 mapped to sides A/B.
    None when the competitors can't be mapped (we never guess the orientation)."""
    d = live.get("details") or {}
    c1, c2 = d.get("competitor1_id"), d.get("competitor2_id")
    if sides.get(c1) not in ("A", "B") or sides.get(c2) not in ("A", "B") or sides[c1] == sides[c2]:
        return None
    n = {sides[c1]: "1", sides[c2]: "2"}  # side → competitor number

    def comp(side, field):
        return d.get(f"competitor{n[side]}_{field}")

    rounds = {s: comp(s, "round_scores") or [] for s in "AB"}
    last = {s: (rounds[s][-1] if rounds[s] else {}) for s in "AB"}
    sets_txt = []
    for ra, rb in zip(rounds["A"], rounds["B"]):
        txt = f"{ra.get('score')}-{rb.get('score')}"
        tb = [r.get("tiebreak_score") for r in (ra, rb) if r.get("tiebreak_score") is not None]
        if tb:
            txt += f"({min(tb)})"
        sets_txt.append(txt)
    raw = {k: v for k, v in d.items() if "statistics" not in k}
    return {
        "ts": ts(at), "match_id": match_id, "milestone_id": live.get("milestone_id"),
        "status": d.get("status") or "", "match_status": d.get("match_status") or "",
        "delayed": bool(d.get("live_data_delayed") or False),
        "sets_a": _int(comp("A", "overall_score")), "sets_b": _int(comp("B", "overall_score")),
        "games_a": _int(last["A"].get("score")), "games_b": _int(last["B"].get("score")),
        "tb_a": _int(last["A"].get("tiebreak_score")), "tb_b": _int(last["B"].get("tiebreak_score")),
        "points_a": _int(comp("A", "current_round_score")), "points_b": _int(comp("B", "current_round_score")),
        "server": sides.get(d.get("server")) or pd.NA,
        "advantage": sides.get(d.get("advantage")) or pd.NA,
        "set_scores": " ".join(sets_txt),
        "winner": sides.get(d.get("winner")) or pd.NA,
        "raw": json.dumps(raw, sort_keys=True),
    }
