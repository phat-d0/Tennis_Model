"""Backtest aggregates for the page's Portfolio tab: site/portfolio_backtest.json.

    python -m upsets.portfolio_backtest [--out site/portfolio_backtest.json]

The live paper rules (upsets.portfolio.STRATEGIES) applied to the cached DK history: DraftKings and
Pinnacle at the last snapshot >= 5 min before the listed start, rounds 1-2 of Slams (2020-), 1000s
and 250/500s (2024-), results from Jeff Sackmann's files only (events through May 2026; the public
page never uses Kalshi data). Writes aggregates only: no odds, no per-match rows.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import dk_history as dh
from . import dk_study as ds
from . import elo, sackmann
from .portfolio import MAX_BOOK_GAP, STRATEGIES


def bets(f: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Per strategy: one row per bet with odds, fair p (Pinnacle, proportional), win, date."""
    f = f[~f["void"].astype(bool)].dropna(subset=["odds_dog_pin", "odds_fav_pin"]).copy()
    i_d, i_f = 1 / f["odds_dog_pin"], 1 / f["odds_fav_pin"]
    f["pf_dog"] = i_d / (i_d + i_f)
    k_d, k_f = 1 / f["odds_dog_dk"], 1 / f["odds_fav_dk"]
    f = f[(k_d / (k_d + k_f) - f["pf_dog"]).abs() <= MAX_BOOK_GAP]       # the live rule's quote-error filter
    sides = []
    for side in ("dog", "fav"):
        sides.append(pd.DataFrame({
            "m": f.index, "date": f["date"], "side": side, "odds": f[f"odds_{side}_dk"],
            "p_fair": f["pf_dog"] if side == "dog" else 1 - f["pf_dog"],
            "p_model": f["p_model"] if side == "dog" else 1 - f["p_model"],
            "win": f["upset"] if side == "dog" else 1 - f["upset"]}))
    long = pd.concat(sides, ignore_index=True)
    long["ev"] = long["odds"] * long["p_fair"] - 1
    long["model_edge"] = long["odds"] * long["p_model"] - 1
    out = {}
    for s in STRATEGIES:
        if s["id"] == "dogs":
            b = long[long["side"] == "dog"]
        else:
            col = "model_edge" if s["id"] == "model" else "ev"
            b = long.dropna(subset=[col]).sort_values(col, ascending=False).drop_duplicates("m")
            b = b[b[col] >= s["min_edge"]]
        b = b.assign(pnl=np.where(b["win"] == 1, b["odds"] - 1, -1.0))
        out[s["id"]] = b.sort_values("date")
    return out


def aggregate(b: pd.DataFrame, rule: str, n_boot: int = 2000) -> dict:
    if not len(b):
        return {"rule": rule, "bets": 0}
    x = b["pnl"].to_numpy()
    rng = np.random.default_rng(0)
    boots = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    wk = b.assign(week=b["date"].dt.to_period("W").dt.start_time).groupby("week").agg(
        realized=("pnl", "sum"), expected=("ev", "sum"), n=("pnl", "size"))
    wk[["realized", "expected"]] = wk[["realized", "expected"]].cumsum()
    curve = [{"date": d.strftime("%Y-%m-%d"), "n": int(r.n), "realized": round(float(r.realized), 2),
              "expected": round(float(r.expected), 2)} for d, r in wk.iterrows()]
    return {
        "rule": rule, "bets": int(len(b)),
        "period": f"{b['date'].min():%b %Y} – {b['date'].max():%b %Y}",
        "roi": float(x.mean()), "roi_ci": [float(lo), float(hi)],
        "expected_roi": float(b["ev"].mean()),
        "luck_units": round(float(x.sum() - b["ev"].sum()), 2),
        "win_rate": float(b["win"].mean()), "expected_win_rate": float(b["p_fair"].mean()),
        "curve": curve,
    }


def build(root: Path, cache: Path, other_from: str = "2024-01-01") -> dict:
    sack = sackmann.load(root, start=1990, lower=True)
    sack_elo = elo.add_elo(sack, keys=("winner_id", "loser_id"))
    hs = {**dh.HIST_START, "other": pd.Timestamp(other_from)}
    t = dh.tournaments(sack, dh._keys(), hist_start=hs)
    priced = dh.collect(t, sack_elo, 24.0, root=cache)
    f = ds.frame(priced, sack_elo)
    f["date"] = pd.to_datetime(priced.set_index("sack_row").loc[f["sack_row"], "commence"].to_numpy())
    by = bets(f)
    return {
        "note": ("Backtest of the same rules on past seasons: DraftKings and Pinnacle at the last snapshot "
                 "at least 5 minutes before the start (one price per match, so not the live rule's first "
                 "qualifying moment), rounds 1–2 of Slams from 2020 and 1000s and 250/500s from 2024, "
                 "results from Jeff Sackmann's files (events through May 2026). Matches where DraftKings' and "
                 "Pinnacle's fair chances differ by more than 10 points are skipped as quote errors, as live. "
                 "In-sample: no rule here has passed the project's walk-forward test. 1 unit = one $10 bet. "
                 "Expected = each bet's value at Pinnacle's fair price."),
        "strategies": {s["id"]: aggregate(by[s["id"]], s["rule"]) for s in STRATEGIES},
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    ap.add_argument("--cache", type=Path, default=dh.CACHE)
    ap.add_argument("--out", type=Path, default=Path("site/portfolio_backtest.json"))
    a = ap.parse_args(argv)
    doc = build(a.sackmann, a.cache)
    a.out.write_text(json.dumps(doc, indent=1))
    for k, v in doc["strategies"].items():
        print(k, v.get("bets"), f"roi {v.get('roi', float('nan')):+.1%}", f"expected {v.get('expected_roi', float('nan')):+.1%}")


if __name__ == "__main__":
    main()
