"""Pre-match Elo rank of each player in Kalshi research matches, for Backtest's MISMATCH50 study.

    python -m upsets.elo_ranks --data data/processed/kalshi_g0 [--data data/processed/kalshi_g12] \
        --sackmann /path/to/tennis-sackmann-archive --out data/reports/elo_ranks.parquet

Runs where the Kalshi data lives (Data's machine). Writes one parquet row per match (match_id, rank_a,
rank_b, plus elo/n/matched columns) and prints the match rate. Nothing here is committed.

- Ratings: phase B's timeline (upsets.kalshi_elo.timeline): Sackmann tour + qualifying/Challenger/ITF
  results, then Kalshi settlements after Sackmann ends (May 2026), with the round_monotone and no-read
  guards. Overall Elo, players keyed per tour, so ATP and WTA are ranked separately. Challenger and
  WTA 125 matches are included (series KXATPCHALLENGERMATCH, KXWTACHALLENGERMATCH).
- Rank: 1 + the number of active players of the same tour rated higher than this player's pre-match
  Elo. Active = at least MIN_N rated matches and a match in the ACTIVE_DAYS before the match's day.
  The pool is a snapshot of ratings at the start of the match's UTC day, so it uses only earlier
  results. Results from the same day aren't in the pool yet.
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


def _pool_ranks(rows: pd.DataFrame, active_days: int = ACTIVE_DAYS, min_n: int = MIN_N) -> pd.DataFrame:
    """Replay the timeline (same updates as upsets.elo) and, for each Kalshi row, rank its winner-key and
    loser-key players' pre-match Elo within that tour's active pool at the start of the row's day.
    -> frame indexed like rows' Kalshi rows: w_rank, l_rank (NaN when n < min_n), pool."""
    rating, played, last = defaultdict(lambda: elo.START), defaultdict(int), {}
    tours, wk, lk = rows["tour"].to_numpy(), rows["wkey"].to_numpy(), rows["lkey"].to_numpy()
    days = pd.to_datetime(rows["time"]).to_numpy().astype("datetime64[D]")
    walk = rows["comment"].fillna("").str.lower().str.startswith("walk").to_numpy()
    is_k = rows["kalshi"].notna().to_numpy()
    snap_day, pools, own = None, {}, {}
    out = {"row": [], "w_rank": [], "l_rank": [], "pool": []}
    window = np.timedelta64(active_days, "D")
    for i in range(len(rows)):
        d = days[i]
        if is_k[i] and d != snap_day:
            snap_day = d
            vals, own = defaultdict(list), {}
            for (t, p), r in rating.items():
                if played[(t, p)] >= min_n and (t, p) in last and last[(t, p)] >= d - window:
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
                if p in own and own[p] > rating[p]:   # the player's own day-start entry isn't a rival
                    higher -= 1
                return float(1 + higher)
            out["row"].append(i)
            out["w_rank"].append(rank(w))
            out["l_rank"].append(rank(l))
            out["pool"].append(len(pool))
        if walk[i]:
            continue
        e = elo.expected(rating[w], rating[l])
        rating[w] += elo._k(played[w]) * (1 - e)
        rating[l] -= elo._k(played[l]) * (1 - e)
        played[w] += 1
        played[l] += 1
        last[w] = last[l] = d
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
    return out.reset_index(drop=True)


def summary(r: pd.DataFrame) -> str:
    lines = [f"[elo_ranks: {len(r):,} matches]"]
    for (series, _), g in r.groupby(["series", "tour"]):
        both = g["rank_a"].notna() & g["rank_b"].notna()
        names = pd.concat([g["matched_a"], g["matched_b"]])
        lines.append(f"  {series}: {len(g):,} matches; names matched {names.mean():.1%}; both ranked {both.mean():.1%}; "
                     f"median pool {g['pool'].median():,.0f}")
    return "\n".join(lines)


def main(argv=None) -> None:
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


if __name__ == "__main__":
    main()
