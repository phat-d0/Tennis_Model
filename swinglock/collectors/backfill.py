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
from .kalshi import KalshiClient, KalshiError
from .kalshi_normalize import DEFAULT_MAX_CARRY_S, candles_to_quotes, match_row, matches_frame, ts

log = logging.getLogger("swinglock.backfill")

CHUNK_MIN = 4900   # minutes per candle request: 2 legs × 4900 < the 10,000-candle cap
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
        out.append({"event": e, "markets": mk, "historical": is_hist, "series": meta,
                    "fee_changes": fee_changes})
    out.sort(key=lambda r: max(ts(m.get("close_time")) for m in r["markets"]), reverse=True)
    return out[:max_matches] if max_matches else out


def normalize_one(client: KalshiClient, r: dict, starts: dict, stats: dict,
                  max_carry_s: float | None = DEFAULT_MAX_CARRY_S) -> tuple[dict, pd.DataFrame]:
    e, mk = r["event"], r["markets"]
    row = match_row(e, mk, r["series"], r["fee_changes"], starts.get(e["event_ticker"]))
    try:
        c = fetch_candles(client, [row["instrument_a"], row["instrument_b"]],
                          row["open_time"], row["close_time"], r["historical"])
    except KalshiError as err:
        log.warning("%s: candles failed (%s); match kept without quotes", e["event_ticker"], err)
        stats["skipped"]["candle error"] += 1
        c = {}
    q = candles_to_quotes(row["match_id"], row["instrument_a"], row["instrument_b"],
                          c.get(row["instrument_a"], []), c.get(row["instrument_b"], []),
                          until=row["close_time"], max_carry_s=max_carry_s)
    return row, q


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
        max_carry_s: float | None = DEFAULT_MAX_CARRY_S) -> dict:
    client = KalshiClient(raw_dir=raw_dir, min_interval_s=min_interval_s)
    t0 = time.time()
    cutoff = ts(client.historical_cutoff()["market_settled_ts"])
    since_ts = ts(since) if since else None
    stats: dict = {"events_listed": {}, "skipped": defaultdict(int)}
    starts = scheduled_starts(client, since)
    rows, quotes = [], []
    for s in series_list:
        todo = collect_series(client, s, cutoff, since_ts, max_matches, stats)
        log.info("%s: %d settled matches to normalize", s, len(todo))
        for i, r in enumerate(todo, 1):
            row, q = normalize_one(client, r, starts, stats, max_carry_s)
            rows.append(row)
            quotes.append(q)
            if i % 50 == 0:
                log.info("%s %d/%d matches, %d requests (%d cached, %d 429s)", s, i, len(todo),
                         client.requests_made, client.cache_hits, client.rate_limited)
        # Checkpoint after each series so finished series are usable while later ones run.
        matches, q = write_outputs(out_dir, rows, quotes)
        log.info("%s done: wrote %d matches, %d quote rows", s, len(matches), len(q))

    summary = summarize(matches, q, cutoff)
    summary.update({
        "run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "series": series_list, "since": since, "max_carry_s": max_carry_s,
        "events_listed": stats["events_listed"],
        "skipped": dict(stats["skipped"]), "requests": client.requests_made,
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
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    carry = (cfg.get("data") or {}).get("max_carry_s", DEFAULT_MAX_CARRY_S)
    print(json.dumps(run(a.series, a.out, a.raw, a.since, a.max_matches, a.min_interval, carry),
                     indent=1, default=str))


if __name__ == "__main__":
    main()
