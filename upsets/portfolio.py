"""Paper-trade portfolio for the public odds page: realized vs expected, like the soccer app's
Portfolio tab (owner request, 2026-10-26).

Each build (upsets.site) calls `update`:
- Open: in tournaments The Odds API scores (SCORED_KEYS), before the listed start, one $10 paper
  trade per strategy and match, at DraftKings' current odds, the first time the strategy's rule
  holds. Recorded with its expected value at Pinnacle's fair price (DraftKings' fair price when
  Pinnacle has no quote).
- Close: until the start, each open trade's close is refreshed to the latest DraftKings odds and
  Pinnacle fair chance (builds run every 3 h, so a close can be up to ~3 h before the start).
- Settle: 3 h after the start, `/scores` (2 credits per key, inside the page's monthly cap) gives the
  winner. A match with no result 4 days after its start is void (stake back).
Trades live in the build cache (portfolio.json there), never in git. No Kalshi data.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .odds import devig_power

STAKE = 10.0
SETTLE_AFTER_H = 3.0
VOID_AFTER_D = 4.0
MAX_SCORE_CALLS = 4
MAX_BOOK_GAP = 0.10     # skip a match when DK's and Pinnacle's fair chances differ by more: a quote
                        # error (suspended or stale line), not a price you could get

# Keys with /scores support (docs/research/odds_api.md, the-odds-api.com sports list)
SCORED_KEYS = frozenset(f"tennis_{k}" for k in """
atp_us_open wta_us_open atp_canadian_open wta_canadian_open atp_cincinnati_open wta_cincinnati_open
atp_china_open wta_china_open atp_japan_open atp_shanghai_masters atp_washington_open wta_washington_open
wta_wuhan_open wta_guadalajara_open wta_monterrey_open wta_singapore_open""".split())

STRATEGIES = [
    {"id": "model", "name": "Elo model edge", "min_edge": 0.05,
     "rule": "Bet the player whose Elo model chance × DraftKings odds − 1 is at least 5%."},
    {"id": "line", "name": "DraftKings beats Pinnacle", "min_edge": 0.01,
     "rule": "Bet the player whose DraftKings odds × Pinnacle's fair chance − 1 is at least 1% "
             "(line shopping)."},
    {"id": "dogs", "name": "Every underdog (control)", "min_edge": None,
     "rule": "Bet the longer DraftKings price in every match. Expect to lose about DraftKings' margin."},
    # owner request 2026-10-28; pre-registered and backtested in reports/upsets_seed_portfolio.md (gate FAIL)
    {"id": "seed", "name": "Seed loses early (backtest: −10.3%, not proven)", "min_edge": None,
     "rule": "In rounds 1–2, when exactly one player is seeded, bet the unseeded player at DraftKings. Seeds come from "
             "Wikipedia; \"rounds 1–2\" is a proxy: the seed's first or second match listed in the event."},
    {"id": "seed_q", "name": "Seed loses early: qualifiers only (sub-line)", "min_edge": None,
     "rule": "The same bets, only when the unseeded player is a qualifier or lucky loser (from Wikipedia's draw). "
             "The one split the backtest showed positive in some seasons; −8.2% overall."},
]


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _fair(book: dict | None) -> float | None:
    """Power de-vig of a book's two prices -> fair p(player 1). The page and every study use the power
    method since 2026-10-26 (it puts more of the margin on the long shot; the proportional method made
    the line rule's expected value about +9% a bet instead of about +0.5%)."""
    if not isinstance(book, dict):
        return None
    o1, o2 = _num(book.get("odds_1")), _num(book.get("odds_2"))
    if not o1 or not o2 or o1 <= 1 or o2 <= 1:
        return None
    return float(devig_power(np.array([o1]), np.array([o2]))[0])


def pick(strategy: dict, m: dict) -> tuple[int, float] | None:
    """(side 1|2, the rule's edge) when the strategy bets this match now, else None."""
    dk = m.get("draftkings") if isinstance(m.get("draftkings"), dict) else None
    if not dk:
        return None
    o = (_num(dk.get("odds_1")), _num(dk.get("odds_2")))
    if not all(o) or min(o) <= 1:
        return None
    dk1, pin1 = _fair(dk), _fair(m.get("pinnacle"))
    if dk1 is not None and pin1 is not None and abs(dk1 - pin1) > MAX_BOOK_GAP:
        return None
    sid = strategy["id"]
    if sid in ("seed", "seed_q"):
        sd = m.get("_seed") or {}   # {"seed_side": 1|2, "seed": n, "qual": bool, "round_ok": bool}, see upsets.site
        if sd.get("seed_side") not in (1, 2) or not sd.get("round_ok") or (sid == "seed_q" and not sd.get("qual")):
            return None
        side = 3 - sd["seed_side"]
        return side, 0.0
    if sid == "dogs":
        if o[0] == o[1]:
            return None
        return (1, 0.0) if o[0] > o[1] else (2, 0.0)
    if sid == "model":
        p1 = _num(m.get("model_p1"))
    else:
        p1 = _fair(m.get("pinnacle"))
    if p1 is None:
        return None
    edges = (p1 * o[0] - 1, (1 - p1) * o[1] - 1)
    side = 1 if edges[0] >= edges[1] else 2
    e = edges[side - 1]
    return (side, e) if e >= strategy["min_edge"] else None


def _side_fair(m: dict, side: int) -> tuple[float | None, str]:
    """Fair chance of `side` from Pinnacle, else DraftKings."""
    for name, src in (("pinnacle", "Pinnacle"), ("draftkings", "DraftKings")):
        p1 = _fair(m.get(name))
        if p1 is not None:
            return (p1 if side == 1 else 1 - p1), src
    return None, ""


def update(trades: list[dict], matches: list[dict], now: pd.Timestamp, fetched_at: str | None,
           seeds: dict | None = None) -> list[dict]:
    """Open new trades and refresh closes from this build's matches (odds.json rows). seeds: event_id ->
    the seed facts the "seed" strategies need (upsets.site.seed_facts); missing means no seed bet."""
    by_id = {t["id"]: t for t in trades}
    for m in matches:
        if seeds and m.get("event_id") in seeds:
            m = {**m, "_seed": seeds[m["event_id"]]}
        if m.get("sport_key") not in SCORED_KEYS:
            continue
        start = pd.Timestamp(m.get("commence_time"))
        if pd.isna(start) or start <= now:
            continue
        dk = m.get("draftkings") or {}
        for s in STRATEGIES:
            tid = f"{s['id']}:{m['event_id']}"
            t = by_id.get(tid)
            if t is None:
                got = pick(s, m)
                if got is None:
                    continue
                side, edge = got
                odds = _num(dk.get(f"odds_{side}"))
                p, src = _side_fair(m, side)
                pm = _num(m.get("model_p1"))
                t = {
                    "id": tid, "strategy": s["id"], "event_id": m["event_id"], "sport_key": m.get("sport_key"),
                    "tournament": m.get("tournament"), "tour": m.get("tour"), "commence_time": m.get("commence_time"),
                    "side": side, "player": m.get(f"player_{side}"), "opponent": m.get(f"player_{3 - side}"),
                    "odds": odds, "stake": STAKE, "opened_at": fetched_at or now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "edge": round(edge, 4), "p_fair": None if p is None else round(p, 4), "fair_source": src,
                    "ev": None if p is None else round(odds * p - 1, 4),
                    "p_model": None if pm is None else round(pm if side == 1 else 1 - pm, 4),
                    "status": "open", "profit": None, "close": None, "clv": None,
                }
                if s["id"] in ("seed", "seed_q"):
                    t["opponent_seed"] = m["_seed"].get("seed")
                    t["qualifier"] = bool(m["_seed"].get("qual"))
                trades.append(t)
                by_id[tid] = t
            if t["status"] == "open":
                p, src = _side_fair(m, t["side"])
                co = _num(dk.get(f"odds_{t['side']}"))
                at = fetched_at or now.strftime("%Y-%m-%dT%H:%M:%SZ")
                mins = (start - pd.Timestamp(at)).total_seconds() / 60
                t["close"] = {"odds": co, "p_fair": None if p is None else round(p, 4), "source": src,
                              "at": at, "minutes_before": round(mins)}
                t["clv"] = None if p is None else round(t["odds"] * p - 1, 4)
    return trades


def winner_from_scores(ev: dict) -> str | None:
    """Winning team name from one /scores event, or None if it isn't clear."""
    if not ev.get("completed"):
        return None
    sc = ev.get("scores") or []
    vals = [(s.get("name"), _num(s.get("score"))) for s in sc if isinstance(s, dict)]
    if len(vals) != 2 or any(v is None for _, v in vals) or vals[0][1] == vals[1][1]:
        return None
    return max(vals, key=lambda x: x[1])[0]


def settle(trades: list[dict], api, now: pd.Timestamp, budget_ok, record) -> int:
    """Settle trades whose match has had SETTLE_AFTER_H hours. `budget_ok(cost)` says if a paid call
    fits the page's budget; `record(credits)` books it. Returns the number of /scores calls."""
    due = [t for t in trades if t["status"] == "open"
           and pd.Timestamp(t["commence_time"]) + pd.Timedelta(hours=SETTLE_AFTER_H) <= now]
    calls = 0
    for key in sorted({t["sport_key"] for t in due}):
        if api is None or calls >= MAX_SCORE_CALLS or not budget_ok(2):
            break
        before = api.spent
        try:
            events = api.scores(key, days_from=3)
        finally:
            if api.spent > before:
                record(api.spent - before)
        calls += 1
        by_ev = {e.get("id"): e for e in events or [] if isinstance(e, dict)}
        for t in due:
            if t["sport_key"] != key or t["event_id"] not in by_ev:
                continue
            ev = by_ev[t["event_id"]]
            w = winner_from_scores(ev)
            if w is None:
                continue
            won = w == t["player"]
            t["status"] = "won" if won else "lost"
            t["profit"] = round(t["stake"] * (t["odds"] - 1), 2) if won else -t["stake"]
            t["settled_at"] = ev.get("last_update") or now.strftime("%Y-%m-%dT%H:%M:%SZ")
            t["score"] = " – ".join(f"{s.get('name')} {s.get('score')}" for s in ev.get("scores") or [])
    for t in trades:
        if t["status"] == "open" and pd.Timestamp(t["commence_time"]) + pd.Timedelta(days=VOID_AFTER_D) <= now:
            t["status"], t["profit"] = "void", 0.0
            t["settled_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
            t["note"] = "No result from The Odds API within 4 days: stake back."
    return calls


def summary(trades: list[dict]) -> dict:
    """Headline numbers: realized vs expected (Pinnacle-fair EV at entry), CLV, drawdown."""
    st = [t for t in trades if t["status"] in ("won", "lost")]
    out = {"trades": len(trades), "open": sum(t["status"] == "open" for t in trades),
           "void": sum(t["status"] == "void" for t in trades), "settled": len(st)}
    if not st:
        return out
    profit = np.array([t["profit"] for t in st], float)
    stake = np.array([t["stake"] for t in st], float)
    ev = np.array([t["ev"] if t["ev"] is not None else np.nan for t in st], float)
    ret = profit / stake
    order = np.argsort([t.get("settled_at") or t["commence_time"] for t in st])
    cum = np.cumsum(profit[order])
    clv = np.array([t["clv"] for t in st if t.get("clv") is not None], float)
    out.update(
        staked=float(stake.sum()), profit=round(float(profit.sum()), 2),
        roi=float(profit.sum() / stake.sum()),
        roi_se=float(ret.std(ddof=1) / math.sqrt(len(ret))) if len(ret) > 1 else None,
        expected=round(float(np.nansum(ev * stake)), 2),
        expected_roi=float(np.nanmean(ev)) if np.isfinite(ev).any() else None,
        win_rate=float(np.mean([t["status"] == "won" for t in st])),
        expected_win_rate=float(np.mean([t["p_fair"] for t in st if t.get("p_fair") is not None]))
        if any(t.get("p_fair") is not None for t in st) else None,
        avg_odds=float(np.mean([t["odds"] for t in st])),
        clv=float(clv.mean()) if len(clv) else None,
        beat_close=float((clv > 0).mean()) if len(clv) else None,
        max_drawdown=float(np.max(np.maximum.accumulate(np.r_[0, cum]) - np.r_[0, cum])),
    )
    out["luck"] = round(out["profit"] - out["expected"], 2)
    return out


def curve(trades: list[dict]) -> list[dict]:
    """Cumulative realized and expected profit by settle day."""
    days: dict = {}
    for t in trades:
        if t["status"] not in ("won", "lost") or t.get("ev") is None:
            continue
        d = str(t.get("settled_at") or t["commence_time"])[:10]
        g = days.setdefault(d, {"date": d, "profit": 0.0, "expected": 0.0, "n": 0})
        g["profit"] += t["profit"]
        g["expected"] += t["ev"] * t["stake"]
        g["n"] += 1
    out, cp, ce = [], 0.0, 0.0
    for d in sorted(days):
        g = days[d]
        cp, ce = cp + g["profit"], ce + g["expected"]
        out.append({"date": d, "n": g["n"], "realized": round(cp, 2), "expected": round(ce, 2)})
    return out


def pretty(key: str) -> str:
    """'tennis_atp_us_open' -> 'ATP US Open' (a fallback when the API's title isn't cached)."""
    tour, _, rest = key.removeprefix("tennis_").partition("_")
    words = {"us": "US", "atp": "ATP", "wta": "WTA"}
    return f"{tour.upper()} " + " ".join(words.get(w, w.capitalize()) for w in rest.split("_"))


def page(trades: list[dict], now: pd.Timestamp, titles: dict) -> dict:
    """portfolio.json for the page."""
    strategies = []
    for s in STRATEGIES:
        mine = [t for t in trades if t["strategy"] == s["id"]]
        mine.sort(key=lambda t: t["commence_time"], reverse=True)
        strategies.append({"id": s["id"], "name": s["name"], "rule": s["rule"], "summary": summary(mine),
                           "curve": curve(mine), "trades": mine})
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stake": STAKE,
        "scored_tournaments": sorted({titles.get(k) or pretty(k) for k in SCORED_KEYS}),
        "strategies": strategies,
    }
