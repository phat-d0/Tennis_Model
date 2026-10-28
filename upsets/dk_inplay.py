"""DraftKings in-play studies (DOG50, exit-level curve, MISMATCH50, FAVDIP on DK prices): credit dry run.
Plan only, pre-registered in reports/upsets_dk_inplay.md. This module makes no paid call.

    python -m upsets.dk_inplay plan [--sackmann PATH]

Universe: the early-round matches we already hold DraftKings + Pinnacle closes for (upsets.dk_history.collect,
from the cached Odds API snapshots, 0 credits), with Sackmann results (through May 2026).

Cost model (docs/research/odds_api.md §4): one /v4/historical/sports/{key}/odds snapshot = 10 credits for
h2h with draftkings + pinnacle (one region block), and it returns every event of that key at that moment,
in-play ones included. So the cost is 10 x the distinct (key, snapshot time) pairs that fall inside any
match's live window. Live window = [commence_time, commence_time + match minutes + slack]; Sackmann's
`minutes`, else the median for that best-of. The slack covers late starts ("followed by" scheduling).
The archive is 10-min before 2022-09-18 and 5-min after, so a 5-min plan uses 10 min before that date.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

FIVE_MIN_FROM = pd.Timestamp("2022-09-18", tz="UTC")
CREDITS_PER_SNAPSHOT = 10
MAX_MINUTES = 360


def windows(priced: pd.DataFrame, sack: pd.DataFrame) -> pd.DataFrame:
    """One row per priced match: key, commence (UTC), dur (minutes), season, level."""
    s = sack.loc[priced["sack_row"].to_numpy()].reset_index(drop=True)
    w = pd.DataFrame({"key": priced["key"].to_numpy(), "commence": pd.to_datetime(priced["commence"].to_numpy(), utc=True),
                      "minutes": s["minutes"].to_numpy(), "best_of": s["best_of"].to_numpy(),
                      "season": s["season"].to_numpy(), "level": s["level_group"].to_numpy()})
    med = w.groupby("best_of")["minutes"].median()
    w["dur"] = w["minutes"].fillna(w["best_of"].map(med)).fillna(med.max() if len(med) else 120).clip(upper=MAX_MINUTES)
    return w.drop(columns="minutes")


def slots(w: pd.DataFrame, step_min: int = 5, slack_min: int = 180) -> set:
    """Distinct (key, snapshot time) pairs covering every live window."""
    out = set()
    for k, c, d in zip(w["key"], w["commence"], w["dur"]):
        step = step_min if c >= FIVE_MIN_FROM else max(step_min, 10)
        a = c.floor(f"{step}min")
        for x in pd.date_range(a, c + pd.Timedelta(minutes=float(d) + slack_min), freq=f"{step}min"):
            out.add((k, x))
    return out


def credits(w: pd.DataFrame, step_min: int = 5, slack_min: int = 180) -> int:
    return CREDITS_PER_SNAPSHOT * len(slots(w, step_min, slack_min))


VARIANTS = [("All seasons (2020–May 2026)", None), ("2023–May 2026 (5-min archive)", 2023),
            ("2024–May 2026", 2024), ("2025–May 2026", 2025)]


def plan(w: pd.DataFrame) -> str:
    L = ["| Universe | Matches | 5 min, +1 h slack | 5 min, +3 h slack | 10 min, +1 h | 10 min, +3 h |",
         "|---|---|---|---|---|---|"]
    for name, since in VARIANTS:
        g = w if since is None else w[w["season"] >= since]
        L.append(f"| {name} | {len(g):,} | " + " | ".join(f"{credits(g, st, sl):,}" for st, sl in
                                                          ((5, 60), (5, 180), (10, 60), (10, 180))) + " |")
    by = ["", "By tier, 2023–May 2026, 10 min, +3 h slack:", "", "| Tier | Matches | Credits |", "|---|---|---|"]
    g = w[w["season"] >= 2023]
    for lv, x in g.groupby("level"):
        by.append(f"| {lv} | {len(x):,} | {credits(x, 10, 180):,} |")
    return "\n".join(L + by) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["plan"])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    a = ap.parse_args(argv)
    from . import dk_history as dh
    from . import elo, sackmann
    sack = sackmann.load(a.sackmann, start=1990, lower=True)
    t = dh.tournaments(sack, dh._keys(), hist_start={**dh.HIST_START, "other": pd.Timestamp("2024-01-01")})
    priced = dh.collect(t, elo.add_elo(sack, keys=("winner_id", "loser_id")), 24.0)
    print(plan(windows(priced, sack)))


if __name__ == "__main__":
    main()
