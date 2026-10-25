"""Seeded-player base rates in early rounds, from results only (Sackmann data, no odds).

    python -m upsets.seeds --root /home/user/phat-d0/tennis-sackmann-archive \
        [--from 2010 --to 2025] [--out reports/upsets_seed_base_rates.md]

Two views, ATP and WTA apart, tour-level knockout events (Slams, 1000s, others; no team
events, Finals or round-robin events):
- Match view: rounds 1-2 matches between a seeded and an unseeded player, not voided (walkover,
  or retirement before set 1 is complete). How often does the seed lose, by seed band, level and
  surface, and what did pre-match Elo say?
- Player view: share of seeds whose tournament ends in rounds 1-2 (their first match can be in
  round 2 when the top seeds get byes). Void losses are left out.

Elo is computed from 1990 (ratings strictly pre-match). By default it also uses the qualifying,
Challenger and ITF files: on tour-level files alone it underrates qualifiers and is
over-confident (fitted slope on its logit ~0.72 vs ~0.90 with them).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import elo, sackmann

BANDS = [(1, 4, "1-4"), (5, 8, "5-8"), (9, 16, "9-16"), (17, 32, "17-32")]
LEVELS = ("slam", "1000", "other")
P_BINS = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 1.0)


def band(seed: pd.Series) -> pd.Series:
    """Seed -> ordered band label ("1-4" ... "17-32"); NaN outside 1-32."""
    edges = [BANDS[0][0] - 0.5] + [hi + 0.5 for _, hi, _ in BANDS]
    return pd.cut(seed, edges, labels=[name for *_, name in BANDS])


def knockout(df: pd.DataFrame) -> pd.Series:
    """Rows from tour-level knockout events (no team ties, Finals, or events with round robin)."""
    has_rr = df["round"].eq("RR").groupby(df["tourney_id"]).transform("any")
    return df["level_group"].isin(LEVELS) & ~has_rr


def seed_matches(df: pd.DataFrame, early_rounds: int = 2) -> pd.DataFrame:
    """Early-round seed-vs-unseeded matches (needs elo columns), oriented to the seed."""
    m = df[knockout(df) & (df["round_idx"] <= early_rounds) & ~df["void"]]
    w_seeded, l_seeded = m["w_seed"].notna(), m["l_seed"].notna()
    m = m[w_seeded ^ l_seeded]
    seed_won = m["w_seed"].notna()
    pick = lambda w, l: m[w].where(seed_won, m[l])  # noqa: E731
    opp = lambda w, l: m[l].where(seed_won, m[w])  # noqa: E731
    out = pd.DataFrame({
        "season": m["season"], "tour": m["tour"], "level_group": m["level_group"],
        "surface": m["surface"], "round_idx": m["round_idx"],
        "seed": pick("w_seed", "l_seed"), "seed_rank": pick("w_rank", "l_rank"),
        "opp_rank": opp("w_rank", "l_rank"), "opp_entry": opp("w_entry", "l_entry"),
        "seed_lost": (~seed_won).astype(int),
        "elo_diff": pick("w_elo", "l_elo") - opp("w_elo", "l_elo"),
        "min_n": np.minimum(m["w_n"], m["l_n"]),
    })
    out["band"] = band(out["seed"])
    out["p_elo_lose"] = 1.0 / (1.0 + 10 ** (out["elo_diff"] / 400.0))
    return out.dropna(subset=["band"]).reset_index(drop=True)


def seed_exits(df: pd.DataFrame, early_rounds: int = 2) -> pd.DataFrame:
    """One row per seeded player per tournament: did their tournament end in rounds 1-2?
    Tournaments ended by a void loss (walkover, early retirement) are left out."""
    k = df[knockout(df)]
    rows = []
    for side, other in (("w", "l"), ("l", "w")):
        s = k[k[f"{side}_seed"].notna()]
        rows.append(pd.DataFrame({
            "tourney_id": s["tourney_id"], "player": s["winner_id" if side == "w" else "loser_id"],
            "season": s["season"], "tour": s["tour"], "level_group": s["level_group"],
            "surface": s["surface"], "seed": s[f"{side}_seed"], "round_idx": s["round_idx"],
            "lost": side == "l", "void": s["void"],
        }))
    long = pd.concat(rows, ignore_index=True)
    g = long.groupby(["tourney_id", "player"], sort=False)
    out = g.agg(season=("season", "first"), tour=("tour", "first"),
                level_group=("level_group", "first"), surface=("surface", "first"),
                seed=("seed", "first")).reset_index()
    loss = long[long["lost"]].drop_duplicates(["tourney_id", "player"]).set_index(["tourney_id", "player"])
    key = pd.MultiIndex.from_frame(out[["tourney_id", "player"]])
    out["exit_round"] = loss["round_idx"].reindex(key).to_numpy()
    out["exit_void"] = loss["void"].reindex(key).fillna(False).astype(bool).to_numpy()
    out = out[~out["exit_void"]]
    out["out_early"] = (out["exit_round"] <= early_rounds).astype(int)
    out["band"] = band(out["seed"])
    return out.dropna(subset=["band"]).reset_index(drop=True)


def rate_table(m: pd.DataFrame, by: list[str], y: str = "seed_lost", p: str | None = "p_elo_lose"):
    g = m.groupby(by, observed=True)
    t = g[y].agg(n="size", rate="mean")
    t["se"] = np.sqrt(t["rate"] * (1 - t["rate"]) / t["n"])
    if p:
        t["elo"] = g[p].mean()
        t["gap"] = t["rate"] - t["elo"]
    return t


def calibration(m: pd.DataFrame) -> pd.DataFrame:
    """Elo's p(seed loses) by bin vs the actual loss rate, per tour."""
    b = pd.cut(m["p_elo_lose"], P_BINS, include_lowest=True)
    t = m.groupby(["tour", b], observed=True).agg(n=("seed_lost", "size"),
                                                  elo=("p_elo_lose", "mean"),
                                                  actual=("seed_lost", "mean"))
    t["se"] = np.sqrt(t["actual"] * (1 - t["actual"]) / t["n"])
    return t


def scores(m: pd.DataFrame) -> pd.DataFrame:
    p = m["p_elo_lose"].clip(1e-6, 1 - 1e-6)
    y = m["seed_lost"]
    ll = -(y * np.log(p) + (1 - y) * np.log(1 - p))
    base = m.groupby("tour")["seed_lost"].transform("mean")
    ll0 = -(y * np.log(base) + (1 - y) * np.log(1 - base))
    return pd.DataFrame({"tour": m["tour"], "ll": ll, "ll_base": ll0,
                         "brier": (p - y) ** 2}).groupby("tour").mean()


def _pct(x) -> str:
    return "" if pd.isna(x) else f"{100 * x:.1f}%"


def _md(t: pd.DataFrame, pct_cols=("rate", "se", "elo", "gap", "actual")) -> str:
    t = t.reset_index()
    cols = list(t.columns)
    lines = ["| " + " | ".join(map(str, cols)) + " |", "|" + "---|" * len(cols)]
    for _, r in t.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if c in pct_cols:
                cells.append(_pct(v) if c != "gap" or pd.isna(v) else f"{100 * v:+.1f} pp")
            elif c == "n":
                cells.append(f"{int(v):,}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def report(df: pd.DataFrame, first: int, last: int, elo_note: str = "") -> str:
    m = seed_matches(df)
    m = m[(m["season"] >= first) & (m["season"] <= last)]
    x = seed_exits(df)
    x = x[(x["season"] >= first) & (x["season"] <= last)]
    sc = scores(m)
    out = [
        f"# Seeded players in early rounds: base rates ({first}–{last})",
        "",
        "Results only (no odds). Data: Jeff Sackmann's tennis_atp / tennis_wta match files "
        "(CC BY-NC-SA 4.0), via the archival fork phat-d0/tennis-sackmann-archive. "
        "Generated by `python -m upsets.seeds`.",
        "",
        "Scope: tour-level knockout events (Slams, 1000s, other tour events; no team events, "
        "Finals or round-robin events), rounds 1–2 of the main draw. Void = walkover, or a "
        "retirement/default before set 1 is complete (left out). `elo` = mean pre-match Elo "
        f"probability that the seed loses (overall Elo from 1990 on {elo_note or 'the loaded matches'}, "
        "ATP and WTA apart); "
        "`gap` = actual − Elo. `se` = binomial standard error of the rate.",
        "",
        "## Match view: seed vs unseeded, rounds 1–2",
        "",
        "### By tour and seed band",
        _md(rate_table(m, ["tour", "band"])),
        "",
        "### By tour, level and seed band",
        _md(rate_table(m, ["tour", "level_group", "band"])),
        "",
        "### By tour and surface (all bands)",
        _md(rate_table(m, ["tour", "surface"])),
        "",
        "### By tour and season (all bands)",
        _md(rate_table(m, ["tour", "season"])),
        "",
        "### Elo calibration (p = Elo probability the seed loses)",
        _md(calibration(m), pct_cols=("elo", "actual", "se")),
        "",
        "Log loss (Elo vs the tour's constant base rate) and Brier score:",
        "",
        "| tour | n | log loss Elo | log loss base rate | Brier Elo |",
        "|---|---|---|---|---|",
        *[f"| {t} | {int((m['tour'] == t).sum()):,} | {r.ll:.4f} | {r.ll_base:.4f} | {r.brier:.4f} |"
          for t, r in sc.iterrows()],
        "",
        "## Player view: share of seeds out by round 2",
        "",
        "Each seeded player's tournament counts once; the top seeds' first match is often in "
        "round 2 (bye). Exits by walkover or early retirement are left out.",
        "",
        _md(rate_table(x, ["tour", "band"], y="out_early", p=None)),
        "",
        _md(rate_table(x, ["tour", "level_group"], y="out_early", p=None)),
    ]
    return "\n".join(out) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True, help="tennis-sackmann-archive checkout")
    ap.add_argument("--from", dest="first", type=int, default=2010)
    ap.add_argument("--to", dest="last", type=int, default=2025)
    ap.add_argument("--elo-start", type=int, default=1990)
    ap.add_argument("--tour-only-elo", action="store_true",
                    help="Elo from tour-level files only (default also uses qualifying/Challenger/ITF)")
    ap.add_argument("--out", default="reports/upsets_seed_base_rates.md")
    a = ap.parse_args(argv)
    df = sackmann.load(a.root, start=a.elo_start, lower=not a.tour_only_elo)
    df = elo.add_elo(df, keys=("winner_id", "loser_id"))
    text = report(df, a.first, a.last, elo_note="tour-level only" if a.tour_only_elo
                  else "tour-level + qualifying/Challenger (ATP) / qualifying/ITF (WTA)")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
