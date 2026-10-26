"""Live DraftKings + Pinnacle pre-match tennis odds recorder (The Odds API, free plan credits).

    python -m upsets.dk_live run [--floor 10] [--poll-min 60] [--discover-min 30] [--pre-min 15]
    python -m upsets.dk_live report [--out reports/upsets_dk_live.md]

Read-only research recorder; no bets. Loop:
- every `discover_min`: free /v4/sports -> active tennis_* keys; free /events per key -> commence times.
- every `poll_min`, for each active key with an event starting in the next `horizon_h` hours:
  /odds?bookmakers=draftkings,pinnacle&markets=h2h&oddsFormat=decimal (1 credit per key per call).
- one extra call per key ~`pre_min` before each match's commence time (skipped if the key was
  polled in the last `min_gap_min` minutes), so each match gets a near-closing price.
- stops cleanly when a call would take the balance below `floor` (OddsApi raises BudgetError),
  then writes the report.

Storage (never committed: data/ is gitignored and the API's terms forbid redistribution):
gzipped JSON snapshots under data/raw/odds_api/live/<key>/<ts>.json.gz, parse_h2h rows in
data/processed/odds_api_live/h2h.parquet, spends in data/raw/odds_api/live/spend.log (copy totals
to docs/data_inventory.md). The report is aggregates only: book margins, DK vs Pinnacle de-vigged
gap, DK price movement into the start.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .odds import devig_power, overround
from .odds_api import BudgetError, OddsApi, parse_h2h

ROOT = Path("data/raw/odds_api/live")
H2H = Path("data/processed/odds_api_live/h2h.parquet")
BOOKS = ("draftkings", "pinnacle")


def utcnow() -> pd.Timestamp:
    return pd.Timestamp(dt.datetime.now(dt.UTC))


class Recorder:
    def __init__(self, api: OddsApi, root: Path = ROOT, h2h_path: Path = H2H, poll_min: float = 60,
                 discover_min: float = 30, pre_min: float = 15, min_gap_min: float = 10,
                 horizon_h: float = 24, clock=utcnow, log=print):
        self.api, self.root, self.h2h_path = api, Path(root), Path(h2h_path)
        self.poll = pd.Timedelta(minutes=poll_min)
        self.discover_every = pd.Timedelta(minutes=discover_min)
        self.pre = pd.Timedelta(minutes=pre_min)
        self.min_gap = pd.Timedelta(minutes=min_gap_min)
        self.horizon = pd.Timedelta(hours=horizon_h)
        self.clock, self.log = clock, log
        self.keys: dict[str, list[pd.Timestamp]] = {}   # active key -> upcoming commence times
        self.last_discover: pd.Timestamp | None = None
        self.last_poll: dict[str, pd.Timestamp] = {}
        self.pre_done: set[tuple[str, pd.Timestamp]] = set()
        self.calls = 0
        self.stopped: str | None = None

    # -- discovery (free) --
    def discover(self, now: pd.Timestamp) -> None:
        active = [s["key"] for s in self.api.sports() if s["key"].startswith("tennis_") and s.get("active")]
        keys = {}
        for k in active:
            ev = self.api.events(k)
            keys[k] = sorted(pd.Timestamp(e["commence_time"]) for e in ev)
        self.keys, self.last_discover = keys, now

    # -- one paid snapshot --
    def snapshot(self, key: str, now: pd.Timestamp, why: str) -> None:
        events = self.api.odds(key, bookmakers=BOOKS)
        self.calls += 1
        self.last_poll[key] = now
        stamp = now.strftime("%Y%m%dT%H%M%SZ")
        p = self.root / key / f"{stamp}.json.gz"
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(p, "wt") as f:
            json.dump({"timestamp": now.isoformat(), "why": why, "data": events}, f)
        rows = parse_h2h(events, now.isoformat())
        if len(rows):
            self.h2h_path.parent.mkdir(parents=True, exist_ok=True)
            old = pd.read_parquet(self.h2h_path) if self.h2h_path.exists() else None
            pd.concat([old, rows.assign(why=why)] if old is not None else [rows.assign(why=why)],
                      ignore_index=True).to_parquet(self.h2h_path, index=False)
        self.log(f"{now:%Y-%m-%d %H:%M} {key} [{why}] events={len(events)} rows={len(rows)} "
                 f"balance={self.api.remaining:.0f}")

    def due(self, now: pd.Timestamp) -> list[tuple[str, str]]:
        """(key, why) calls due now: hourly polls for keys with a match in the horizon, and one
        pre-start call per match (once its commence - pre_min has passed, before commence)."""
        out = []
        for key, starts in self.keys.items():
            upcoming = [c for c in starts if now < c <= now + self.horizon]
            if not upcoming:
                continue
            last = self.last_poll.get(key)
            pre_due = [c for c in upcoming if c - self.pre <= now and (key, c) not in self.pre_done]
            if pre_due:
                self.pre_done.update((key, c) for c in pre_due)
                if last is None or now - last >= self.min_gap:
                    out.append((key, "pre-start"))
                    continue
            if last is None or now - last >= self.poll:
                out.append((key, "hourly"))
        return out

    def step(self) -> bool:
        """One loop iteration. Returns False once stopped at the floor."""
        now = self.clock()
        if self.last_discover is None or now - self.last_discover >= self.discover_every:
            self.discover(now)
        for key, why in self.due(now):
            try:
                self.snapshot(key, now, why)
            except BudgetError as e:
                self.stopped = f"floor reached: {e}"
                self.log(self.stopped)
                return False
        return True

    def run(self, tick_s: float = 60, until: pd.Timestamp | None = None, sleep=time.sleep) -> None:
        while self.step():
            if until is not None and self.clock() >= until:
                self.stopped = "until reached"
                break
            sleep(tick_s)


# --- report ----------------------------------------------------------------------------------

def closing_rows(h2h: pd.DataFrame) -> pd.DataFrame:
    """Per (event, book): first and last snapshot before commence; oriented to player_1."""
    pre = h2h[h2h["snapshot_ts"] < h2h["commence_time"]].sort_values("snapshot_ts")
    g = pre.groupby(["event_id", "book"])
    first, last = g.head(1).set_index(["event_id", "book"]), g.tail(1).set_index(["event_id", "book"])
    out = last[["sport_key", "commence_time", "odds_1", "odds_2", "snapshot_ts"]].copy()
    out["first_odds_1"], out["first_odds_2"] = first["odds_1"], first["odds_2"]
    out["first_ts"] = first["snapshot_ts"]
    out["n_snaps"] = g.size()
    return out.reset_index()


def report(h2h: pd.DataFrame, calls: int | None = None) -> str:
    c = closing_rows(h2h)
    c["margin"] = overround(c["odds_1"], c["odds_2"])
    c["p1"] = devig_power(c["odds_1"].to_numpy(), c["odds_2"].to_numpy())
    c["p1_first"] = devig_power(c["first_odds_1"].to_numpy(), c["first_odds_2"].to_numpy())
    c["mins_before"] = (c["commence_time"] - c["snapshot_ts"]).dt.total_seconds() / 60
    w = c.pivot(index="event_id", columns="book", values=["p1", "margin", "odds_1", "odds_2"])
    lines = ["# Live DraftKings vs Pinnacle tennis odds (free-plan recorder)", "",
             f"{h2h['snapshot_ts'].nunique():,} snapshots over {h2h['event_id'].nunique():,} events "
             f"({', '.join(sorted(h2h['sport_key'].unique()))}); "
             f"{'' if calls is None else f'{calls:,} paid calls; '}h2h, decimal. Aggregates only.", "",
             "## Book margin at the last pre-start snapshot", "",
             "| Book | Events | Mean margin | Median | Last snapshot, median min before start |", "|---|---|---|---|---|"]
    for book, g in c.groupby("book"):
        lines.append(f"| {book} | {len(g):,} | {g['margin'].mean():.2%} | {g['margin'].median():.2%} | "
                     f"{g['mins_before'].median():.0f} |")
    if {"draftkings", "pinnacle"} <= set(c["book"]):
        both = w.dropna(subset=[("p1", "draftkings"), ("p1", "pinnacle")])
        dk, pin = both[("p1", "draftkings")], both[("p1", "pinnacle")]
        dog_dk = np.minimum(dk, 1 - dk)
        dog_pin = np.where(dk < 0.5, pin, 1 - pin)   # same player as DK's underdog
        gap = dog_dk - dog_pin
        lines += ["", "## DraftKings vs Pinnacle, de-vigged (power method), same snapshot time", "",
                  f"Events with both books: {len(both):,}. DK underdog probability minus Pinnacle's for the "
                  f"same player: mean {gap.mean():+.2%}, mean |gap| {np.abs(gap).mean():.2%}, 90th percentile "
                  f"|gap| {np.quantile(np.abs(gap), 0.9):.2%}.", "",
                  "| DK underdog p | Events | Mean DK − Pinnacle |", "|---|---|---|"]
        bands = pd.cut(dog_dk, [0, 0.15, 0.25, 0.35, 0.5])
        for band, gg in pd.Series(gap, index=both.index).groupby(bands, observed=True):
            lines.append(f"| {band} | {len(gg):,} | {gg.mean():+.2%} |")
    lines += ["", "## Price movement into the start (first → last pre-start snapshot)", "",
              "| Book | Events with ≥ 2 snapshots | Mean |Δp| | 90th pct |Δp| | Mean hours covered |",
              "|---|---|---|---|---|"]
    for book, g in c[c["n_snaps"] >= 2].groupby("book"):
        d = (g["p1"] - g["p1_first"]).abs()
        hrs = (g["snapshot_ts"] - g["first_ts"]).dt.total_seconds() / 3600
        lines.append(f"| {book} | {len(g):,} | {d.mean():.2%} | {d.quantile(0.9):.2%} | {hrs.mean():.1f} |")
    lines += ["", "Results join (did the dog win at these prices?) comes later, once results for these "
              "events are available."]
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["run", "report"])
    ap.add_argument("--floor", type=int, default=10)
    ap.add_argument("--poll-min", type=float, default=60)
    ap.add_argument("--discover-min", type=float, default=30)
    ap.add_argument("--pre-min", type=float, default=15)
    ap.add_argument("--tick-s", type=float, default=60)
    ap.add_argument("--until", default=None, help="ISO time to stop (default: run until the floor)")
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--h2h", type=Path, default=H2H)
    ap.add_argument("--out", type=Path, default=Path("reports/upsets_dk_live.md"))
    a = ap.parse_args(argv)
    if a.cmd == "run":
        api = OddsApi(floor=a.floor, spend_log=a.root / "spend.log")
        rec = Recorder(api, a.root, a.h2h, a.poll_min, a.discover_min, a.pre_min)
        rec.run(a.tick_s, pd.Timestamp(a.until) if a.until else None)
        print(f"stopped: {rec.stopped}; paid calls {rec.calls}; balance {api.remaining}")
    if not a.h2h.exists():
        raise SystemExit("no snapshots recorded yet")
    text = report(pd.read_parquet(a.h2h))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
