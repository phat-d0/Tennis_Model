"""Load tennis-data.co.uk yearly result files (ATP + WTA) into one normalized table.

Source format: one row per match, winner/loser oriented, with closing odds per bookmaker
(B365W/B365L = Bet365, PSW/PSL = Pinnacle, MaxW/AvgW = best/average across books). The
WTA files have `Tier` where ATP has `Series`. Ranks can be "NR".

Normalized columns (one row per match):
  date, season, tour, tournament, location, tier, court, surface, round, round_idx,
  best_of, winner, loser, w_rank, l_rank, w_pts, l_pts, w1, l1, comment,
  odds_<book>_w, odds_<book>_l for each book in BOOKS (NaN when the file lacks it).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

# our book key -> tennis-data column prefix
BOOKS = {"b365": "B365", "ps": "PS", "max": "Max", "avg": "Avg"}

# Round labels used by tennis-data.co.uk, in playing order
ROUND_ORDER = {
    "1st Round": 1, "2nd Round": 2, "3rd Round": 3, "4th Round": 4,
    "Quarterfinals": 5, "Semifinals": 6, "The Final": 7, "Round Robin": 5,
}


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def normalize(raw: pd.DataFrame, tour: str) -> pd.DataFrame:
    """One tennis-data sheet -> normalized rows. `tour` is "atp" or "wta"."""
    r = raw.rename(columns=lambda c: str(c).strip())
    out = pd.DataFrame({
        "date": pd.to_datetime(r["Date"], errors="coerce"),
        "tour": tour,
        "tournament": r.get("Tournament", pd.Series(pd.NA, index=r.index)).astype("string"),
        "location": r.get("Location", pd.Series(pd.NA, index=r.index)).astype("string"),
        "tier": r.get("Series", r.get("Tier", pd.Series(pd.NA, index=r.index))).astype("string"),
        "court": r.get("Court", pd.Series(pd.NA, index=r.index)).astype("string"),
        "surface": r.get("Surface", pd.Series(pd.NA, index=r.index)).astype("string"),
        "round": r["Round"].astype("string").str.strip(),
        "best_of": _num(r.get("Best of", pd.Series(3, index=r.index))),
        "winner": r["Winner"].astype("string").str.strip(),
        "loser": r["Loser"].astype("string").str.strip(),
        "w_rank": _num(r.get("WRank")),
        "l_rank": _num(r.get("LRank")),
        "w_pts": _num(r.get("WPts")),
        "l_pts": _num(r.get("LPts")),
        "w1": _num(r.get("W1")),
        "l1": _num(r.get("L1")),
        "comment": r.get("Comment", pd.Series("Completed", index=r.index)).astype("string").str.strip(),
    })
    for key, prefix in BOOKS.items():
        for side, suffix in (("w", "W"), ("l", "L")):
            col = f"{prefix}{suffix}"
            v = _num(r[col]) if col in r else pd.Series(np.nan, index=r.index)
            out[f"odds_{key}_{side}"] = v.where(v > 1.0)  # decimal odds <= 1 are data errors
    out["round_idx"] = out["round"].map(ROUND_ORDER).astype("float64")
    out = out.dropna(subset=["date", "winner", "loser"])
    out["season"] = out["date"].dt.year.astype("int64")
    return out.reset_index(drop=True)


def load_dir(data_dir: str | Path, tours: tuple[str, ...] = ("atp", "wta")) -> pd.DataFrame:
    """Read every file under data_dir/<tour>/ (xlsx, xls or csv) and sort chronologically.

    Within a date, rows keep round order then file order, so ratings update in playing order.
    """
    frames = []
    for tour in tours:
        for path in sorted(Path(data_dir, tour).glob("*")):
            if path.suffix in (".xlsx", ".xls"):
                raw = pd.read_excel(path)
            elif path.suffix == ".csv":
                raw = pd.read_csv(path)
            else:
                continue
            frames.append(normalize(raw, tour))
    if not frames:
        raise FileNotFoundError(f"no tennis-data files under {data_dir}/{{{','.join(tours)}}}/")
    df = pd.concat(frames, ignore_index=True)
    df["_order"] = np.arange(len(df))
    df = df.sort_values(["date", "round_idx", "_order"], na_position="last", kind="stable")
    return df.drop(columns="_order").reset_index(drop=True)


def first_set_complete(w1: pd.Series, l1: pd.Series) -> pd.Series:
    """True when the first set reached a result (6-x with a 2-game lead, or 7-x)."""
    hi = np.maximum(w1, l1)
    lo = np.minimum(w1, l1)
    return ((hi >= 6) & (hi - lo >= 2)) | (hi == 7)


def void_mask(df: pd.DataFrame) -> pd.Series:
    """Bets a sportsbook would void: walkovers, and retirements before set 1 is complete
    (DraftKings' rule; Bet365 and Pinnacle also settle only after a completed set)."""
    c = df["comment"].fillna("").str.lower()
    walkover = c.str.startswith("walk")
    retired = c.str.startswith("ret") | c.str.startswith("disq")
    return walkover | (retired & ~first_set_complete(df["w1"], df["l1"]).fillna(False))
