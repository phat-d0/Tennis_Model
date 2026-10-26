"""The "penultimate set" theory, from results only (Jeff Sackmann's match files, CC BY-NC-SA 4.0).

    python -m upsets.penultimate --root PATH [--from 1991] [--out reports/upsets_penultimate.md]

Owner's questions: (1) does the winner of the penultimate set win the match more often than
not? (3) does it change when that player was the pre-match underdog? (Question 2, "more often
than the odds imply", needs in-match prices: upsets.decider on Kalshi.)

Completed tour-level matches only (no RET / W/O / DEF / unfinished / abandoned, no malformed
scores; a match tiebreak "[10-7]" counts as a set). Straight-sets matches make (1) trivially
high, so the real test is matches that reach a deciding set: there the penultimate-set winner
is always the player who just levelled. If sets were independent, the player who won the
penultimate set and the one who won an earlier set would each win the decider half the time,
whatever their strength, so the gap from 50% is a model-free momentum test. Splits by pre-match
favourite (better Elo, from 1990 on tour + qualifying/Challenger/ITF files, or better ranking) use
"expected" = the per-set win probability implied by pre-match Elo (a decider is one set; the
pre-match *match* probability overstates a favourite's edge in a single set). The cleanest split
is symmetric: P(favourite wins decider | favourite levelled) − P(favourite wins | underdog
levelled) = 2 × momentum, with strength held equal on both sides.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

from . import elo, sackmann

SET_RE = re.compile(r"^\[?(\d+)-(\d+)(?:\(\d+\))?\]?$")
# Kalshi price test (upsets.decider, run by Data on kalshi_g0, 2026-10-26; aggregates only).
KALSHI_SECTION = """## (2) Against the price: Kalshi, buying the levelling player at the decider start

**It happens (≈ 55%), but it's priced in, so no edge after fees.** Data ran `upsets.decider` on Kalshi
ATP/WTA match markets (Apr–Oct 2026, 1-min candles): buy the player who won the penultimate set at
the ask + Kalshi taker fee, 100 contracts, as of the decider start + 90 s. Decider guard: the
decider must start 15–180 min before the match close and not share its start with another match
(batch closes). It removed 14 impossible starts and 24 over 180 min.

| Slice | Bets | Levelling player won | Avg ask | Break-even (incl. fee) | ROI 0¢ | 95% CI | ROI 1¢ |
|---|---|---|---|---|---|---|---|
| All, after the guard | 1,385 | | | | −0.9% | −5.0% to +3.2% | −2.7% |
| All, before the guard | 1,423 | 54.8% | 53.8% | 55.2% | −0.7% | −5.0% to +3.7% | −2.4% |
| … buying the other player instead (before the guard) | | | | | −7.3% | | |

Before the guard (Data's first run), by tour: ATP +1.9%, WTA −3.1%; best of 5: 38 bets, +19%
(CI −6% to +44%, noise). By who levelled: pre-match favourite 688 bets, won 65.8% vs a 64.1% ask,
+0.5%; pre-match underdog 726 bets, won 44.4% vs a 44.0% ask, −2.4%. Flat across timing offsets
(0 / 60 / 90 / 180 s); monthly results mixed. The market's price for the levelling player already
sits within ~1–2 pp of how often they win; the fee and the spread take the rest.
"""
ERAS = [(1991, 2000), (2001, 2010), (2011, 2020), (2021, 2026)]


def parse_sets(score) -> list[int] | None:
    """Score (winner first) -> per-set winner: 1 = match winner, 0 = loser. None if malformed."""
    if not isinstance(score, str) or not score.strip():
        return None
    out = []
    for tok in score.split():
        m = SET_RE.match(tok)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2))
        if a == b:
            return None
        out.append(1 if a > b else 0)
    return out


def set_prob(p_match, best_of, iters: int = 60) -> np.ndarray:
    """Per-set win probability s implying match probability p_match, with sets i.i.d.:
    bo3 M = s^2 (3 - 2s); bo5 M = s^3 (10 - 15s + 6s^2). A decider is one set, so s is a
    player's strength-only chance of winning it."""
    p = np.asarray(p_match, float)
    bo5 = np.asarray(best_of) == 5
    lo, hi = np.zeros_like(p), np.ones_like(p)
    for _ in range(iters):
        x = (lo + hi) / 2
        m = np.where(bo5, x ** 3 * (10 - 15 * x + 6 * x ** 2), x ** 2 * (3 - 2 * x))
        lo, hi = np.where(m < p, x, lo), np.where(m < p, hi, x)
    return (lo + hi) / 2


def penultimate_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Completed tour-level matches with sets parsed and the penultimate-set winner oriented.
    Needs elo columns. One row per match: pen_won_match, decider, pen_is_fav_elo, pen_is_fav_rank,
    p_pen (pre-match Elo win probability of the penultimate-set winner), fav_won (Elo fav)."""
    d = df[(df["comment"] == "Completed") & (df["level_group"] != "lower")]
    sets = d["score"].map(parse_sets)
    ok = sets.notna()
    d, sets = d[ok], sets[ok]
    n = sets.map(len)
    won = sets.map(sum)
    need = (d["best_of"] + 1) // 2
    valid = (n >= 2) & (won == need) & (n - won < need) & sets.map(lambda s: len(s) > 0 and s[-1] == 1)
    d, sets, n = d[valid], sets[valid], n[valid]
    pen_by_w = sets.map(lambda s: s[-2] == 1).astype(bool)  # match winner won the penultimate set
    p_w = 1.0 / (1.0 + 10 ** ((d["l_elo"] - d["w_elo"]) / 400.0))
    w_rank, l_rank = d["w_rank"].fillna(9999), d["l_rank"].fillna(9999)
    out = pd.DataFrame({
        "season": d["season"], "tour": d["tour"], "best_of": d["best_of"].astype(int),
        "level_group": d["level_group"], "n_sets": n,
        "decider": n == d["best_of"],
        "pen_won_match": pen_by_w.astype(int),
        "p_pen": np.where(pen_by_w, p_w, 1 - p_w),
        "w_elo_better": d["w_elo"] > d["l_elo"], "w_rank_better": w_rank < l_rank,
        "rank_tie": w_rank == l_rank, "elo_tie": d["w_elo"] == d["l_elo"],
        "min_n": np.minimum(d["w_n"], d["l_n"]),
    }, index=d.index)
    out["p_set_pen"] = set_prob(out["p_pen"], out["best_of"])
    out["path_w"] = sets.map(lambda x: "".join("W" if v else "L" for v in x))  # match winner's view
    out["pen_is_fav_elo"] = np.where(out["elo_tie"], np.nan, (pen_by_w == out["w_elo_better"]).astype(float))
    out["pen_is_fav_rank"] = np.where(out["rank_tie"], np.nan, (pen_by_w == out["w_rank_better"]).astype(float))
    out["fav_won_elo"] = np.where(out["elo_tie"], np.nan, out["w_elo_better"].astype(float))
    out["fav_won_rank"] = np.where(out["rank_tie"], np.nan, out["w_rank_better"].astype(float))
    era = pd.Series(pd.NA, index=out.index, dtype="string")
    for a, b in ERAS:
        era[(out["season"] >= a) & (out["season"] <= b)] = f"{a}–{b}"
    out["era"] = era
    out["fmt"] = out["tour"].str.upper() + " bo" + out["best_of"].astype(str)
    return out


def rate(g: pd.DataFrame, y: str = "pen_won_match", p: str | None = "p_pen") -> dict:
    v = g[y].dropna()
    n = len(v)
    r = v.mean() if n else np.nan
    out = {"n": n, "rate": r, "se": np.sqrt(r * (1 - r) / n) if n else np.nan}
    if p:
        out["expected"] = g.loc[v.index, p].mean() if n else np.nan
        out["gap"] = out["rate"] - out["expected"]
        # SE of the gap: residual variance around the per-match expectation
        resid = v - g.loc[v.index, p]
        out["gap_se"] = resid.std(ddof=1) / np.sqrt(n) if n > 1 else np.nan
    return out


def table(f: pd.DataFrame, by: list[str], **kw) -> pd.DataFrame:
    rows = [{**dict(zip(by, k if isinstance(k, tuple) else (k,))), **rate(g, **kw)}
            for k, g in f.groupby(by, observed=True, sort=True)]
    return pd.DataFrame(rows)


def symmetric(dec: pd.DataFrame, fav_col: str = "pen_is_fav_elo") -> pd.DataFrame:
    """Per format: A = P(fav wins decider | fav levelled), B = P(fav wins | dog levelled),
    momentum = (A - B) / 2 with its standard error."""
    rows = []
    for fmt, g in dec.groupby("fmt"):
        g = g[g[fav_col].notna()]
        fl, dl = g[g[fav_col] == 1], g[g[fav_col] == 0]
        a, b = fl["pen_won_match"].mean(), 1 - dl["pen_won_match"].mean()
        se = np.sqrt(a * (1 - a) / len(fl) + b * (1 - b) / len(dl)) / 2
        rows.append({"fmt": fmt, "n": len(g), "fav wins (fav levelled)": a,
                     "fav wins (dog levelled)": b, "momentum": (a - b) / 2, "momentum_se": se})
    return pd.DataFrame(rows)


def _md(t: pd.DataFrame) -> str:
    cols = list(t.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in t.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            if c == "n":
                cells.append(f"{int(v):,}")
            elif c in ("rate", "se", "expected") or c.startswith("fav wins"):
                cells.append("—" if pd.isna(v) else f"{100 * v:.1f}%")
            elif c in ("gap", "gap_se", "momentum", "momentum_se"):
                cells.append("—" if pd.isna(v) else f"{100 * v:+.1f} pp" if c in ("gap", "momentum")
                             else f"{100 * v:.1f} pp")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def fav_paths(f: pd.DataFrame, by: str = "rank") -> pd.DataFrame:
    """Matches oriented to the pre-match favourite (better ranking or Elo): path (fav's view),
    fav_won, won_set1."""
    win_fav = f[f"w_{by}_better"] & ~f[f"{by}_tie"]
    keep = ~f[f"{by}_tie"]
    g = f[keep]
    flip = lambda s: s.translate(str.maketrans("WL", "LW"))  # noqa: E731
    path = np.where(win_fav[keep], g["path_w"], g["path_w"].map(flip))
    return pd.DataFrame({"fmt": g["fmt"], "season": g["season"], "path": path,
                         "fav_won": win_fav[keep].astype(int).to_numpy(),
                         "won_set1": pd.Series(path, index=g.index).str[0].eq("W").astype(int)}, index=g.index)


def fav_section(f: pd.DataFrame, since: int | None = None, paths: bool = True) -> list[str]:
    lines = []
    for by, label in (("rank", "ranking"), ("elo", "Elo")):
        fp = fav_paths(f, by)
        if since:
            fp = fp[fp["season"] >= since]
        rows = []
        for fmt, g in fp.groupby("fmt"):
            w1, l1 = g[g["won_set1"] == 1], g[g["won_set1"] == 0]
            rows.append({"fmt": fmt, "favourite by": label, "n": len(g), "fav won": g["fav_won"].mean(),
                         "won set 1": len(w1) / len(g), "→ fav won": w1["fav_won"].mean(),
                         "lost set 1 → fav won": l1["fav_won"].mean()})
        lines += [_md_plain(pd.DataFrame(rows)), ""]
    if not paths:
        return lines
    fp = fav_paths(f, "rank")
    if since:
        fp = fp[fp["season"] >= since]
    rows = []
    for fmt, g in fp.groupby("fmt"):
        for path, h in g.groupby("path"):
            if len(h) / len(g) >= 0.005:
                rows.append({"fmt": fmt, "path (favourite by ranking)": path, "n": len(h), "share": len(h) / len(g)})
    lines += [_md_plain(pd.DataFrame(rows).sort_values(["fmt", "share"], ascending=[True, False])), "",
              "Score state while the match is still going (favourite's view, by ranking) → how often the "
              "favourite still wins:", ""]
    rows = []
    for fmt, g in fp.groupby("fmt"):
        longest = g["path"].str.len().max()
        for k in range(1, longest):
            live = g[g["path"].str.len() > k]
            for pre, h in live.groupby(live["path"].str[:k]):
                rows.append({"fmt": fmt, "sets so far": pre, "n": len(h), "fav won": h["fav_won"].mean()})
    lines += [_md_plain(pd.DataFrame(rows)), ""]
    return lines


def _md_plain(t: pd.DataFrame) -> str:
    cols = list(t.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in t.iterrows():
        lines.append("| " + " | ".join(
            f"{int(r[c]):,}" if c == "n" else (f"{100 * r[c]:.1f}%" if isinstance(r[c], float) else str(r[c]))
            for c in cols) + " |")
    return "\n".join(lines)


def fav_answer(f: pd.DataFrame) -> list[str]:
    fp = fav_paths(f, "rank")

    def p(fmt, pre):
        g = fp[(fp["fmt"] == fmt) & (fp["path"].str.len() > len(pre)) & fp["path"].str.startswith(pre)]
        return f"{100 * g['fav_won'].mean():.1f}%"

    def won(fmt):
        return f"{100 * fp.loc[fp['fmt'] == fmt, 'fav_won'].mean():.1f}%"

    return [
        f"4b. **Does the original favourite make it out?** The pre-match favourite (by ranking) wins "
        f"ATP bo3 {won('ATP bo3')} / ATP bo5 {won('ATP bo5')} / WTA bo3 {won('WTA bo3')}. After losing set 1: "
        f"{p('ATP bo3', 'L')} / {p('ATP bo5', 'L')} / {p('WTA bo3', 'L')}. At one set all, the favourite who "
        f"just levelled wins {p('ATP bo3', 'LW')} (ATP) / {p('WTA bo3', 'LW')} (WTA), the one who was just "
        f"levelled {p('ATP bo3', 'WL')} / {p('WTA bo3', 'WL')}. Best of 5 at 2–2: back from 0–2 "
        f"{p('ATP bo5', 'LLWW')}, after leading 2–0 {p('ATP bo5', 'WWLL')}.",
    ]


def answer(f: pd.DataFrame, dec: pd.DataFrame) -> list[str]:
    allm, d, sym = table(f, ["fmt"]), table(dec, ["fmt"], p="p_set_pen"), symmetric(dec)
    fav = dec[dec["pen_is_fav_elo"].notna()]
    roles = table(fav.assign(role=np.where(fav["pen_is_fav_elo"] == 1, "fav", "dog")), ["fmt", "role"],
                  p="p_set_pen").set_index(["fmt", "role"])
    fmt_list = lambda t, c, sign=False: " / ".join(  # noqa: E731
        f"{r['fmt']} {100 * r[c]:{'+' if sign else ''}.1f}{' pp' if sign else '%'}" for _, r in t.iterrows())
    return [
        "## Answer",
        f"1. **Yes, but mostly because of straight sets.** Over all completed matches the "
        f"penultimate-set winner wins {fmt_list(allm, 'rate')}. In matches that go the distance (the only "
        f"place the question has bite) the player who levelled wins the decider "
        f"{fmt_list(d, 'rate')}: a small but real edge over the 50% that independent sets would give "
        f"(SE ≈ 0.3–0.7 pp).",
        f"2. **Strength held equal, the momentum is {fmt_list(sym, 'momentum', True)}** (symmetric test: "
        "the same favourite wins the decider more often when they were the one who levelled). It is "
        "steady across eras and levels.",
        "3. **Favourite or underdog, the effect is about the same size.** A favourite who levelled wins "
        + " / ".join(f"{r.Index} {100 * roles.loc[(r.Index, 'fav'), 'rate']:.1f}%" for r in sym.set_index("fmt").itertuples())
        + "; an underdog who levelled wins "
        + " / ".join(f"{r.Index} {100 * roles.loc[(r.Index, 'dog'), 'rate']:.1f}%" for r in sym.set_index("fmt").itertuples())
        + ". So a levelling underdog is still the underdog in the decider: they win less than half the time.",
        "4. **(2) More often than the odds imply? No.** On Kalshi the levelling player wins ≈ 55% but is "
        "priced at ≈ 54% before the fee: buying them at the decider start returns −0.9% (CI −5.0% to "
        "+3.2%, 1,385 bets) and −2.7% at 1¢ slippage. The market already prices the momentum (section below).",
        *fav_answer(f),
        "5. **Caveats.** Retirements are excluded (~3% of matches; a player fading physically may retire "
        "in the decider, so momentum could be a little larger). The data can't tell psychology from "
        "in-match information (fitness, an injury, tactics, conditions): it only shows the latest set "
        "predicts the decider better than an earlier one.",
    ]


def report(f: pd.DataFrame, first: int, last: int) -> str:
    dec = f[f["decider"]]
    fav = dec.assign(role=np.where(dec["pen_is_fav_elo"] == 1, "favourite levelled",
                                   np.where(dec["pen_is_fav_elo"] == 0, "underdog levelled", None)))
    fav = fav[fav["role"].notna()]
    favr = dec.assign(role=np.where(dec["pen_is_fav_rank"] == 1, "favourite levelled",
                                    np.where(dec["pen_is_fav_rank"] == 0, "underdog levelled", None)))
    favr = favr[favr["role"].notna()]
    base = pd.concat([table(dec, ["fmt"], y="fav_won_elo", p=None).assign(by="Elo"),
                      table(dec, ["fmt"], y="fav_won_rank", p=None).assign(by="ranking")])
    lines = [
        f"# The penultimate-set theory (results {first}–{last}; Kalshi price test 2026)", "",
        *answer(f, dec), "", KALSHI_SECTION,
        "Data: Jeff Sackmann's tennis_atp / tennis_wta match files (CC BY-NC-SA 4.0), archival fork "
        "phat-d0/tennis-sackmann-archive. Generated by `python -m upsets.penultimate`.", "",
        "Completed tour-level matches (no retirements, walkovers, defaults or unfinished matches). "
        "`rate` = how often the penultimate-set winner won the match; `expected` = their strength-only "
        "chance (all matches: pre-match Elo match probability; deciders: the per-set probability it "
        "implies); `gap` = rate − expected (± `gap_se`). Favourite = better pre-match Elo unless the "
        "table says ranking.", "",
        "## (1) All matches", "", "Inflated by straight sets, where the penultimate-set winner always wins.", "",
        _md(table(f, ["fmt"])), "",
        "## Matches that reach a deciding set", "",
        "The penultimate-set winner is the player who just levelled the match. With independent sets "
        "they'd win the decider 50% of the time.", "",
        _md(table(dec, ["fmt"], p="p_set_pen")), "",
        "### Momentum with strength held equal (symmetric test)", "",
        _md(symmetric(dec)), "", "By ranking instead of Elo:", "", _md(symmetric(dec, "pen_is_fav_rank")), "",
        "### (3) Split by pre-match favourite / underdog (Elo)", "",
        "`expected` comes from pre-match Elo, which is a little over-confident (Phase A: logit slope ~0.9), "
        "so it flatters favourites slightly; the symmetric test above doesn't depend on it.", "",
        _md(table(fav, ["fmt", "role"], p="p_set_pen")), "",
        "Same split by ranking:", "", _md(table(favr, ["fmt", "role"], p="p_set_pen")), "",
        "Baseline: the pre-match favourite wins the decider (no momentum split):", "",
        _md(base[["by", "fmt", "n", "rate", "se"]]), "",
        "### By level", "", _md(table(dec, ["fmt", "level_group"], p="p_set_pen")), "",
        "### By era", "", _md(table(dec, ["fmt", "era"], p="p_set_pen")), "",
        "### Players with ≥ 20 prior matches each (Elo better informed)", "",
        _md(table(dec[dec["min_n"] >= 20], ["fmt"], p="p_set_pen")), "",
        f"## The pre-match favourite's path ({first}–{last})", "",
        "Does the original favourite make it out? Win rate overall, after winning / losing set 1, and by "
        "set path from the favourite's view (W = favourite won the set; paths under 0.5% left out).", "",
        *fav_section(f),
        "Same, 2010 onwards:", "", *fav_section(f, 2010, paths=False),
    ]
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True, help="tennis-sackmann-archive checkout")
    ap.add_argument("--from", dest="first", type=int, default=1991)
    ap.add_argument("--to", dest="last", type=int, default=2026)
    ap.add_argument("--out", default="reports/upsets_penultimate.md")
    a = ap.parse_args(argv)
    df = elo.add_elo(sackmann.load(a.root, start=1990, lower=True), keys=("winner_id", "loser_id"))
    f = penultimate_frame(df)
    f = f[(f["season"] >= a.first) & (f["season"] <= a.last)]
    text = report(f, a.first, a.last)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
