"""Reframe winner/loser rows as favourite vs underdog, using only pre-match information.

The favourite is the side with the shorter odds at the reference book (Pinnacle, else the
market average, else Bet365), so orientation never depends on the result. `upset` = the
underdog won. Model features describe the underdog relative to the favourite.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .load import BOOKS, void_mask
from .odds import devig_power

REF_BOOKS = ("ps", "avg", "b365")
FEATURES = ["mkt_logit", "elo_diff", "selo_diff", "log_rank_ratio", "bo5", "early"]
UNRANKED = 1500.0  # rank given to "NR" players


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def build(matches: pd.DataFrame, early_rounds: int = 2) -> pd.DataFrame:
    """matches (load + elo columns) -> one row per match with a market reference price.

    Rows with no reference odds are dropped. `early` = round_idx <= early_rounds.
    """
    ref_w = pd.Series(np.nan, index=matches.index)
    ref_l = pd.Series(np.nan, index=matches.index)
    ref_book = pd.Series(pd.NA, index=matches.index, dtype="string")
    for b in REF_BOOKS:
        take = ref_w.isna() & matches[f"odds_{b}_w"].notna() & matches[f"odds_{b}_l"].notna()
        ref_w[take], ref_l[take] = matches.loc[take, f"odds_{b}_w"], matches.loc[take, f"odds_{b}_l"]
        ref_book[take] = b
    keep = ref_w.notna()
    m, ref_w, ref_l, ref_book = matches[keep], ref_w[keep], ref_l[keep], ref_book[keep]

    # Favourite = shorter reference price; exact ties go to the better-ranked player.
    w_rank = m["w_rank"].fillna(UNRANKED)
    l_rank = m["l_rank"].fillna(UNRANKED)
    dog_is_w = (ref_w > ref_l) | ((ref_w == ref_l) & (w_rank > l_rank))

    def pick(w_col, l_col, dog: bool):
        w, l = m[w_col], m[l_col]
        return w.where(dog_is_w, l) if dog else l.where(dog_is_w, w)

    out = pd.DataFrame({
        "date": m["date"], "season": m["season"], "tour": m["tour"],
        "tournament": m["tournament"], "tier": m["tier"], "surface": m["surface"],
        "round": m["round"], "round_idx": m["round_idx"], "best_of": m["best_of"],
        "fav": pick("winner", "loser", False), "dog": pick("winner", "loser", True),
        "fav_rank": w_rank.where(~dog_is_w, l_rank), "dog_rank": w_rank.where(dog_is_w, l_rank),
        "upset": dog_is_w.astype(int),
        "void": void_mask(m).to_numpy(),
        "ref_book": ref_book,
    }, index=m.index)
    dog_ref = ref_w.where(dog_is_w, ref_l)
    fav_ref = ref_l.where(dog_is_w, ref_w)
    out["p_mkt"] = devig_power(dog_ref.to_numpy(), fav_ref.to_numpy())
    for b in BOOKS:
        out[f"odds_dog_{b}"] = pick(f"odds_{b}_w", f"odds_{b}_l", True)
        out[f"odds_fav_{b}"] = pick(f"odds_{b}_w", f"odds_{b}_l", False)

    out["mkt_logit"] = _logit(out["p_mkt"].to_numpy())
    out["elo_diff"] = (pick("w_elo", "l_elo", True) - pick("w_elo", "l_elo", False)) / 400.0
    out["selo_diff"] = (pick("w_selo", "l_selo", True) - pick("w_selo", "l_selo", False)) / 400.0
    out["log_rank_ratio"] = np.log(out["dog_rank"] / out["fav_rank"])
    out["min_history"] = np.minimum(pick("w_n", "l_n", True), pick("w_n", "l_n", False))
    out["bo5"] = (out["best_of"] == 5).astype(float)
    out["early"] = (out["round_idx"] <= early_rounds).astype(float)
    return out.reset_index(drop=True)
