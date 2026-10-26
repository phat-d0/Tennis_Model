"""Kalshi per-set winner markets → a `sets` table next to matches/quotes.

Read-only. Kalshi lists one event per set (`KXATPSETWINNER-26OCT24FARBRU-2` = set 2 of the
match event `KXATPMATCH-26OCT24FARBRU`) with one market per player (`...-2-FAR`). A set
market's `close_time` is when the set ended; `result` says who won it.

    python -m swinglock.collectors.kalshi_sets --out data/processed/kalshi_g0

Listings only (no per-match calls): settled events with nested markets, plus the series'
`/historical/markets` for events settled before the cutoff. Responses are cached under the
raw dir like the backfill, so a rerun costs nothing. Rows are kept for match_ids present in
`<out>/matches.parquet`; the table is written to `<out>/sets.parquet`.
"""
from __future__ import annotations

import argparse
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable

import pandas as pd

from swinglock.collectors.kalshi import KalshiClient
from swinglock.collectors.kalshi_normalize import ts

log = logging.getLogger(__name__)

# set-winner series -> match-winner series (Challenger/WTA 125/ITF have no set markets, 2026-10-26)
SET_SERIES = {"KXATPSETWINNER": "KXATPMATCH", "KXWTASETWINNER": "KXWTAMATCH"}
SET_COLUMNS = ["match_id", "set_no", "event_ticker", "close_time", "settlement_ts",
               "winner_side", "status"]
_EVENT = re.compile(r"^(?P<series>[A-Z0-9]+)-(?P<code>[A-Z0-9]+)-(?P<set>\d+)$")


def parse_set_event(event_ticker: str) -> tuple[str, int] | None:
    """KXATPSETWINNER-26OCT24FARBRU-2 -> ('KXATPMATCH-26OCT24FARBRU', 2); None if not a set event."""
    m = _EVENT.match(event_ticker)
    if not m or m["series"] not in SET_SERIES:
        return None
    return f"{SET_SERIES[m['series']]}-{m['code']}", int(m["set"])


def _suffix(ticker) -> str:
    return str(ticker).rsplit("-", 1)[-1]


def set_row(event_ticker: str, markets: list[dict], sides: dict[str, str] | None = None) -> dict | None:
    """One row of the sets table. `sides` maps a player suffix (FAR) to 'A'/'B' (from the
    match's instrument tickers); without it the suffix listed first in the code is A.

    status: 'decided' (one market settled yes), 'fair_price' (scalar settlement: not started,
    or not decidable after a retirement), 'unsettled' otherwise."""
    parsed = parse_set_event(event_ticker)
    if parsed is None or not markets:
        return None
    match_id, set_no = parsed
    code = match_id.split("-", 1)[1]
    if sides is None:
        sfx = sorted({_suffix(m["ticker"]) for m in markets}, key=lambda s: (code.find(s) < 0, code.find(s), s))
        sides = {s: "AB"[i] for i, s in enumerate(sfx[:2])}
    results = [str(m.get("result") or "").lower() for m in markets]
    winners = [m for m, r in zip(markets, results) if r == "yes"]
    if len(winners) == 1:
        status, side = "decided", sides.get(_suffix(winners[0]["ticker"]))
    elif "scalar" in results:
        status, side = "fair_price", None
    else:
        status, side = "unsettled", None
    return {
        "match_id": match_id, "set_no": set_no, "event_ticker": event_ticker,
        "close_time": max((ts(m.get("close_time")) for m in markets), default=pd.NaT),
        "settlement_ts": max((ts(m.get("settlement_ts")) for m in markets), default=pd.NaT),
        "winner_side": side, "status": status,
    }


def sets_frame(rows: Iterable[dict | None]) -> pd.DataFrame:
    df = pd.DataFrame([r for r in rows if r], columns=SET_COLUMNS)
    for c in ("close_time", "settlement_ts"):
        df[c] = pd.to_datetime(df[c], utc=True).astype("datetime64[ns, UTC]")
    df["set_no"] = df["set_no"].astype("int64")
    df["winner_side"] = df["winner_side"].astype("string")
    return df.sort_values(["match_id", "set_no"]).reset_index(drop=True)


def match_sides(matches: pd.DataFrame) -> dict[str, dict[str, str]]:
    """match_id -> {player suffix: 'A'|'B'} from instrument_a/instrument_b."""
    return {r.match_id: {_suffix(r.instrument_a): "A", _suffix(r.instrument_b): "B"}
            for r in matches[["match_id", "instrument_a", "instrument_b"]].itertuples(index=False)}


def list_set_markets(client: KalshiClient, series: str, stats: dict) -> dict[str, list[dict]]:
    """event_ticker -> markets for every settled set event of a series (live + historical)."""
    events = list(client.events(series, status="settled"))
    out = {e["event_ticker"]: list(e.get("markets") or []) for e in events}
    stats["events"][series] = len(events)
    if any(not mk for mk in out.values()):
        hist: dict[str, list] = defaultdict(list)
        for m in client.historical_markets(series):
            hist[m["event_ticker"]].append(m)
        for ev, mk in out.items():
            if not mk:
                out[ev] = hist.get(ev, [])
        stats["historical_events"][series] = sum(1 for ev in out if ev in hist)
    return out


def collect(client: KalshiClient, matches: pd.DataFrame | None, series: Iterable[str] = SET_SERIES,
            stats: dict | None = None) -> pd.DataFrame:
    stats = stats if stats is not None else {}
    stats.setdefault("events", {})
    stats.setdefault("historical_events", {})
    sides = match_sides(matches) if matches is not None else {}
    wanted = set(sides) if matches is not None else None
    rows = []
    for s in series:
        for ev, mk in list_set_markets(client, s, stats).items():
            parsed = parse_set_event(ev)
            if parsed is None or (wanted is not None and parsed[0] not in wanted):
                continue
            rows.append(set_row(ev, mk, sides.get(parsed[0])))
    return sets_frame(rows)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, required=True, help="processed dir holding matches.parquet")
    ap.add_argument("--raw", type=Path, default=Path("data/raw/kalshi"))
    ap.add_argument("--series", nargs="*", default=list(SET_SERIES))
    ap.add_argument("--min-interval", type=float, default=1.0, help="seconds between requests")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = KalshiClient(raw_dir=args.raw, min_interval_s=args.min_interval)
    matches = pd.read_parquet(args.out / "matches.parquet")
    stats: dict = {}
    df = collect(client, matches, args.series, stats)
    df.to_parquet(args.out / "sets.parquet", index=False)
    print(f"sets: {len(df):,} rows, {df['match_id'].nunique():,} of {len(matches):,} matches; "
          f"status {df['status'].value_counts().to_dict()}; listings {stats}; "
          f"requests {client.requests_made}, cache hits {client.cache_hits}")


if __name__ == "__main__":
    main()
