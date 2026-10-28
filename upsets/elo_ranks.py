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
- reason_a / reason_b say why a rank is blank (null when ranked): `unmatched` (name not found),
  `few_matches` (under min_n rated matches; elo/n still give his provisional rating), `inactive` (nobody of
  that tour is in the active pool on the match day). The player's own activity is not required for a rank
  (he is playing this match), so `inactive` only shows up when the whole pool is empty.
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
    n_a, n_b, matched_a, matched_b, pool, reason_a, reason_b. Ranks are NaN for unmatched names or players
    with < min_n matches; reason_x says why (null when rank_x is set)."""
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
        few = out[f"n_{s}"] < min_n
        out[f"reason_{s}"] = pd.Series(np.select([~out[f"matched_{s}"], few], ["unmatched", "few_matches"],
                                                 "inactive"), index=out.index).where(out[f"rank_{s}"].isna())
    return out.reset_index(drop=True)


def summary(r: pd.DataFrame) -> str:
    lines = [f"[elo_ranks: {len(r):,} matches]"]
    for (series, _), g in r.groupby(["series", "tour"]):
        both = g["rank_a"].notna() & g["rank_b"].notna()
        names = pd.concat([g["matched_a"], g["matched_b"]])
        lines.append(f"  {series}: {len(g):,} matches; names matched {names.mean():.1%}; both ranked {both.mean():.1%}; "
                     f"median pool {g['pool'].median():,.0f}")
    why = pd.concat([r["reason_a"], r["reason_b"]]).value_counts()
    lines.append("  unranked players: " + (", ".join(f"{k} {v:,}" for k, v in why.items()) or "none"))
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
