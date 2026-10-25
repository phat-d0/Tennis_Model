"""Pre-match Elo ratings (overall and per surface), computed strictly from earlier matches.

K-factor follows the FiveThirtyEight tennis Elo: K = 250 / (matches_played + 5) ** 0.4.
Walkovers don't update ratings. Rows must already be in playing order (load.load_dir).
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

START = 1500.0


def _k(n: int) -> float:
    return 250.0 / (n + 5) ** 0.4


def expected(r_a: float, r_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((r_b - r_a) / 400.0))


def add_elo(df: pd.DataFrame, keys: tuple[str, str] = ("winner", "loser")) -> pd.DataFrame:
    """Add pre-match columns w_elo, l_elo, w_selo, l_selo, w_n, l_n (matches played before).

    Players are keyed by (tour, <keys> column) so ATP and WTA pools never mix; pass
    keys=("winner_id", "loser_id") when the source has player ids (Sackmann).
    """
    rating: dict = defaultdict(lambda: START)
    s_rating: dict = defaultdict(lambda: START)
    played: dict = defaultdict(int)
    s_played: dict = defaultdict(int)
    n = len(df)
    cols = {c: np.empty(n) for c in ("w_elo", "l_elo", "w_selo", "l_selo", "w_n", "l_n")}
    walkover = df["comment"].fillna("").str.lower().str.startswith("walk").to_numpy()
    tours, surfaces = df["tour"].to_numpy(), df["surface"].fillna("?").to_numpy()
    winners, losers = df[keys[0]].to_numpy(), df[keys[1]].to_numpy()
    for i in range(n):
        w, l = (tours[i], winners[i]), (tours[i], losers[i])
        ws, ls = (w, surfaces[i]), (l, surfaces[i])
        cols["w_elo"][i], cols["l_elo"][i] = rating[w], rating[l]
        cols["w_selo"][i], cols["l_selo"][i] = s_rating[ws], s_rating[ls]
        cols["w_n"][i], cols["l_n"][i] = played[w], played[l]
        if walkover[i]:
            continue
        e = expected(rating[w], rating[l])
        rating[w] += _k(played[w]) * (1 - e)
        rating[l] -= _k(played[l]) * (1 - e)
        es = expected(s_rating[ws], s_rating[ls])
        s_rating[ws] += _k(s_played[ws]) * (1 - es)
        s_rating[ls] -= _k(s_played[ls]) * (1 - es)
        played[w] += 1
        played[l] += 1
        s_played[ws] += 1
        s_played[ls] += 1
    out = df.copy()
    for c, v in cols.items():
        out[c] = v
    return out
