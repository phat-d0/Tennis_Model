"""Pre-match Elo rank of each player in Kalshi research matches, for Backtest's MISMATCH50 study.

    python -m upsets.elo_ranks --data data/processed/kalshi_g0 [--data data/processed/kalshi_g12] \
        --sackmann /path/to/tennis-sackmann-archive --out data/reports/elo_ranks.parquet

Runs where the Kalshi data lives (Data's machine). Writes one parquet row per match (match_id, rank_a,
rank_b, plus elo/n/matched columns) and prints the match rate. Nothing here is committed.

- Ratings: phase B's timeline (upsets.kalshi_elo.timeline): Sackmann tour + qualifying/Challenger/ITF
  results, then Kalshi settlements after Sackmann ends (May 2026), with the round_monotone and no-read
  guards. Overall Elo, players keyed per tour, so ATP and WTA are ranked separately. Challenger and
  WTA 125 matches are included (series KXATPCHALLENGERMATCH, KXWTACHALLENGERMATCH).
- Rank: integer, lower = better: 1 + the number of active players of the same tour rated higher than this
  player's pre-match Elo. A/B follow matches.parquet. Active = at least MIN_N rated matches and a match in
  the ACTIVE_DAYS before the match's day.
- No lookahead: the player's own Elo uses only his earlier matches (all finished before he plays again).
  The pool uses only results of matches that started at least FINISH_H hours before the match's UTC day
  began, so they finished before it started. Sackmann rows carry estimated times (tournament start + the
  round's share of the event), so for events inside Sackmann's span "finished" is an estimate; Kalshi rows
  use the real scheduled start.
- Left blank, never guessed: a player whose Kalshi name doesn't match one Sackmann player
  (upsets/names.py), or one with fewer than MIN_N rated matches. An unmatched player still counts in the
  pool once rated from Kalshi results (he is a real player); he just gets no rank himself.
- Staleness: after May 2026 only Kalshi-listed matches (tour, Challenger, WTA 125) update ratings;
  ITF-only players keep frozen ratings until they fall out of the active window.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import elo, sackmann
from . import kalshi_elo as ke
from .names import player_table

SERIES = {"KXATPMATCH": "atp", "KXWTAMATCH": "wta", "KXATPCHALLENGERMATCH": "atp", "KXWTACHALLENGERMATCH": "wta"}
ACTIVE_DAYS = 365
MIN_N = 10
FINISH_H = 6.0     # a result counts in the pool only if its match started this long before the day began


def _update(rating: dict, played: dict, last: dict, w, l, d) -> None:
    e = elo.expected(rating[w], rating[l])
    rating[w] += elo._k(played[w]) * (1 - e)
    rating[l] -= elo._k(played[l]) * (1 - e)
    played[w] += 1
    played[l] += 1
    last[w] = last[l] = d


def _pool_ranks(rows: pd.DataFrame, active_days: int = ACTIVE_DAYS, min_n: int = MIN_N,
                finish_h: float = FINISH_H) -> pd.DataFrame:
    """Replay the timeline (same updates as upsets.elo) and, for each Kalshi row, rank its winner-key and
    loser-key players' pre-match Elo within that tour's active pool.
    - The player's own Elo is exact (his earlier matches are all finished before he plays again).
    - The pool is a second, lagged replay: only rows that started at least `finish_h` hours before the
      match's UTC day began, so every result in it finished before the match started.
    -> frame indexed like rows' Kalshi rows: w_rank, l_rank (NaN when n < min_n or the pool is empty), pool."""
    rating, played, last = defaultdict(lambda: elo.START), defaultdict(int), {}
    lag_r, lag_n, lag_last = defaultdict(lambda: elo.START), defaultdict(int), {}
    tours, wk, lk = rows["tour"].to_numpy(), rows["wkey"].to_numpy(), rows["lkey"].to_numpy()
    times = pd.to_datetime(rows["time"]).to_numpy()
    days = times.astype("datetime64[D]")
    walk = rows["comment"].fillna("").str.lower().str.startswith("walk").to_numpy()
    is_k = rows["kalshi"].notna().to_numpy()
    lag = np.timedelta64(int(finish_h * 3600), "s")
    window = np.timedelta64(active_days, "D")
    snap_day, pools, own, j = None, {}, {}, 0
    out = {"row": [], "w_rank": [], "l_rank": [], "pool": []}
    for i in range(len(rows)):
        d = days[i]
        if is_k[i] and d != snap_day:
            snap_day, cutoff = d, d.astype("datetime64[s]") - lag
            while j < i and times[j] <= cutoff:     # lagged replay up to the cutoff
                if not walk[j]:
                    _update(lag_r, lag_n, lag_last, (tours[j], wk[j]), (tours[j], lk[j]), days[j])
                j += 1
            vals, own = defaultdict(list), {}
            for (t, p), r in lag_r.items():
                if lag_n[(t, p)] >= min_n and (t, p) in lag_last and lag_last[(t, p)] >= d - window:
                    vals[t].append(r)
                    own[(t, p)] = r
            pools = {t: np.sort(np.array(v)) for t, v in vals.items()}
        w, l = (tours[i], wk[i]), (tours[i], lk[i])
        if is_k[i]:
            pool = pools.get(tours[i], np.array([]))

            def rank(p):
                if played[p] < min_n or not len(pool):
                    return np.nan
                higher = len(pool) - np.searchsorted(pool, rating[p], side="right")
                if p in own and own[p] > rating[p]:   # the player's own pool entry isn't a rival
                    higher -= 1
                return float(1 + higher)
            out["row"].append(i)
            out["w_rank"].append(rank(w))
            out["l_rank"].append(rank(l))
            out["pool"].append(len(pool))
        if not walk[i]:
            _update(rating, played, last, w, l, d)
    return pd.DataFrame(out).set_index("row")


def ranks(matches: pd.DataFrame, sack: pd.DataFrame, active_days: int = ACTIVE_DAYS, min_n: int = MIN_N) -> pd.DataFrame:
    """One row per Kalshi match of SERIES: match_id, series, tour, start, rank_a, rank_b, elo_a, elo_b,
    n_a, n_b, matched_a, matched_b, pool. Ranks are NaN for unmatched names or players with < min_n matches."""
    players = player_table(sack)
    km = ke.kalshi_matches(matches, players, tours=SERIES)
    rows, km = ke.timeline(sack, km)
    pr = _pool_ranks(rows, active_days, min_n)
    kr = rows.loc[pr.index]
    pr["kalshi"] = kr["kalshi"].astype(int).to_numpy()
    pr["wkey"] = kr["wkey"].to_numpy()
    pr = pr.set_index("kalshi").reindex(km.index)
    a_key = km["id_a"].astype("string").fillna("k:" + km["player_a"].map(ke.name_key))
    a_is_w = (pr["wkey"] == a_key).fillna(False).to_numpy()
    out = pd.DataFrame({
        "match_id": km["match_id"], "series": km["series"], "tour": km["tour"], "start": km["start"],
        "rank_a": np.where(a_is_w, pr["w_rank"], pr["l_rank"]),
        "rank_b": np.where(a_is_w, pr["l_rank"], pr["w_rank"]),
        "elo_a": km["elo_a"], "elo_b": km["elo_b"], "n_a": km["n_a"], "n_b": km["n_b"],
        "matched_a": km["id_a"].notna(), "matched_b": km["id_b"].notna(), "pool": pr["pool"]})
    for s in ("a", "b"):   # unmatched names: blank, never guessed
        out.loc[~out[f"matched_{s}"], [f"rank_{s}", f"elo_{s}", f"n_{s}"]] = np.nan
        out[f"rank_{s}"] = out[f"rank_{s}"].round().astype("Int64")   # integer, lower = better; <NA> = blank
    return out.reset_index(drop=True)


def current(sack: pd.DataFrame, results: pd.DataFrame | None, now: pd.Timestamp,
            active_days: int = ACTIVE_DAYS, min_n: int = MIN_N) -> dict:
    """The live rank table for the VPS paper engine (data/paper/elo_ranks.json): every active player's Elo
    rank per tour as of `now`, from Sackmann results plus the recorder's settled Kalshi matches (`results`:
    a matches table with series, scheduled_start, player_a/b, settle_a; settled after Sackmann ends).
    Same ratings and pool rule as `ranks`. Players are keyed by upsets.names.name_key for the scanner's lookup.
    Each entry carries last_played, so a consumer can skip stale ratings."""
    players = player_table(sack)
    km = results if results is not None else pd.DataFrame(columns=["match_id", "series", "scheduled_start",
                                                                   "player_a", "player_b", "settle_a"])
    km = km[pd.to_datetime(km["scheduled_start"], utc=True) < now] if len(km) else km
    km = ke.kalshi_matches(km, players, tours=SERIES) if len(km) else None
    if km is not None and len(km):
        rows, _ = ke.timeline(sack, km)
    else:
        s = sack.copy()
        s["time"] = ke.round_monotone(s.assign(time=ke.estimated_time(s)))
        s["wkey"], s["lkey"] = s["winner_id"].astype(str), s["loser_id"].astype(str)
        rows = s.sort_values("time", kind="stable")[["tour", "time", "wkey", "lkey", "comment"]].reset_index(drop=True)
    rating, played, last = defaultdict(lambda: elo.START), defaultdict(int), {}
    days = pd.to_datetime(rows["time"]).to_numpy().astype("datetime64[D]")
    walk = rows["comment"].fillna("").str.lower().str.startswith("walk").to_numpy()
    for t, w, l, d, wk_ in zip(rows["tour"].to_numpy(), rows["wkey"].to_numpy(), rows["lkey"].to_numpy(), days, walk):
        if not wk_:
            _update(rating, played, last, (t, w), (t, l), d)
    today = np.datetime64(now.tz_convert("UTC").tz_localize(None).date(), "D")
    names = dict(zip(zip(players["tour"], players["id"].astype(str)), players["name"]))
    tours = {}
    for t in ("atp", "wta"):
        act = [(p, r) for (tt, p), r in rating.items()
               if tt == t and played[(tt, p)] >= min_n and last.get((tt, p), today) >= today - np.timedelta64(active_days, "D")]
        act.sort(key=lambda x: -x[1])
        out = []
        for i, (p, r) in enumerate(act):
            name = names.get((t, p)) or (p[2:] if str(p).startswith("k:") else None)
            out.append({"key": ke.name_key(name) if name else None, "name": name,
                        "sackmann_id": None if str(p).startswith("k:") else str(p), "rank": i + 1,
                        "elo": round(float(r), 1), "n": int(played[(t, p)]), "last_played": str(last[(t, p)])})
        tours[t] = out
    return {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "sackmann_through": sack["date"].max().strftime("%Y-%m-%d"),
            "results_through": None if km is None or not len(km) else km["start"].max().strftime("%Y-%m-%d"),
            "min_n": min_n, "active_days": active_days, "tours": tours}


def summary(r: pd.DataFrame) -> str:
    lines = [f"[elo_ranks: {len(r):,} matches]"]
    for (series, _), g in r.groupby(["series", "tour"]):
        both = g["rank_a"].notna() & g["rank_b"].notna()
        names = pd.concat([g["matched_a"], g["matched_b"]])
        lines.append(f"  {series}: {len(g):,} matches; names matched {names.mean():.1%}; both ranked {both.mean():.1%}; "
                     f"median pool {g['pool'].median():,.0f}")
    return "\n".join(lines)


def main(argv=None) -> None:
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "current":
        return main_current(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, action="append", required=True, help="dir(s) with matches.parquet")
    ap.add_argument("--sackmann", type=Path, required=True)
    ap.add_argument("--active-days", type=int, default=ACTIVE_DAYS)
    ap.add_argument("--min-n", type=int, default=MIN_N)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    matches = pd.concat([pd.read_parquet(d / "matches.parquet") for d in a.data], ignore_index=True)
    matches = matches.drop_duplicates("match_id")
    sack = sackmann.load(a.sackmann, start=1990, lower=True)
    r = ranks(matches, sack, a.active_days, a.min_n)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    r.to_parquet(a.out, index=False)
    print(summary(r))
    print(f"[written: {a.out}]")


def main_current(argv) -> None:
    """python -m upsets.elo_ranks current --sackmann <archive> [--results <matches.parquet> ...] --out elo_ranks.json"""
    import json
    ap = argparse.ArgumentParser(prog="upsets.elo_ranks current")
    ap.add_argument("--sackmann", type=Path, required=True)
    ap.add_argument("--results", type=Path, action="append", default=[], help="matches.parquet with settled results")
    ap.add_argument("--start", type=int, default=2010, help="first Sackmann season (2010 keeps RAM near 1 GB)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    sack = sackmann.load(a.sackmann, start=a.start, lower=True)
    res = pd.concat([pd.read_parquet(p) for p in a.results], ignore_index=True).drop_duplicates("match_id") \
        if a.results else None
    doc = current(sack, res, pd.Timestamp.now(tz="UTC"))
    a.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = a.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc))
    tmp.replace(a.out)   # atomic, like state.json
    print(f"[elo_ranks current: atp {len(doc['tours']['atp']):,}, wta {len(doc['tours']['wta']):,} active players; "
          f"sackmann through {doc['sackmann_through']}, results through {doc['results_through']}]")

if __name__ == "__main__":
    main()
