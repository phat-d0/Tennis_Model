"""Load Jeff Sackmann's ATP/WTA match files (archival fork `phat-d0/tennis-sackmann-archive`,
CC BY-NC-SA 4.0: non-commercial, attribute Jeff Sackmann, never commit the CSVs) into the
normalized match frame `elo.add_elo` expects.

Source format: `<tour>/<tour>_matches_YYYY.csv`, one row per tour-level main-draw match, winner/
loser oriented, with seeds, entry codes, ranks and the score string ("6-3 4-1 RET", "W/O").
No odds. `tourney_date` is the tournament's start date, so matches are ordered by tournament
date, then round, then match_num.

Normalized columns (one row per match):
  date, season, tour, tourney_id, tournament, level, level_group, surface, draw_size, round,
  round_idx (1 = the tournament's first main-draw round; NaN for round robin etc.), best_of,
  winner, loser, winner_id, loser_id, w_seed, l_seed, w_entry, l_entry, w_rank, l_rank,
  w_pts, l_pts, score, w1, l1, comment (Completed | Walkover | Retired | Disqualified |
  Unfinished), void.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

from .load import first_set_complete

ROUND_SIZE = {"R128": 128, "R64": 64, "R32": 32, "R16": 16, "QF": 8, "SF": 4, "F": 2}
# Rows that aren't tour-level singles results (ITF/125 events coded into the WTA files).
SKIP_LEVELS = {"CC", "35+H", "50+H"}
SLAM = {"G"}
THOUSAND = {"atp": {"M"}, "wta": {"PM", "T1"}}
TEAM = {"D"}  # Davis Cup / Fed-BJK Cup ties
FINALS = {"F"}
STAT_COLS = ("minutes", "w_svpt", "w_1stWon", "w_2ndWon", "l_svpt", "l_1stWon", "l_2ndWon")


def level_group(tour: str, level: str) -> str:
    """slam | 1000 | other | team | finals. WTA 'P' (Premier/500, incl. Premier 5 until 2020)
    counts as other, as do ATP 'A' (250/500) and Olympics 'O'."""
    if level in SLAM:
        return "slam"
    if level in THOUSAND.get(tour, set()):
        return "1000"
    if level in TEAM:
        return "team"
    if level in FINALS:
        return "finals"
    return "other"


def parse_score(score) -> tuple[str, float, float]:
    """Score string -> (comment, first-set games of winner, of loser)."""
    s = "" if not isinstance(score, str) else score.strip()
    low = s.lower()
    if not s or "w/o" in low or "walkover" in low:
        return "Walkover", np.nan, np.nan
    if "ret" in low:
        comment = "Retired"
    elif "def" in low:
        comment = "Disqualified"
    elif "unfinished" in low:
        comment = "Unfinished"
    else:
        comment = "Completed"
    m = re.match(r"(\d+)-(\d+)", s)
    if not m:
        return comment, np.nan, np.nan
    return comment, float(m.group(1)), float(m.group(2))


def _first_round_size(draw_size: pd.Series, sizes: pd.Series, key: pd.Series) -> pd.Series:
    """Size of the first main-draw round: the draw size rounded up to a power of two (a 28 or
    56 draw has byes), or the largest round seen if that's bigger."""
    ds = pd.to_numeric(draw_size, errors="coerce")
    from_draw = 2.0 ** np.ceil(np.log2(ds.where(ds >= 2)))
    seen = sizes.groupby(key).transform("max")
    return np.fmax(from_draw, seen)


def normalize(raw: pd.DataFrame, tour: str, lower: bool = False) -> pd.DataFrame:
    """One Sackmann matches file -> normalized rows. `tour` is "atp" or "wta". `lower` marks a
    qualifying/Challenger/ITF file: every row gets level_group "lower" (Elo input only)."""
    r = raw
    if not lower:
        r = r[~r["tourney_level"].astype(str).isin(SKIP_LEVELS)]
        r = r[~r["tourney_name"].astype(str).str.contains(r"\b125\b", regex=True)]
    parsed = [parse_score(s) for s in r["score"]]
    comment = pd.Series([p[0] for p in parsed], index=r.index, dtype="string")
    w1 = pd.Series([p[1] for p in parsed], index=r.index, dtype="float64")
    l1 = pd.Series([p[2] for p in parsed], index=r.index, dtype="float64")
    level = r["tourney_level"].astype(str)
    num = lambda c: pd.to_numeric(r[c], errors="coerce")  # noqa: E731
    out = pd.DataFrame({
        "date": pd.to_datetime(r["tourney_date"].astype("Int64").astype(str), format="%Y%m%d",
                               errors="coerce"),
        "tour": tour,
        "tourney_id": r["tourney_id"].astype("string"),
        "tournament": r["tourney_name"].astype("string"),
        "level": level.astype("string"),
        "level_group": ["lower" if lower else level_group(tour, lv) for lv in level],
        "surface": r["surface"].astype("string").str.strip().str.capitalize(),
        "draw_size": num("draw_size"),
        "round": r["round"].astype("string").str.strip(),
        "best_of": num("best_of"),
        "winner": r["winner_name"].astype("string").str.strip(),
        "loser": r["loser_name"].astype("string").str.strip(),
        "winner_id": r["winner_id"].astype("string"),
        "loser_id": r["loser_id"].astype("string"),
        "w_seed": num("winner_seed"), "l_seed": num("loser_seed"),
        "w_entry": r["winner_entry"].astype("string"), "l_entry": r["loser_entry"].astype("string"),
        "w_rank": num("winner_rank"), "l_rank": num("loser_rank"),
        "w_pts": num("winner_rank_points"), "l_pts": num("loser_rank_points"),
        "score": r["score"].astype("string"),
        "w1": w1, "l1": l1, "comment": comment,
        "match_num": num("match_num"),
        # match length and serve stats (NaN where the file has none): used by upsets.elo_plus
        **{c: (num(c) if c in r else np.nan) for c in STAT_COLS},
    })
    size = out["round"].map(ROUND_SIZE).astype("float64")
    first = _first_round_size(out["draw_size"], size, out["tourney_id"])
    out["round_idx"] = np.log2(first / size) + 1
    out = out.dropna(subset=["date", "winner", "loser"])
    out["season"] = out["date"].dt.year.astype("int64")
    retired = out["comment"].isin(["Retired", "Disqualified", "Unfinished"])
    early_stop = retired & ~first_set_complete(out["w1"], out["l1"]).fillna(False).astype(bool)
    out["void"] = (out["comment"] == "Walkover") | early_stop
    return out.reset_index(drop=True)


def _order_key(df: pd.DataFrame) -> pd.Series:
    """Round order within a tournament: round robin and other unsized rounds before the
    knockout ('RR' precedes SF/F at the Finals); 'BR' (bronze) with the final."""
    key = df["round_idx"].copy()
    key[df["round"] == "BR"] = 99.0
    return key.fillna(0.0)


LOWER_FILES = {"atp": "qual_chall", "wta": "qual_itf"}


def load(root: str | Path, tours=("atp", "wta"), start: int = 1990, end: int | None = None,
         include_team: bool = True, lower: bool = False) -> pd.DataFrame:
    """Read <root>/<tour>/<tour>_matches_YYYY.csv for start <= YYYY <= end, in playing order.

    lower=True also reads the qualifying + Challenger (ATP) / qualifying + ITF (WTA) files, as
    level_group "lower": they feed Elo (qualifiers' recent wins) but never the tour-level tables."""
    frames = []
    for tour in tours:
        patterns = [(f"{tour}_matches_[0-9][0-9][0-9][0-9].csv", False)]
        if lower:
            patterns.append((f"{tour}_matches_{LOWER_FILES[tour]}_[0-9][0-9][0-9][0-9].csv", True))
        for pattern, is_lower in patterns:
            for path in sorted(Path(root, tour).glob(pattern)):
                year = int(path.stem[-4:])
                if year < start or (end is not None and year > end):
                    continue
                frames.append(normalize(pd.read_csv(path, low_memory=False), tour, lower=is_lower))
    if not frames:
        raise FileNotFoundError(f"no Sackmann match files under {root}/{{{','.join(tours)}}}/")
    df = pd.concat(frames, ignore_index=True)
    if not include_team:
        df = df[df["level_group"] != "team"]
    df["_round"] = _order_key(df)
    df = df.sort_values(["date", "_round", "match_num"], kind="stable", na_position="last")
    return df.drop(columns="_round").reset_index(drop=True)
