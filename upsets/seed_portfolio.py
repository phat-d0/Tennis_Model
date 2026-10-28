"""Seed losing early: back the unseeded player at DraftKings in rounds 1-2 against a seed. The rule is
pre-registered in reports/upsets_seed_portfolio.md (committed before this code).

    python -m upsets.seed_portfolio [--out reports/upsets_seed_portfolio.md]

Reads cached Odds API snapshots (0 credits) and Jeff Sackmann's results (seeds, entry types, rounds; events
through May 2026). Prints and writes aggregates only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import dk_history as dh
from . import elo, sackmann
from .odds import devig_power

QUAL = {"Q", "LL"}
SEED_BANDS = [(1, 4), (5, 8), (9, 16), (17, 32)]
GATE_SEASONS = (2023, 2024, 2025, 2026)
HAIRCUT = 0.03
SUBRULES = [("a", "All unseeded players"), ("b", "Qualifiers and lucky losers"), ("c", "Other unseeded players")]


def bets(priced: pd.DataFrame, sack: pd.DataFrame) -> pd.DataFrame:
    """One bet per qualifying match: rounds 1-2, exactly one seed, the unseeded player at DraftKings (last snapshot
    >= 5 min before the start), Pinnacle's power de-vig for the fair chance. Void and unpriced matches are left out."""
    need = ["odds_w_draftkings", "odds_l_draftkings", "odds_w_pinnacle", "odds_l_pinnacle"]
    p = priced.dropna(subset=[c for c in need if c in priced]).copy()
    if not set(need) <= set(p.columns) or not len(p):
        return pd.DataFrame()
    s = sack.loc[p["sack_row"].to_numpy()].reset_index(drop=True)
    p = p.reset_index(drop=True)
    ws, ls_ = s["w_seed"].notna().to_numpy(), s["l_seed"].notna().to_numpy()
    keep = (s["round_idx"] <= 2).to_numpy() & ~s["void"].astype(bool).to_numpy() & (ws ^ ls_)
    p, s, ws = p[keep].reset_index(drop=True), s[keep].reset_index(drop=True), ws[keep]
    u_is_w = ~ws                                         # the unseeded player won the match
    pick = lambda w, l: np.where(u_is_w, w, l)            # noqa: E731  unseeded player's value
    other = lambda w, l: np.where(u_is_w, l, w)           # noqa: E731  the seed's value
    odds = pick(p["odds_w_draftkings"], p["odds_l_draftkings"]).astype(float)
    odds_o = other(p["odds_w_draftkings"], p["odds_l_draftkings"]).astype(float)
    pin_u = pick(p["odds_w_pinnacle"], p["odds_l_pinnacle"]).astype(float)
    pin_o = other(p["odds_w_pinnacle"], p["odds_l_pinnacle"]).astype(float)
    b = pd.DataFrame({
        "sack_row": p["sack_row"].to_numpy(), "date": pd.to_datetime(s["date"]).to_numpy(),
        "season": s["season"].to_numpy(), "tour": s["tour"].to_numpy(), "tier": s["level_group"].to_numpy(),
        "entry": pd.Series(pick(s["w_entry"], s["l_entry"])).fillna("").astype(str).str.upper().to_numpy(),
        "seed": pd.to_numeric(pd.Series(other(s["w_seed"], s["l_seed"])), errors="coerce").to_numpy(),
        "odds": odds, "dk_dog": odds > odds_o, "win": u_is_w.astype(int),
        "p_fair": devig_power(pin_u, pin_o)})
    b["qual"] = b["entry"].isin(QUAL)
    b["pnl"] = np.where(b["win"] == 1, b["odds"] - 1, -1.0)
    b["ev"] = b["odds"] * b["p_fair"] - 1        # = CLV vs Pinnacle's close: both use the last snapshot
    b["pnl_cut"] = np.where(b["win"] == 1, np.maximum(b["odds"] * (1 - HAIRCUT), 1.0) - 1, -1.0)
    b["band"] = pd.cut(b["seed"], [0, 4, 8, 16, 32], labels=[f"{a}–{z}" for a, z in SEED_BANDS]).astype(str)
    return b.sort_values("date").reset_index(drop=True)


def subrule(b: pd.DataFrame, rid: str) -> pd.DataFrame:
    return b if rid == "a" else b[b["qual"]] if rid == "b" else b[~b["qual"]]


def ci(x: np.ndarray, n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% bootstrap CI of the mean (one bet per match, so resampling bets = resampling matches)."""
    if len(x) < 2:
        return float("nan"), float("nan")
    rng = np.random.default_rng(seed)
    m = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(1)
    lo, hi = np.percentile(m, [2.5, 97.5])
    return float(lo), float(hi)


def gate(b: pd.DataFrame, seasons=GATE_SEASONS, min_bets: int = 30) -> dict:
    by = b.groupby("season")["pnl"].sum()
    pos = int(sum(by.get(s, 0.0) > 0 for s in seasons))
    ok = len(b) >= min_bets and b["pnl"].sum() > 0 and pos >= 3
    return {"bets": len(b), "pnl": float(b["pnl"].sum()), "seasons_positive": pos, "pass": bool(ok)}


def _p(x) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x:+.1%}"


def row(name: str, b: pd.DataFrame) -> str:
    if not len(b):
        return f"| {name} | 0 | — | — | — | — | — |"
    lo, hi = ci(b["pnl"].to_numpy())
    return (f"| {name} | {len(b):,} | {b['win'].mean():.1%} vs {b['p_fair'].mean():.1%} | {_p(b['pnl'].mean())} "
            f"({_p(lo)} to {_p(hi)}) | {_p(b['ev'].mean())} | {_p(b['pnl_cut'].mean())} | {b['pnl'].sum():+.1f}u |")


HEAD = ["| Slice | Bets | Win rate vs Pinnacle-fair | ROI at DK (95% CI) | Expected ROI = CLV | ROI, odds −3% | P&L |",
        "|---|---|---|---|---|---|---|"]


def report(b: pd.DataFrame) -> str:
    L = ["## Results", "",
         f"Generated by `python -m upsets.seed_portfolio`. {len(b):,} qualifying matches, "
         f"{b['date'].min():%b %Y} – {b['date'].max():%b %Y}. 1 unit per bet. Aggregates only.", ""]
    gs = {rid: gate(subrule(b, rid)) for rid, _ in SUBRULES}
    a, q = subrule(b, "a"), subrule(b, "b")
    fav = a[~a["dk_dog"]]
    passed = [rid for rid, g in gs.items() if g["pass"]]
    L += ["### Verdict", "",
          (f"**{'No sub-rule passes the gate.' if not passed else 'Sub-rule(s) ' + ', '.join(passed) + ' pass the gate.'}** "
           f"Backing the unseeded player against a seed returned {_p(a['pnl'].mean())} a bet at DraftKings over "
           f"{len(a):,} matches, against {_p(a['ev'].mean())} expected at Pinnacle's fair price."),
          "",
          f"- Qualifiers and lucky losers: {_p(q['pnl'].mean())} over {len(q):,} bets "
          f"({gs['b']['seasons_positive']} of 4 recent seasons positive, total {gs['b']['pnl']:+.1f}u).",
          f"- Unseeded players DraftKings makes the favourite: {_p(fav['pnl'].mean())} over {len(fav):,} bets.",
          "- As pre-registered, three sub-rules on one dataset means any single bright spot in a split below is "
          "weak evidence.", "",
          "### Gate (per pre-registered sub-rule)", "",
         "| Sub-rule | Bets | P&L | Seasons positive (of 2023–2026) | Gate |", "|---|---|---|---|---|"]
    for rid, name in SUBRULES:
        g = gs[rid]
        L.append(f"| ({rid}) {name} | {g['bets']:,} | {g['pnl']:+.1f}u | {g['seasons_positive']} | "
                 f"{'PASS' if g['pass'] else 'FAIL'} |")
    L += ["", "### Sub-rules", ""] + HEAD + [row(f"({rid}) {name}", subrule(b, rid)) for rid, name in SUBRULES]
    splits = [("Seed band of the opponent", "band", [f"{a}–{z}" for a, z in SEED_BANDS]),
              ("DraftKings' view of the unseeded player", "dk_dog", [True, False]),
              ("Tour", "tour", ["atp", "wta"]), ("Tier", "tier", ["slam", "1000", "other"]),
              ("Season", "season", sorted(b["season"].unique()))]
    names = {True: "DK underdog", False: "DK favourite"}
    for title, col, keys in splits:
        L += ["", f"### {title}", ""] + HEAD
        for k in keys:
            L.append(row(str(names.get(k, k)) if col == "dk_dog" else str(k), b[b[col] == k]))
        if col in ("band", "dk_dog"):
            L += ["", f"Qualifiers only, by {title[0].lower() + title[1:]}:", ""] + HEAD
            for k in keys:
                q = b[b["qual"]]
                L.append(row(str(names.get(k, k)) if col == "dk_dog" else str(k), q[q[col] == k]))
    return "\n".join(L) + "\n"


def run(root: Path, cache: Path, other_from: str = "2024-01-01") -> tuple[str, pd.DataFrame]:
    sack = sackmann.load(root, start=1990, lower=True)
    sack_elo = elo.add_elo(sack, keys=("winner_id", "loser_id"))
    hs = {**dh.HIST_START, "other": pd.Timestamp(other_from)}
    t = dh.tournaments(sack, dh._keys(), hist_start=hs)
    priced = dh.collect(t, sack_elo, 24.0, root=cache)
    b = bets(priced, sack)
    return report(b), b


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    ap.add_argument("--cache", type=Path, default=dh.CACHE)
    ap.add_argument("--out", type=Path, default=None, help="append the results to this pre-registration file")
    a = ap.parse_args(argv)
    text, _ = run(a.sackmann, a.cache)
    print(text)
    if a.out:
        body = a.out.read_text().split("## Results")[0].rstrip()
        a.out.write_text(body + "\n\n" + text)


if __name__ == "__main__":
    main()
