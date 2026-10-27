"""Nightly lookback: run the paper rules over the recorder's order books with the backtest's swing sim.

    python -m swinglock.scanner.lookback                 # on the server: systemd timer, ~04:00 UTC
    python -m swinglock.scanner.lookback --no-fetch      # use cached settlements only (no requests)

Same rule definitions as the live paper engine (`paper.RULES` → `PaperRule.backtest_cfg`), same
simulator (`swinglock.backtest.swing.simulate`, mode "first"), at 0¢ and 1¢ slippage.

Incremental, so memory stays small on a 1–2 GB server: each run only simulates matches that have
settled since the last run, reading just the recorder day files around their start, and appends their
trades to `data/paper/lookback_trades.parquet`. `data/paper/lookback.json` holds the aggregates over
every processed match. Settlements come from `data/paper/settlements.json` (shared with the live paper
engine), else the recorder's matches table, else `GET /markets?tickers=` (one request per 50 matches;
only for matches whose scheduled start is over `settle_after_h` hours ago).

Everything stays under data/ on the server (gitignored). Read-only; no order code.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ..backtest.align import align, staleness_s
from ..backtest.swing import TRADE_COLUMNS, match_paths, simulate
from ..config import ROOT, load_config
from ..schema import MATCH_COLUMNS, conform
from .client import KalshiReadClient
from .engine import iso
from .paper import RULES, PaperRule, load_settlements, save_settlements, settlement_from_markets

log = logging.getLogger("swinglock.lookback")

SLIPPAGES = (0.0, 0.01)
SETTLE_AFTER_H = 6.0       # only look a match's result up this long after its scheduled start
DAY_PAD = timedelta(days=2)   # quotes for a match are read from day files within start ± this


def _day_files(root: Path) -> dict[str, list[Path]]:
    """{YYYY-MM-DD: [files]} for compacted day files and today's part directories."""
    out: dict[str, list[Path]] = {}
    if not root.exists():
        return out
    for p in root.iterdir():
        if p.suffix == ".parquet":
            out.setdefault(p.stem, []).append(p)
        elif p.is_dir():
            out.setdefault(p.name, []).extend(sorted(p.glob("part-*.parquet")))
    return out


def read_quotes(recorded: Path, match_ids: list[str], days: list[str]) -> pd.DataFrame:
    files = _day_files(recorded / "quotes")
    frames = [pd.read_parquet(f, filters=[("match_id", "in", match_ids)])
              for d in days for f in files.get(d, [])]
    frames = [f for f in frames if len(f)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _days_for(m: pd.DataFrame) -> list[str]:
    anchor = m["scheduled_start"].fillna(m["open_time"]).dropna()
    if anchor.empty:
        return []
    lo, hi = anchor.min() - DAY_PAD, anchor.max() + DAY_PAD
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(lo.normalize(), hi.normalize(), freq="D")]


def fetch_settlements(client: KalshiReadClient, pending: pd.DataFrame) -> dict[str, list[float]]:
    """{match_id: [pay_a, pay_b]} for the pending matches that have a result now."""
    if pending.empty:
        return {}
    tickers = [t for a, b in zip(pending["instrument_a"], pending["instrument_b"]) for t in (a, b)]
    markets = client.markets(tickers)
    out = {}
    for mid, a, b in zip(pending["match_id"], pending["instrument_a"], pending["instrument_b"]):
        pay = settlement_from_markets(markets, (a, b))
        if pay is not None:
            out[str(mid)] = list(pay)
    return out


def simulate_rules(aligned: pd.DataFrame, matches: pd.DataFrame, cfg: dict[str, Any],
                   rules: tuple[PaperRule, ...] = RULES) -> pd.DataFrame:
    """Trades for every rule at every slippage, tagged with `rule` and `slippage`."""
    paths = match_paths(aligned, matches, cfg)
    frames = []
    for r in rules:
        for slip in SLIPPAGES:
            t = simulate(paths, r.x, r.y, r.backtest_cfg(cfg, slip), r.mode)
            if len(t):
                frames.append(t.assign(rule=r.id, slippage=slip))
    cols = [*TRADE_COLUMNS, "rule", "slippage"]
    return pd.concat(frames, ignore_index=True)[cols] if frames else pd.DataFrame(columns=cols)


def aggregate(trades: pd.DataFrame, rules: tuple[PaperRule, ...] = RULES) -> list[dict]:
    rows = []
    for r in rules:
        for slip in SLIPPAGES:
            t = trades[(trades["rule"] == r.id) & (trades["slippage"] == slip)] if len(trades) else trades
            n = len(t)
            locked = int(t["locked"].sum()) if n else 0
            pnl = float(t["pnl"].sum()) if n else 0.0
            rows.append({
                "rule": r.id, "slippage": slip, "trades": n, "locked": locked,
                "lock_rate": round(locked / n, 4) if n else None,
                "pnl": round(pnl, 4), "pnl_per_trade": round(pnl / n, 4) if n else None,
                "win_rate": round(float((t["pnl"] > 0).mean()), 4) if n else None,
                "pnl_locked": round(float(t.loc[t["locked"], "pnl"].sum()), 4) if n else 0.0,
                "pnl_unlocked": round(float(t.loc[~t["locked"].astype(bool), "pnl"].sum()), 4) if n else 0.0,
                "capital": round(float(t["capital"].sum()), 4) if n else 0.0,
            })
    return rows


def by_day(trades: pd.DataFrame) -> list[dict]:
    """Per settlement day and rule, at 0¢ slippage."""
    t = trades[trades["slippage"] == 0.0] if len(trades) else trades
    if not len(t):
        return []
    day = pd.to_datetime(t["settle_ts"], utc=True).dt.strftime("%Y-%m-%d")
    g = t.assign(day=day).groupby(["day", "rule"])
    out = g.agg(trades=("pnl", "size"), locked=("locked", "sum"), pnl=("pnl", "sum")).reset_index()
    return [{"day": d, "rule": r, "trades": int(n), "locked": int(k), "pnl": round(float(v), 4)}
            for d, r, n, k, v in out[["day", "rule", "trades", "locked", "pnl"]].itertuples(index=False)]


def run(cfg: dict[str, Any], recorded: Path, out_dir: Path, client: KalshiReadClient | None,
        now: datetime | None = None, settle_after_h: float = SETTLE_AFTER_H) -> dict:
    now = now or datetime.now(timezone.utc)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_p, trades_p = out_dir / "lookback_state.json", out_dir / "lookback_trades.parquet"
    settle_p = out_dir / "settlements.json"
    try:
        processed = set(json.loads(state_p.read_text()).get("processed", []))
    except (OSError, ValueError):
        processed = set()

    mp = recorded / "matches.parquet"
    matches = conform(pd.read_parquet(mp), MATCH_COLUMNS) if mp.exists() else conform(pd.DataFrame(), MATCH_COLUMNS)
    matches = matches.drop_duplicates("match_id", keep="last")

    cache = load_settlements(settle_p)
    for mid, a, b in zip(matches["match_id"], matches["settle_a"], matches["settle_b"]):
        if pd.notna(a) and pd.notna(b):
            cache.setdefault(str(mid), [float(a), float(b)])
    todo = matches[~matches["match_id"].isin(processed)]
    anchor = todo["scheduled_start"].fillna(todo["open_time"])
    due = todo[anchor.notna() & (anchor < pd.Timestamp(now) - pd.Timedelta(hours=settle_after_h))]
    missing = due[~due["match_id"].isin(cache)]
    requests = 0
    if client is not None and len(missing):
        before = client.requests_made
        cache.update(fetch_settlements(client, missing))
        requests = client.requests_made - before
    save_settlements(settle_p, cache)

    ready = due[due["match_id"].isin(cache)].copy()
    if len(ready):
        pays = ready["match_id"].map(cache)
        ready["settle_a"] = [p[0] for p in pays]
        ready["settle_b"] = [p[1] for p in pays]
        ready["winner"] = [("A" if a == 1 else "B" if b == 1 else pd.NA) for a, b in pays]
    new = pd.DataFrame(columns=[*TRADE_COLUMNS, "rule", "slippage"])
    if len(ready):
        ids = ready["match_id"].astype(str).tolist()
        q = read_quotes(recorded, ids, _days_for(ready))
        if len(q):
            new = simulate_rules(align(q, ready, staleness_s(cfg)), ready, cfg)
        processed |= set(ids)

    old = pd.read_parquet(trades_p) if trades_p.exists() else new.iloc[:0]
    trades = pd.concat([old, new], ignore_index=True) if len(new) else old
    if len(new) or not trades_p.exists():
        tmp = trades_p.with_name(trades_p.name + ".tmp")
        trades.to_parquet(tmp, index=False)
        tmp.replace(trades_p)
    state_p.write_text(json.dumps({"processed": sorted(processed)}))

    settled_ids = set(trades["match_id"]) if len(trades) else set()
    summary = {
        "generated_at": iso(now),
        "source": "recorded order books (swinglock.collectors.recorder), backtest swing sim",
        "data_from": iso(pd.to_datetime(trades["entry_ts"], utc=True).min()) if len(trades) else None,
        "data_to": iso(pd.to_datetime(trades["settle_ts"], utc=True).max()) if len(trades) else None,
        "matches_recorded": int(len(matches)),
        "matches_processed": int(len(processed)),
        "matches_with_trades": int(len(settled_ids)),
        "matches_new_this_run": int(len(ready)),
        "matches_awaiting_result": int(len(due) - len(ready)),
        "settlement_requests": int(requests),
        "rules": [r.describe() for r in RULES],
        "by_rule": aggregate(trades),
        "by_day": by_day(trades),
    }
    tmp = out_dir / "lookback.json.tmp"
    tmp.write_text(json.dumps(summary, indent=1))
    tmp.replace(out_dir / "lookback.json")
    log.info("lookback: %d new settled matches, %d trades total, %d requests",
             len(ready), len(trades), requests)
    return summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Paper rules over recorded order books (read-only)")
    ap.add_argument("--config", default=None)
    ap.add_argument("--recorded", default=None, help="recorder out_dir (default: recorder.out_dir)")
    ap.add_argument("--out", default="data/paper")
    ap.add_argument("--no-fetch", action="store_true", help="don't request settlements from Kalshi")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    rec = Path(args.recorded or (cfg.get("recorder") or {}).get("out_dir", "data/recorded/kalshi"))
    out = Path(args.out)
    rec, out = (p if p.is_absolute() else ROOT / p for p in (rec, out))
    client = None if args.no_fetch else KalshiReadClient(
        min_interval=float((cfg.get("scanner") or {}).get("min_request_interval", 1.0)))
    run(cfg, rec, out, client)


if __name__ == "__main__":
    main()
