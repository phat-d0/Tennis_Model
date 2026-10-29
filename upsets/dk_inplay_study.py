"""DraftKings in-play studies, as pre-registered in reports/upsets_dk_inplay.md (with its amendments).

    python -m upsets.dk_inplay_study [--sackmann PATH] [--out PATH]

Reads only cached Odds API snapshots (0 credits) and Sackmann results. Prints aggregates only.

Sample: the in-play window (a‴) of `upsets.dk_inplay.window` (column live_started), minus matches still postponed
past our pulled window. A trigger or an in-play fill uses an in-window snapshot whose DK quote is at most 5 min old
(1 min as a check). Entries at the close use DK's close (dk_history.prices). Stake 1 unit per position.

1. DK-DOG50: back the close dog (power de-vig p < 20%, also < 30%); hedge to equal payout at the first in-play
   snapshot with the dog's p >= 50%. Control: hold.
2. Exit-level curve: the same entries, hedge level L in 0.40..0.90, plus hold; walk-forward by season on L.
3. DK-MISMATCH50: Sackmann official ranks, ratio >= 4x, better <= 100; back the worse-ranked player at the close,
   hedge at p >= 50%.
4. DK-FAVDIP, close favourite p in 60-80% and >= 80%: (A) back him at the close; (B) back him at the first in-play
   snapshot with p <= 50% (no bet otherwise). Both held.

Hedge: first bet pays N = o1 (stake 1); the hedge stakes N / o2 on the other player at his live odds o2, so the
result is o1 - 1 - o1 / o2 either way. In-play odds are cut by 0%, 3% and 6% of the winnings (backtest.payout_odds).
Voids (walkover, retirement before set 1 completes) refund every leg.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import dk_inplay as di
from .backtest import payout_odds
from .odds import devig_power

CUTS = (0.0, 0.03, 0.06)
GATE_CUT = 0.03
LEVELS = (0.40, 0.50, 0.60, 0.70, 0.80, 0.90)
DOG_CUTS = (0.20, 0.30)
FAV_BANDS = ((0.60, 0.80), (0.80, 1.01))
FRESH_MIN = 5
FRESH_CHECK_MIN = 1
LAST4 = (2023, 2024, 2025, 2026)
SPLITS = (("2025–26 (main)", (2025, 2026)), ("2023–24", (2023, 2024)), ("Pooled", (2023, 2024, 2025, 2026)))


# --- inputs -------------------------------------------------------------------------------------------------------

def live_rows(q: pd.DataFrame, m: pd.DataFrame, home_is_w: pd.Series, f: pd.DataFrame,
              fresh_min: float = FRESH_MIN, with_postponed: bool = False) -> pd.DataFrame:
    """In-play rows usable for a trigger or a fill: in the (a‴) window, match in the sample, DK quote <= fresh_min old.
    Oriented to the close dog/favourite of f (dk_study.frame): odds_dog, odds_fav, p_dog (power de-vig), and the
    Sackmann winner's odds odds_w / odds_l. home_is_w: per match index, True if DK's home player is the winner."""
    keep = m.index[m["live_started"] & (with_postponed | ~m["postponed"])]
    x = q[q["live_started"] & q["match"].isin(keep)].copy()
    x = x[x["draftkings_home"].notna() & x["draftkings_away"].notna()]
    x = x[(x["ts"] - x["draftkings_updated"]) <= pd.Timedelta(minutes=fresh_min)]
    hw = x["match"].map(home_is_w)
    x = x[hw.notna()]
    hw = hw[hw.notna()].astype(bool)
    x["odds_w"] = np.where(hw, x["draftkings_home"], x["draftkings_away"])
    x["odds_l"] = np.where(hw, x["draftkings_away"], x["draftkings_home"])
    x["sack_row"] = x["match"].map(m["sack_row"])
    x = x.merge(f[["sack_row", "upset"]], on="sack_row", how="inner")
    dog_w = x["upset"] == 1
    x["odds_dog"] = np.where(dog_w, x["odds_w"], x["odds_l"])
    x["odds_fav"] = np.where(dog_w, x["odds_l"], x["odds_w"])
    x["p_dog"] = devig_power(x["odds_dog"].to_numpy(), x["odds_fav"].to_numpy())
    # Pinnacle's fair in-play p for the dog at the same snapshot (quote <= fresh_min old), else NaN
    ph, pa = x["pinnacle_home"], x["pinnacle_away"]
    pin_ok = ph.notna() & pa.notna() & ((x["ts"] - x["pinnacle_updated"]) <= pd.Timedelta(minutes=fresh_min))
    hw2 = x["match"].map(home_is_w).astype(bool)
    pin_w, pin_l = np.where(hw2, ph, pa), np.where(hw2, pa, ph)
    pd_, pf_ = np.where(dog_w, pin_w, pin_l), np.where(dog_w, pin_l, pin_w)
    x["p_pin_dog"] = np.nan
    if pin_ok.any():
        x.loc[pin_ok, "p_pin_dog"] = devig_power(pd_[pin_ok.to_numpy()], pf_[pin_ok.to_numpy()])
    return x.sort_values(["sack_row", "ts"]).reset_index(drop=True)


def sample(f: pd.DataFrame, m: pd.DataFrame, with_postponed: bool = False) -> pd.DataFrame:
    """Close-priced matches (dk_study.frame) in the in-play sample (with_postponed: the still-postponed ones too)."""
    ok = m.loc[m["live_started"] & (with_postponed | ~m["postponed"]), "sack_row"]
    return f[f["sack_row"].isin(ok)].reset_index(drop=True)


def first_hit(x: pd.DataFrame, col: str, level: float, above: bool) -> pd.DataFrame:
    """Per sack_row, the first row (in time) with col >= level (above) or col <= level. Uses no later row."""
    hit = x[x[col] >= level] if above else x[x[col] <= level]
    return hit.groupby("sack_row", sort=False).head(1).set_index("sack_row")


# --- rules ---------------------------------------------------------------------------------------------------------

def hold_pnl(odds: pd.Series, won: pd.Series, void: pd.Series) -> pd.Series:
    return pd.Series(np.where(void, 0.0, np.where(won, odds - 1.0, -1.0)), index=odds.index)


def hedge_rule(e: pd.DataFrame, x: pd.DataFrame, level: float | None, cut: float) -> pd.DataFrame:
    """Entries e (sack_row, odds_bet = close odds of the backed side, won, void, side 'dog'|'fav'): hedge to equal
    payout at the first live row where the backed side's p >= level (None = hold). -> e + pnl, hedged."""
    out = e.copy()
    out["pnl"] = hold_pnl(out["odds_bet"], out["won"], out["void"])
    out["hedged"] = False
    out["exp_delta"] = np.nan
    if level is None:
        return out
    xs = x[x["sack_row"].isin(out["sack_row"])].copy()
    side_of = out.set_index("sack_row")["side"]
    xs["p_bet"] = np.where(xs["sack_row"].map(side_of) == "dog", xs["p_dog"], 1 - xs["p_dog"])
    xs["odds_other"] = np.where(xs["sack_row"].map(side_of) == "dog", xs["odds_fav"], xs["odds_dog"])
    xs["p_pin_bet"] = np.where(xs["sack_row"].map(side_of) == "dog", xs["p_pin_dog"], 1 - xs["p_pin_dog"])
    h = first_hit(xs, "p_bet", level, above=True)
    o2 = payout_odds(out["sack_row"].map(h["odds_other"]), cut)
    hit = o2.notna()
    locked = out["odds_bet"] - 1.0 - out["odds_bet"] / o2
    out.loc[hit, "pnl"] = np.where(out.loc[hit, "void"], 0.0, locked[hit])
    out["hedged"] = hit
    # expected cost of the hedge at Pinnacle's fair p at that snapshot: locked - E[hold from there]
    p_fair = out["sack_row"].map(h["p_pin_bet"])
    out["exp_delta"] = np.where(hit & ~out["void"], locked - (p_fair * out["odds_bet"] - 1.0), np.nan)
    return out


def dip_rule(e: pd.DataFrame, x: pd.DataFrame, level: float, cut: float) -> pd.DataFrame:
    """FAVDIP (B): back the close favourite at the first live row with his p <= level, held. No bet if never."""
    xs = x[x["sack_row"].isin(e["sack_row"])].assign(p_fav=lambda d: 1 - d["p_dog"])
    h = first_hit(xs, "p_fav", level, above=False)
    b = e[e["sack_row"].isin(h.index)].copy()
    b["odds_bet"] = payout_odds(b["sack_row"].map(h["odds_fav"]), cut).to_numpy()
    b["pnl"] = hold_pnl(b["odds_bet"], b["won"], b["void"])
    return b


def dog_entries(s: pd.DataFrame, cutoff: float) -> pd.DataFrame:
    d = s[s["p_dk"] < cutoff]
    return pd.DataFrame({"sack_row": d["sack_row"], "season": d["season"], "odds_bet": d["odds_dog_dk"],
                         "p_close": d["p_dk"], "won": d["upset"] == 1, "void": d["void"].astype(bool),
                         "side": "dog"}).reset_index(drop=True)


def fav_entries(s: pd.DataFrame, lo: float, hi: float) -> pd.DataFrame:
    p_fav = 1 - s["p_dk"]
    d = s[(p_fav >= lo) & (p_fav < hi)]
    return pd.DataFrame({"sack_row": d["sack_row"], "season": d["season"], "odds_bet": d["odds_fav_dk"],
                         "p_close": 1 - d["p_dk"], "won": d["upset"] == 0, "void": d["void"].astype(bool),
                         "side": "fav"}).reset_index(drop=True)


def mismatch_entries(s: pd.DataFrame, sack: pd.DataFrame) -> pd.DataFrame:
    """Sackmann official ranks before the match: ratio >= 4x, better <= 100; the worse-ranked player is backed."""
    r = sack.loc[s["sack_row"].to_numpy(), ["w_rank", "l_rank"]].reset_index(drop=True)
    ok = r["w_rank"].notna() & r["l_rank"].notna()
    better, worse = np.minimum(r["w_rank"], r["l_rank"]), np.maximum(r["w_rank"], r["l_rank"])
    ok &= (better <= 100) & (worse >= 4 * better)
    s, r = s[ok.to_numpy()].reset_index(drop=True), r[ok].reset_index(drop=True)
    worse_won = (r["w_rank"] > r["l_rank"]).to_numpy()            # the winner is the worse-ranked player
    worse_is_dog = worse_won == (s["upset"] == 1).to_numpy()       # the worse-ranked player is the close dog
    return pd.DataFrame({"sack_row": s["sack_row"], "season": s["season"],
                         "odds_bet": np.where(worse_is_dog, s["odds_dog_dk"], s["odds_fav_dk"]),
                         "p_close": np.where(worse_is_dog, s["p_dk"], 1 - s["p_dk"]),
                         "won": worse_won, "void": s["void"].astype(bool),
                         "side": np.where(worse_is_dog, "dog", "fav")})


# --- summaries -----------------------------------------------------------------------------------------------------

def stats(b: pd.DataFrame) -> dict:
    p = b["pnl"]
    return {"n": len(b), "pnl": float(p.sum()), "roi": float(p.mean()) if len(b) else np.nan,
            "sd": float(p.std()) if len(b) > 1 else np.nan, "p10": float(p.quantile(0.1)) if len(b) else np.nan,
            "hedged": int(b["hedged"].sum()) if "hedged" in b else np.nan}


def gate(b: pd.DataFrame, min_n: int = 30) -> dict:
    """Fixed-rule gate at the 3% cut (b must be at that cut): >= 30 bets, P&L > 0, >= 3 of the last 4 seasons positive;
    plus the amendment: it must also hold in 2025-26 alone (>= 30 bets and P&L > 0 there)."""
    by = b.groupby("season")["pnl"].sum()
    pos = int(sum(by.get(y, 0.0) > 0 for y in LAST4))
    main = b[b["season"].isin((2025, 2026))]
    ok_all = len(b) >= min_n and b["pnl"].sum() > 0 and pos >= 3
    ok_main = len(main) >= min_n and main["pnl"].sum() > 0
    return {"n": len(b), "pnl": float(b["pnl"].sum()), "pos": pos, "n_main": len(main),
            "pnl_main": float(main["pnl"].sum()), "pass": bool(ok_all and ok_main)}


def walk_forward(e: pd.DataFrame, x: pd.DataFrame, cut: float = GATE_CUT) -> tuple[pd.DataFrame, dict]:
    """Exit level chosen on earlier seasons (total P&L at the cut, hold eligible), tested on the next season."""
    by_level = {L: hedge_rule(e, x, L, cut) for L in (None,) + LEVELS}
    seasons = sorted(e["season"].unique())
    rows = []
    for i, y in enumerate(seasons[1:], start=1):
        prior = seasons[:i]
        tot = {L: b.loc[b["season"].isin(prior), "pnl"].sum() for L, b in by_level.items()}
        best = max(tot, key=lambda L: (tot[L], L is None))       # ties go to hold
        t = by_level[best][by_level[best]["season"] == y]
        rows.append({"season": y, "level": "hold" if best is None else f"{best:.2f}", "n": len(t),
                     "pnl": float(t["pnl"].sum())})
    oos = pd.DataFrame(rows, columns=["season", "level", "n", "pnl"])
    n_pos = int((oos["pnl"] > 0).sum())
    main_pnl = float(oos.loc[oos["season"].isin((2025, 2026)), "pnl"].sum())
    # pre-registered: OOS P&L > 0 in >= 3 test seasons, >= 30 OOS positions; amendment: OOS P&L > 0 in 2025-26 too.
    # With 2023-26 only 2024, 2025 and 2026 can be test seasons, so this needs all three.
    g = {"tests": len(oos), "pos": n_pos, "n": int(oos["n"].sum()), "pnl": float(oos["pnl"].sum()),
         "pnl_main": main_pnl, "pass": bool(n_pos >= 3 and oos["n"].sum() >= 30 and main_pnl > 0)}
    return oos, g


def _fmt(d: dict) -> str:
    return (f"{d['n']:,} | {d['pnl']:+.1f}u | {d['roi']:+.1%} | {d['sd']:.2f} | {d['p10']:+.2f}"
            if d["n"] else "0 | – | – | – | –")


def _split_rows(label: str, b_by_cut: dict, extra=None) -> list[str]:
    L = []
    for name, seasons in SPLITS:
        cells = []
        for c in CUTS:
            b = b_by_cut[c]
            g = b[b["season"].isin(seasons)]
            st = stats(g)
            cells.append(f"{st['pnl']:+.1f}u ({st['roi']:+.1%})" if st["n"] else "–")
        st0 = stats(b_by_cut[GATE_CUT][b_by_cut[GATE_CUT]["season"].isin(seasons)])
        hed = "" if extra is None else f" | {extra(b_by_cut[GATE_CUT][b_by_cut[GATE_CUT]['season'].isin(seasons)])}"
        L.append(f"| {label} | {name} | {st0['n']:,} | " + " | ".join(cells) +
                 f" | {st0['sd']:.2f} | {st0['p10']:+.2f}{hed} |")
    return L


# --- report --------------------------------------------------------------------------------------------------------

def report(s: pd.DataFrame, x: pd.DataFrame, x1: pd.DataFrame, sack: pd.DataFrame, sp=None) -> str:
    L = ["# DK in-play studies: results", "",
         f"Generated by `python -m upsets.dk_inplay_study`. Cached Odds API snapshots only (0 credits); aggregates "
         f"only. Sample: {len(s):,} matches with a DK close in the in-play sample; {x['sack_row'].nunique():,} have a "
         f"usable in-play DK quote (≤ {FRESH_MIN} min old). P&L in units of the first stake; ROI = P&L / positions. "
         f"In-play fills cut 0% / 3% / 6% of the winnings; the gate reads the 3% column. No 5-min snapshots were "
         f"pulled, so the 10-min vs 5-min check can't be run.", ""]
    hdr = ("| Rule | Seasons | Positions | P&L (ROI) cut 0% | cut 3% | cut 6% | SD (3%) | P10 (3%) | Hedged (3%) |",
           "|---|---|---|---|---|---|---|---|---|")
    hcount = lambda b: f"{int(b['hedged'].sum()):,}"  # noqa: E731

    # 1. DOG50
    L += ["## 1. DK-DOG50", ""] + list(hdr)
    gates = []
    for dc in DOG_CUTS:
        e = dog_entries(s, dc)
        hold = {c: hedge_rule(e, x, None, c) for c in CUTS}
        d50 = {c: hedge_rule(e, x, 0.50, c) for c in CUTS}
        L += _split_rows(f"Dog < {dc:.0%}: hold", hold, hcount)
        L += _split_rows(f"Dog < {dc:.0%}: DOG50", d50, hcount)
        gates.append((f"DOG50, dog < {dc:.0%}", gate(d50[GATE_CUT])))
        d1 = hedge_rule(e, x1, 0.50, GATE_CUT)
        L.append(f"| Dog < {dc:.0%}: DOG50, quotes ≤ 1 min | Pooled | {len(d1):,} | – | "
                 f"{d1['pnl'].sum():+.1f}u ({d1['pnl'].mean():+.1%}) | – | – | – | {int(d1['hedged'].sum()):,} |")
    L += [""]

    # 2. exit curve
    L += ["## 2. DK exit-level curve (3% cut)", ""]
    for dc in DOG_CUTS:
        e = dog_entries(s, dc)
        L += [f"Dog < {dc:.0%}:", "", "| Level | Seasons | Positions | Hedged | P&L | ROI | Δ vs hold (per position) | Δ per hedge: realized / "
              "expected at Pinnacle fair (n) | SD | P10 |", "|---|---|---|---|---|---|---|---|---|---|"]
        hold = hedge_rule(e, x, None, GATE_CUT)
        for lv in (None,) + LEVELS:
            b = hedge_rule(e, x, lv, GATE_CUT)
            for name, seasons in SPLITS:
                g, h = b[b["season"].isin(seasons)], hold[hold["season"].isin(seasons)]
                st = stats(g)
                d = (g["pnl"].sum() - h["pnl"].sum()) / max(len(g), 1)
                nh = int(g["hedged"].sum())
                ex = g["exp_delta"].dropna()
                per = (f"{(g['pnl'].sum() - h['pnl'].sum()) / nh:+.3f}u / {ex.mean():+.3f}u ({len(ex):,})"
                       if nh and len(ex) else "–")
                L.append(f"| {'hold' if lv is None else f'{lv:.2f}'} | {name} | {st['n']:,} | {nh:,} | "
                         f"{st['pnl']:+.1f}u | {st['roi']:+.1%} | {d:+.3f}u | {per} | {st['sd']:.2f} | {st['p10']:+.2f} |")
        oos, g = walk_forward(e, x)
        L += ["", f"Walk-forward on L (dog < {dc:.0%}): " + "; ".join(
            f"{int(r.season)} L={r.level} {r.n} positions {r.pnl:+.1f}u" for r in oos.itertuples()) +
            f". OOS {g['n']:,} positions, {g['pnl']:+.1f}u, {g['pos']} of {g['tests']} test seasons positive.", ""]
        gates.append((f"Exit-level walk-forward, dog < {dc:.0%}", {**g, "wf": True}))

    # 3. MISMATCH50
    e = mismatch_entries(s, sack)
    L += ["## 3. DK-MISMATCH50", "", f"Qualifying matches: {len(e):,} (worse-ranked player is the close dog in "
          f"{(e['side'] == 'dog').mean():.0%}).", ""] + list(hdr)
    hold = {c: hedge_rule(e, x, None, c) for c in CUTS}
    m50 = {c: hedge_rule(e, x, 0.50, c) for c in CUTS}
    L += _split_rows("Hold", hold, hcount) + _split_rows("MISMATCH50", m50, hcount)
    gates.append(("MISMATCH50", gate(m50[GATE_CUT])))
    below = e[(e["p_close"] < 0.5) & ~e["void"]]
    reached = hedge_rule(below, x, 0.50, 0.0)["hedged"]
    L += ["", f"Reach 50% (non-void, close p < 50%, {len(below):,} matches): {reached.mean():.1%} reached it; "
          f"the close implies {np.minimum(1, below['p_close'] / 0.5).mean():.1%} (p / 0.5).", ""]

    # 4. FAVDIP
    L += ["## 4. DK-FAVDIP", "", "| Band | Seasons | A: positions | A: P&L (ROI) | B: positions | B: P&L (ROI), cut 0% | "
          "cut 3% | cut 6% | A on B's matches |", "|---|---|---|---|---|---|---|---|---|"]
    for lo, hi in FAV_BANDS:
        e = fav_entries(s, lo, hi)
        a = hedge_rule(e, x, None, 0.0)
        bb = {c: dip_rule(e, x, 0.50, c) for c in CUTS}
        band = f"{lo:.0%}–{min(hi, 1):.0%}" if hi <= 1 else f"≥ {lo:.0%}"
        for name, seasons in SPLITS:
            ga = a[a["season"].isin(seasons)]
            cells = []
            for c in CUTS:
                g = bb[c][bb[c]["season"].isin(seasons)]
                cells.append(f"{g['pnl'].sum():+.1f}u ({g['pnl'].mean():+.1%})" if len(g) else "–")
            gb = bb[GATE_CUT][bb[GATE_CUT]["season"].isin(seasons)]
            same = ga[ga["sack_row"].isin(gb["sack_row"])]
            L.append(f"| {band} | {name} | {len(ga):,} | {ga['pnl'].sum():+.1f}u ({ga['pnl'].mean():+.1%}) | {len(gb):,} | "
                     + " | ".join(cells) + f" | {same['pnl'].sum():+.1f}u ({same['pnl'].mean():+.1%}) |")
        gates.append((f"FAVDIP (B), {band}", gate(bb[GATE_CUT])))
        b1 = dip_rule(e, x1, 0.50, GATE_CUT)
        L.append(f"| {band} | Pooled, quotes ≤ 1 min | – | – | {len(b1):,} | – | "
                 f"{b1['pnl'].sum():+.1f}u ({b1['pnl'].mean():+.1%}) | – | – |")
    L += [""]

    # robustness: the still-postponed (a‴) matches put back (their exclusion uses later information)
    if sp is not None:
        s2, x2 = sp
        L += ["## Robustness: still-postponed matches included (descriptive, not a gate input)", "",
              f"{len(s2) - len(s):,} more matches with a DK close. Pooled, 3% cut.", "",
              "| Rule | Positions | P&L | ROI | Hedged / triggered |", "|---|---|---|---|---|"]
        rows = []
        for dc in DOG_CUTS:
            rows.append((f"DOG50, dog < {dc:.0%}", hedge_rule(dog_entries(s2, dc), x2, 0.50, GATE_CUT)))
            rows.append((f"Hold, dog < {dc:.0%}", hedge_rule(dog_entries(s2, dc), x2, None, GATE_CUT)))
        rows.append(("MISMATCH50", hedge_rule(mismatch_entries(s2, sack), x2, 0.50, GATE_CUT)))
        for lo, hi in FAV_BANDS:
            band = f"{lo:.0%}–{hi:.0%}" if hi <= 1 else f"≥ {lo:.0%}"
            rows.append((f"FAVDIP (B), {band}", dip_rule(fav_entries(s2, lo, hi), x2, 0.50, GATE_CUT).assign(hedged=True)))
        for name, b in rows:
            L.append(f"| {name} | {len(b):,} | {b['pnl'].sum():+.1f}u | {b['pnl'].mean():+.1%} | {int(b['hedged'].sum()):,} |")
        L += [""]

    # gates
    L += ["## Gates", "", "| Rule | Verdict | Detail |", "|---|---|---|"]
    for name, g in gates:
        if g.get("wf"):
            det = (f"OOS {g['n']:,} positions, {g['pnl']:+.1f}u, {g['pos']} of {g['tests']} test seasons positive "
                   f"(only {g['tests']} test seasons exist: 2023 has no earlier season)")
        else:
            det = (f"{g['n']:,} bets, {g['pnl']:+.1f}u at 3%, {g['pos']} of 4 seasons positive; 2025–26: "
                   f"{g['n_main']:,} bets, {g['pnl_main']:+.1f}u")
        L.append(f"| {name} | {'PASS' if g['pass'] else 'FAIL'} | {det} |")
    return "\n".join(L) + "\n"


def load(sackmann_path: Path):
    """-> (sack, f: dk_study.frame of the priced matches, m, q, home_is_w)."""
    from . import dk_close_check as cc
    from . import dk_history as dh
    from . import dk_study as ds
    from . import elo, sackmann
    sack = sackmann.load(sackmann_path, start=1990, lower=True)
    sack_elo = elo.add_elo(sack, keys=("winner_id", "loser_id"))
    t = dh.tournaments(sack, dh._keys(), hist_start={**dh.HIST_START, "other": pd.Timestamp("2024-01-01")})
    priced = dh.collect(t, sack_elo, 24.0)
    w = di.windows(priced, sack)
    ce = di.close_event_ids(t, sack).reindex(priced["sack_row"].to_numpy())
    w["close_event_id"] = ce["event_id"].to_numpy()
    w["commence"] = pd.Series(pd.to_datetime(ce["commence"], utc=True).to_numpy()).fillna(w["commence"]).to_numpy()
    keep = (w["season"] >= 2023).to_numpy()
    mins = sack.loc[priced["sack_row"].to_numpy(), "minutes"].reset_index(drop=True)
    m, q = di.replay(w[keep].reset_index(drop=True), mins[keep].reset_index(drop=True))
    need, _ = cc._need(t, sack)
    id_home = need.drop_duplicates(["sack_row", "event_id"]).set_index(["sack_row", "event_id"])["id_home"]
    key = pd.MultiIndex.from_arrays([m["sack_row"], m["event_id"]])
    home = pd.Series(id_home.reindex(key).to_numpy(), index=m.index)
    win = sack.loc[m["sack_row"].to_numpy(), "winner_id"].astype(str).to_numpy()
    home_is_w = pd.Series(np.where(home.isna(), np.nan, home.astype(str).to_numpy() == win), index=m.index)
    f = ds.frame(priced, sack_elo)
    return sack, f, m, q, home_is_w


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    sack, f, m, q, home_is_w = load(a.sackmann)
    s = sample(f, m)
    x = live_rows(q, m, home_is_w, s)
    x1 = live_rows(q, m, home_is_w, s, FRESH_CHECK_MIN)
    s2 = sample(f, m, with_postponed=True)
    x2 = live_rows(q, m, home_is_w, s2, with_postponed=True)
    text = report(s, x, x1, sack, (s2, x2))
    print(text)
    if a.out:
        a.out.write_text(text)


if __name__ == "__main__":
    main()
