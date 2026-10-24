"""Backfill settled Kalshi tennis matches → data/processed/kalshi/{matches,quotes}.parquet.

    python -m swinglock.collectors.backfill                  # all series in config.yaml
    python -m swinglock.collectors.backfill --series KXATPMATCH --max-matches 20

Steps per series: series meta + fee history → settled events (nested markets) → for events
whose markets settled before GET /historical/cutoff, their markets from /historical/markets
→ 1-minute candles per match (batch endpoint for live markets, /historical/... per market
for archived ones) → normalize. Scheduled starts come from tennis milestones, listed in bulk.

Resumable: every response is cached under data/raw/kalshi/ by the client, so a rerun only
fetches what's missing (listings refresh after 6 hours). Read-only; no order code.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import load_config
from ..schema import MATCH_COLUMNS, QUOTE_COLUMNS, empty, validate_quotes
from .kalshi import KalshiClient, KalshiError, batch_candle_params
from .kalshi_normalize import DEFAULT_MAX_CARRY_S, candles_to_quotes, match_row, matches_frame, order_markets, tier, ts

log = logging.getLogger("swinglock.backfill")

CHUNK_MIN = 4900   # minutes per candle request: 2 legs × 4,901 requested candles ≤ 10,000
PAD_S = 60


def windows(start: pd.Timestamp, end: pd.Timestamp, chunk_min: int = CHUNK_MIN) -> list[tuple[int, int]]:
    s, e = int(start.timestamp()) - PAD_S, int(end.timestamp()) + PAD_S
    step = chunk_min * 60
    return [(a, min(a + step, e)) for a in range(s, e, step)]


def fetch_candles(client: KalshiClient, tickers: list[str], start, end, historical: bool) -> dict[str, list]:
    out: dict[str, list] = {t: [] for t in tickers}
    for a, b in windows(start, end):
        if historical:
            for t in tickers:
                out[t] += client.historical_candles(t, a, b)
        else:
            for t, cs in client.batch_candles(tickers, a, b).items():
                out.setdefault(t, []).extend(cs)
    return out


# GET /markets/candlesticks rejects (HTTP 400) a request whose *requested* candles,
# tickers × window minutes, exceed 10,000 ("requested candlesticks across all markets:
# 10002, max candlesticks: 10000"; checked live 2026-10-24). Returned candles don't matter.
BATCH_CANDLE_CAP = 10_000
MAX_TICKERS = 100


def _span(r: dict) -> tuple[int, int]:
    return int(r["open"].timestamp()) - PAD_S, int(r["close"].timestamp()) + PAD_S


def requested_candles(n_tickers: int, lo: int, hi: int, period_s: int = 60) -> int:
    return n_tickers * ((hi - lo) // period_s + 1)


def plan_batches(items: list[dict]) -> list[list[dict]]:
    """Group live (post-cutoff) matches, in open-time order, into shared candle requests:
    ≤ 100 tickers and tickers × union-window minutes within the 10,000 cap. Matches that
    open and close close together share a request (typically 2-3 same-day matches)."""
    out, cur, lo, hi = [], [], None, None
    for r in sorted(items, key=lambda r: (r["open"], r["close"])):
        a, b = _span(r)
        if cur:
            n, lo2, hi2 = 2 * (len(cur) + 1), min(lo, a), max(hi, b)
            if n > MAX_TICKERS or requested_candles(n, lo2, hi2) > BATCH_CANDLE_CAP:
                out.append(cur)
                cur = []
        if not cur:
            cur, lo, hi = [r], a, b
        else:
            cur.append(r)
            lo, hi = min(lo, a), max(hi, b)
    if cur:
        out.append(cur)
    return out


def prefetch_batch(client: KalshiClient, batch: list[dict], stats: dict) -> None:
    """Fetch candles for several live matches in one call and store each match's share in the
    cache under the exact per-match request fetch_candles() makes, so it becomes a cache hit
    (and reruns stay cache hits even if the matches are grouped differently)."""
    todo = []
    for r in batch:
        w = windows(r["open"], r["close"])
        if len(w) == 1 and not client.has_cached(
                "/markets/candlesticks", batch_candle_params(r["tickers"], *w[0])):
            todo.append(r)
    if len(todo) < 2:
        return  # nothing to gain; fetch_candles does the single request
    lo = min(_span(r)[0] for r in todo)
    hi = max(_span(r)[1] for r in todo)
    tickers = [t for r in todo for t in r["tickers"]]
    try:
        d = client.get("/markets/candlesticks", batch_candle_params(tickers, lo, hi), cache=False)
    except KalshiError as err:
        if err.status == 0:
            return  # network: let the per-match path (with its outage pauses) handle it
        stats["group_errors"] += 1
        log.warning("group of %d matches failed (%s); falling back to per-match", len(todo), str(err)[:200])
        return
    got = {m["market_ticker"]: m.get("candlesticks") or [] for m in d.get("markets") or []}
    stats["grouped_matches"] += len(todo)
    for r in todo:
        a, b = windows(r["open"], r["close"])[0]
        markets = [{"market_ticker": t,
                    "candlesticks": [c for c in got.get(t, []) if a <= c["end_period_ts"] <= b]}
                   for t in r["tickers"]]
        client.store("/markets/candlesticks", batch_candle_params(r["tickers"], a, b), {"markets": markets})


def priority(r: dict, now: pd.Timestamp, recent_days: int) -> int:
    """0: recent ATP/WTA · 1: recent Challenger · 2: everything else (older, ITF)."""
    recent = r["close"] >= now - pd.Timedelta(days=recent_days)
    if recent and r["tier"] in ("atp", "wta"):
        return 0
    if recent and r["tier"] == "challenger":
        return 1
    return 2


def scheduled_starts(client: KalshiClient, since: str | None) -> dict[str, str]:
    """event_ticker → milestone start_date for tennis singles (one bulk listing)."""
    filt: dict[str, Any] = {"type": "tennis_tournament_singles"}
    if since:
        filt["minimum_start_date"] = since
    out = {}
    for m in client.milestones(**filt):
        start = m.get("start_date")
        main = (m.get("details") or {}).get("main_game_event_ticker")
        for ev in [main, *(m.get("primary_event_tickers") or [])]:
            if ev and start:
                out.setdefault(ev, start)
    return out


def collect_series(client: KalshiClient, series: str, cutoff: pd.Timestamp, since: pd.Timestamp | None,
                   max_matches: int | None, stats: dict) -> list[dict]:
    """Settled matches of one series: [{event, markets, historical}]."""
    meta = client.series(series)
    fee_changes = client.series_fee_changes(series)
    events = list(client.events(series, status="settled"))
    stats["events_listed"][series] = len(events)
    hist: dict[str, list] = defaultdict(list)
    if any(len(e.get("markets") or []) < 2 for e in events):
        for m in client.historical_markets(series):
            hist[m["event_ticker"]].append(m)
    out = []
    for e in events:
        mk, is_hist = e.get("markets") or [], False
        if len(mk) < 2:
            mk, is_hist = hist.get(e["event_ticker"], []), True
        if len(mk) != 2:
            stats["skipped"][f"{len(mk)} markets"] += 1
            continue
        close = max(ts(m.get("close_time")) for m in mk)
        if since is not None and close < since:
            continue
        settled = [ts(m.get("settlement_ts")) for m in mk]
        if not is_hist and all(pd.notna(s) and s < cutoff for s in settled):
            is_hist = True
        a, b = order_markets(e["event_ticker"], mk)
        out.append({"event": e, "markets": mk, "historical": is_hist, "series": meta,
                    "fee_changes": fee_changes, "tier": tier(series), "close": close,
                    "open": min(ts(m.get("open_time")) for m in mk), "tickers": [a["ticker"], b["ticker"]]})
    out.sort(key=lambda r: r["close"], reverse=True)
    return out[:max_matches] if max_matches else out


def normalize_one(client: KalshiClient, r: dict, starts: dict, stats: dict,
                  max_carry_s: float | None = DEFAULT_MAX_CARRY_S,
                  raise_network: bool = False) -> tuple[dict, pd.DataFrame]:
    e, mk = r["event"], r["markets"]
    row = match_row(e, mk, r["series"], r["fee_changes"], starts.get(e["event_ticker"]))
    try:
        c = fetch_candles(client, [row["instrument_a"], row["instrument_b"]],
                          row["open_time"], row["close_time"], r["historical"])
    except KalshiError as err:
        if raise_network and err.status == 0:
            raise
        log.warning("%s: candles failed (%s); match kept without quotes", e["event_ticker"], err)
        stats["skipped"]["candle error"] += 1
        c = {}
    q = candles_to_quotes(row["match_id"], row["instrument_a"], row["instrument_b"],
                          c.get(row["instrument_a"], []), c.get(row["instrument_b"], []),
                          until=row["close_time"], max_carry_s=max_carry_s)
    return row, q


NETWORK_PAUSE_S = 120
NETWORK_MAX_PAUSES = 15


def normalize_one_patiently(client: KalshiClient, r: dict, starts: dict, stats: dict,
                            max_carry_s: float | None, sleep=time.sleep) -> tuple[dict, pd.DataFrame]:
    """normalize_one, but a network outage (KalshiError status 0) pauses and retries the match
    instead of recording it without quotes; gives up (raises) after ~30 min of outage."""
    for attempt in range(NETWORK_MAX_PAUSES + 1):
        try:
            return normalize_one(client, r, starts, stats, max_carry_s, raise_network=True)
        except KalshiError as err:
            if err.status != 0 or attempt == NETWORK_MAX_PAUSES:
                raise
            stats["network_pauses"] += 1
            log.warning("network down (%s); pausing %ds", str(err)[:120], NETWORK_PAUSE_S)
            sleep(NETWORK_PAUSE_S)
    raise AssertionError("unreachable")


def write_outputs(out_dir: Path, rows: list[dict], quotes: list[pd.DataFrame]):
    matches = matches_frame(rows)
    q = pd.concat(quotes, ignore_index=True) if quotes else empty(QUOTE_COLUMNS)
    validate_quotes(q)
    out_dir.mkdir(parents=True, exist_ok=True)
    matches.to_parquet(out_dir / "matches.parquet", index=False)
    q.to_parquet(out_dir / "quotes.parquet", index=False)
    return matches, q


def run(series_list: list[str], out_dir: Path, raw_dir: Path, since: str | None = None,
        max_matches: int | None = None, min_interval_s: float = 0.5,
        max_carry_s: float | None = DEFAULT_MAX_CARRY_S, recent_days: int = 183,
        checkpoint_every: int = 1000) -> dict:
    """Work order: recent (≤ recent_days) ATP+WTA, then recent Challenger, then the rest,
    newest first within each group. Outputs are rewritten after each group and every
    `checkpoint_every` matches, so the finished part is usable while the rest runs."""
    client = KalshiClient(raw_dir=raw_dir, min_interval_s=min_interval_s)
    t0 = time.time()
    now = pd.Timestamp.now(tz="UTC")
    cutoff = ts(client.historical_cutoff()["market_settled_ts"])
    since_ts = ts(since) if since else None
    stats: dict = {"events_listed": {}, "skipped": defaultdict(int), "group_errors": 0,
                   "grouped_matches": 0, "network_pauses": 0}
    starts = scheduled_starts(client, since)
    todo = []
    for s in series_list:
        found = collect_series(client, s, cutoff, since_ts, max_matches, stats)
        log.info("%s: %d settled matches listed", s, len(found))
        todo += found
    for r in todo:
        r["prio"] = priority(r, now, recent_days)
    todo.sort(key=lambda r: (r["prio"], -r["close"].timestamp()))
    groups = defaultdict(int)
    for r in todo:
        groups[r["prio"]] += 1
    log.info("work order: %s matches by priority group (0 recent ATP/WTA, 1 recent Challenger, 2 rest)",
             dict(groups))

    rows, quotes = [], []
    matches, q = matches_frame([]), empty(QUOTE_COLUMNS)
    i = 0
    for prio in sorted(groups):
        part = [r for r in todo if r["prio"] == prio]
        # Live matches go in batches of several per candle request; archived ones can't.
        batches = plan_batches([r for r in part if not r["historical"]])
        batch_of = {id(r): bt for bt in batches for r in bt}
        done_batches: set[int] = set()
        for r in part:
            bt = batch_of.get(id(r))
            if bt is not None and id(bt) not in done_batches:
                prefetch_batch(client, bt, stats)
                done_batches.add(id(bt))
            row, qq = normalize_one_patiently(client, r, starts, stats, max_carry_s)
            rows.append(row)
            quotes.append(qq)
            i += 1
            if i % 50 == 0:
                log.info("group %d: %d/%d matches overall, %d requests (%d cached, %d 429s, %d grouped)",
                         prio, i, len(todo), client.requests_made, client.cache_hits,
                         client.rate_limited, stats["grouped_matches"])
            if i % checkpoint_every == 0:
                matches, q = write_outputs(out_dir, rows, quotes)
                log.info("checkpoint: wrote %d matches, %d quote rows", len(matches), len(q))
        matches, q = write_outputs(out_dir, rows, quotes)
        log.info("group %d done: wrote %d matches, %d quote rows (%d requests so far)",
                 prio, len(matches), len(q), client.requests_made)

    summary = summarize(matches, q, cutoff)
    summary.update({
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "series": series_list, "since": since, "max_carry_s": max_carry_s,
        "events_listed": stats["events_listed"],
        "skipped": dict(stats["skipped"]), "requests": client.requests_made,
        "grouped_matches": stats["grouped_matches"], "group_errors": stats["group_errors"],
        "network_pauses": stats["network_pauses"],
        "cache_hits": client.cache_hits, "rate_limited_429": client.rate_limited,
        "final_min_interval_s": client.min_interval_s, "elapsed_s": round(time.time() - t0),
    })
    with open(out_dir / "backfill_runs.jsonl", "a") as f:
        f.write(json.dumps(summary, default=str) + "\n")
    return summary


def summarize(matches: pd.DataFrame, quotes: pd.DataFrame, cutoff=None) -> dict:
    has_q = matches["match_id"].isin(quotes["match_id"].unique())
    return {
        "historical_cutoff": str(cutoff),
        "matches": int(len(matches)),
        "matches_with_quotes": int(has_q.sum()),
        "matches_per_tier": matches["tier"].value_counts().to_dict(),
        "winner_counts": matches["winner"].value_counts(dropna=False).astype(int)
                         .rename(index=lambda k: "NA" if pd.isna(k) else k).to_dict(),
        "with_scheduled_start": int(matches["scheduled_start"].notna().sum()),
        "close_time_range": [str(matches["close_time"].min()), str(matches["close_time"].max())],
        "quote_rows": int(len(quotes)),
        "quote_ts_range": [str(quotes["ts"].min()), str(quotes["ts"].max())] if len(quotes) else None,
        "ask_nan_share": round(float(quotes["ask"].isna().mean()), 4) if len(quotes) else None,
    }


def main(argv: list[str] | None = None) -> None:
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--series", nargs="*", default=cfg["scanner"]["series"])
    ap.add_argument("--since", help="only matches closing on/after this date (ISO)")
    ap.add_argument("--max-matches", type=int, help="per series, newest first (for test runs)")
    ap.add_argument("--out", type=Path, default=Path(cfg["data"]["processed_dir"]) / "kalshi")
    ap.add_argument("--raw", type=Path, default=Path(cfg["data"]["raw_dir"]) / "kalshi")
    ap.add_argument("--min-interval", type=float, default=0.5, help="seconds between requests")
    ap.add_argument("--recent-days", type=int, default=183, help="'recent' window for the work order")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    carry = (cfg.get("data") or {}).get("max_carry_s", DEFAULT_MAX_CARRY_S)
    print(json.dumps(run(a.series, a.out, a.raw, a.since, a.max_matches, a.min_interval, carry,
                         a.recent_days),
                     indent=1, default=str))


if __name__ == "__main__":
    main()
