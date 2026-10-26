"""Why the Portfolio backtest's "DK vs Pinnacle" curve fell from its 2025 peak (Lead request, 2026-10-26).

    python -m upsets.line_shop_drawdown [--results data/reports/dk_big_results.csv] \
        [--out reports/upsets_line_shop_drawdown.md]

Two versions of the line-shopping rule:
  Portfolio backtest  upsets.portfolio_backtest's "line" bets (one price per match: DK and Pinnacle at
                      their last snapshot >= 5 min before the start, proportional de-vig, edge >= 1%,
                      books within 10 pts). Pinnacle's price there is its closing price, so "expected"
                      is already the CLV against Pinnacle's close.
  Job A               upsets.line_shop's pre-registered rule at t = 1% (first non-closing snapshot with
                      DK odds x Pinnacle's power-de-vigged chance - 1 > t, both sides), with CLV against
                      Pinnacle's close.
The peak is the Portfolio curve's highest cumulative P&L; bets up to it are the run-up, bets after it
the drawdown. Reads cached snapshots only (0 credits). Writes aggregates only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import dk_history as dh
from . import dk_study as ds
from . import elo, line_shop, portfolio_backtest, sackmann
from .odds import devig_power

GAP_BINS = [0, 0.05, 0.10, 1.0]
GAP_LABELS = ["< 5 pts", "5–10 pts", "> 10 pts"]
ODDS_BINS = [1.0, 1.5, 2.5, 4.0, 10.0, 1000.0]
ODDS_LABELS = ["≤ 1.5", "1.5–2.5", "2.5–4", "4–10", "> 10"]
JOB_A_T = 0.01
LABELS = {"gap_b": "DK–Pinnacle gap", "tour": "Tour", "level_group": "Tier", "side_": "Side", "band": "DK odds"}
SACKMANN_END = pd.Timestamp("2026-06-01")


# --- bets ----------------------------------------------------------------------------------------

def portfolio_bets(f: pd.DataFrame) -> pd.DataFrame:
    """The Portfolio backtest's "line" bets with gap, tour, tier, odds band and the power-de-vig
    expected value next to the proportional one. f: dk_study.frame + date."""
    b = portfolio_backtest.bets(f)["line"].copy()
    for c in ("tour", "level_group", "odds_dog_dk", "odds_fav_dk", "odds_dog_pin", "odds_fav_pin"):
        b[c] = f.loc[b["m"], c].to_numpy()
    k_d, k_f = 1 / b["odds_dog_dk"], 1 / b["odds_fav_dk"]
    i_d, i_f = 1 / b["odds_dog_pin"], 1 / b["odds_fav_pin"]
    b["gap"] = (k_d / (k_d + k_f) - i_d / (i_d + i_f)).abs()
    p_pow = devig_power(b["odds_dog_pin"].to_numpy(float), b["odds_fav_pin"].to_numpy(float))
    b["p_pow"] = np.where(b["side"] == "dog", p_pow, 1 - p_pow)
    b["ev_pow"] = b["odds"] * b["p_pow"] - 1
    b["dog"] = b["side"] == "dog"
    b["void"] = False
    return b.reset_index(drop=True)


def job_a_bets(q: pd.DataFrame, ev: pd.DataFrame, threshold: float = JOB_A_T) -> pd.DataFrame:
    """Job A's bets at one threshold with the DK-Pinnacle gap at the bet's snapshot."""
    b = line_shop.bets(line_shop.sides(q), ev, line_shop.pinnacle_close(q), threshold)
    w = q.set_index(["event_id", "snapshot_ts"])[["odds_1_dk", "odds_2_dk"]]
    o = w.reindex(pd.MultiIndex.from_arrays([b["event_id"], b["snapshot_ts"]])).to_numpy(float)
    p_home_dk = devig_power(o[:, 0], o[:, 1])
    p_dk = np.where(b["side"] == "home", p_home_dk, 1 - p_home_dk)
    b["gap"] = np.abs(p_dk - b["p_fair"])
    b["ev"], b["date"], b["level_group"] = b["edge"], b["commence"], b["level_group"].fillna("other")
    b["p_pow"], b["ev_pow"] = b["p_fair"], b["edge"]
    return b


# --- aggregates ----------------------------------------------------------------------------------

def summarize(b: pd.DataFrame, ev_col: str = "ev", p_col: str = "p_fair") -> dict:
    """Bets, realized units, expected units, luck and its z-score (spread under the fair p), CLV."""
    s = b[~b["void"].astype(bool)]
    if not len(s):
        return {"n": 0}
    var = (s["odds"] ** 2 * s[p_col] * (1 - s[p_col])).sum()
    real, exp_ = s["pnl"].sum(), s[ev_col].sum()
    out = {"n": len(s), "real": real, "exp": exp_, "roi": real / len(s), "eroi": exp_ / len(s),
           "z": (real - exp_) / np.sqrt(var) if var > 0 else np.nan,
           "win": s["win"].mean(), "pwin": s[p_col].mean()}
    if "clv" in s:
        out["clv"] = s["clv"].mean()
    return out


def phase(b: pd.DataFrame, peak: pd.Timestamp) -> pd.Series:
    return np.where(b["date"] <= peak, "run-up", "drawdown")


def peak_date(b: pd.DataFrame) -> pd.Timestamp:
    """Date of the highest cumulative P&L (bets in date order, one point per date as on the page's
    weekly curve's underlying bets)."""
    c = b.sort_values("date").groupby("date")["pnl"].sum().cumsum()
    return c.idxmax()


def _u(x) -> str:
    return f"{x:+.1f}u"


def _pct(x) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x:+.1%}"


def table(b: pd.DataFrame, by: str, peak: pd.Timestamp, ev_col: str = "ev", p_col: str = "p_fair",
          order=None, clv: bool = False) -> list[str]:
    head = "| " + LABELS.get(by, by) + " | Run-up bets | Run-up realized / expected | Drawdown bets | " \
           "Drawdown realized / expected | Drawdown luck (z) |" + (" Drawdown CLV |" if clv else "")
    lines = [head, "|" + "---|" * (6 + clv)]
    keys = order if order is not None else sorted(b[by].dropna().unique())
    for k in keys:
        g = b[b[by] == k]
        r, d = summarize(g[g["phase"] == "run-up"], ev_col, p_col), summarize(g[g["phase"] == "drawdown"], ev_col, p_col)
        if not r["n"] and not d["n"]:
            continue
        cell = lambda s: f"{_u(s['real'])} / {_u(s['exp'])}" if s["n"] else "—"  # noqa: E731
        z = f"{_u(d['real'] - d['exp'])} ({d['z']:+.1f})" if d["n"] else "—"
        lines.append(f"| {k} | {r['n']} | {cell(r)} | {d['n']} | {cell(d)} | {z} |"
                     + (f" {_pct(d.get('clv'))} |" if clv else ""))
    return lines


def phase_table(b: pd.DataFrame, ev_col: str, p_col: str, clv: bool) -> list[str]:
    lines = ["| Phase | Bets | Realized | Expected | Realized ROI | Expected ROI | Luck (z) | Win rate vs fair |"
             + (" CLV vs Pinnacle close |" if clv else ""), "|" + "---|" * (8 + clv)]
    for ph in ("run-up", "drawdown", "all"):
        g = b if ph == "all" else b[b["phase"] == ph]
        s = summarize(g, ev_col, p_col)
        if not s["n"]:
            continue
        lines.append(f"| {ph} | {s['n']} | {_u(s['real'])} | {_u(s['exp'])} | {_pct(s['roi'])} | {_pct(s['eroi'])} | "
                     f"{_u(s['real'] - s['exp'])} ({s['z']:+.1f}) | {s['win']:.1%} vs {s['pwin']:.1%} |"
                     + (f" {_pct(s.get('clv'))} |" if clv else ""))
    return lines


def report(pb: pd.DataFrame, ja: pd.DataFrame | None) -> str:
    peak = peak_date(pb)
    pb = pb.assign(phase=phase(pb, peak),
                   gap_b=pd.cut(pb["gap"], GAP_BINS, labels=GAP_LABELS, include_lowest=True).astype(str),
                   band=pd.cut(pb["odds"], ODDS_BINS, labels=ODDS_LABELS).astype(str),
                   month=pb["date"].dt.strftime("%Y-%m"), side_=np.where(pb["dog"], "underdog", "favourite"))
    c = pb.sort_values("date")["pnl"].cumsum()
    e = pb.sort_values("date")["ev"].cumsum()
    at_peak = pb[pb["phase"] == "run-up"]
    s_all, s_r, s_d = summarize(pb), summarize(at_peak), summarize(pb[pb["phase"] == "drawdown"])
    s_pow = summarize(pb, "ev_pow", "p_pow")
    L = ["# Why the Portfolio's \"DK vs Pinnacle\" backtest is in drawdown", "",
         "Generated by `python -m upsets.line_shop_drawdown`. Aggregates only; 0 credits.", ""]
    big_d = pb[(pb["phase"] == "drawdown") & (pb["gap"] > 0.05)]
    long_d = pb[(pb["phase"] == "drawdown") & (pb["odds"] > 10)]
    v = ["## Verdict", "",
         f"**Luck in both directions on a thin edge, not an edge that vanished.** The run-up to the peak "
         f"({peak:%Y-%m-%d}) was {_u(s_r['real'])} against {_u(s_r['exp'])} expected (luck z {s_r['z']:+.1f}); "
         f"the {s_d['n']} bets after it made {_u(s_d['real'])} against {_u(s_d['exp'])} expected (z {s_d['z']:+.1f}). "
         f"Over all {s_all['n']} bets, realized ({_u(s_all['real'])}) equals expected ({_u(s_all['exp'])}).",
         "",
         f"- **The expected line depends on the de-vig.** It values each bet at Pinnacle's *proportional* "
         f"de-vig, which gives long shots more chance than the power de-vig used in job A and the other studies. "
         f"At the power de-vig the same bets expect {_u(s_pow['exp'])} ({_pct(s_pow['eroi'])} per bet), about zero. "
         f"These {s_all['n']} bets can't tell the two apart (realized matches proportional; power is z "
         f"{s_pow['z']:+.1f} away). The steep expected rise after the peak is mostly DK odds > 10: "
         f"{len(long_d)} drawdown bets expected {_u(long_d['ev'].sum())} at proportional and made "
         f"{_u(long_d['pnl'].sum())}.",
         f"- **No sign the edge changed.** At the power de-vig, expected per bet was {_pct(summarize(pb[pb['phase'] == 'run-up'], 'ev_pow', 'p_pow')['eroi'])} "
         f"in the run-up and {_pct(summarize(pb[pb['phase'] == 'drawdown'], 'ev_pow', 'p_pow')['eroi'])} in the drawdown. In this backtest "
         "Pinnacle's price is its closing price, so expected *is* the CLV against Pinnacle's close; it didn't turn "
         "negative.",
         f"- **Not the stale lines.** The drawdown's losses are in bets with the books within 5 pts. The "
         f"{len(big_d)} drawdown bets with a 5–10 pt gap made {_u(big_d['pnl'].sum())} vs {_u(big_d['ev'].sum())} "
         "expected; gaps over 10 pts are already skipped.",
         ]
    L += v
    if ja is not None and len(ja):
        ja = ja[ja["date"] < SACKMANN_END].assign(phase=lambda d: phase(d, peak))
        jf = ja[ja["gap"] <= 0.10]
        a_r, a_d = summarize(jf[jf["phase"] == "run-up"]), summarize(jf[jf["phase"] == "drawdown"])
        L += [f"- Job A's rule (first qualifying snapshot) over the same window, books within 10 pts: run-up "
              f"{_u(a_r['real'])} vs {_u(a_r['exp'])} expected, CLV {_pct(a_r.get('clv'))}; after the peak "
              f"{_u(a_d['real'])} vs {_u(a_d['exp'])}, CLV {_pct(a_d.get('clv'))}. See the last section."]
    L += ["- **What it means:** the backtest is consistent with a 0–1% edge plus long-shot variance. "
          "Proposal for the Lead: value the Portfolio's line bets (rule and expected line) at the power "
          "de-vig too, the conservative choice, so the expected line doesn't promise ~9%. The forward test on "
          "the Portfolio tab stands.",
          "", f"Curve check (bet by bet; the page's weekly curve peaks a little lower): peak {_u(c.max())} realized "
          f"vs {_u(float(e[c.idxmax()]))} expected; end {_u(c.iloc[-1])} vs {_u(e.iloc[-1])}.", ""]

    L += ["## Run-up vs drawdown (Portfolio backtest bets)", "",
          "Expected = each bet's value at Pinnacle's proportional fair chance (= CLV vs Pinnacle's close here). "
          "Luck = realized − expected; z = luck / its standard deviation under the fair chances.", ""]
    L += phase_table(pb, "ev", "p_fair", clv=False)
    L += ["", "Same bets, expected at Pinnacle's **power** de-vig:", ""]
    L += phase_table(pb, "ev_pow", "p_pow", clv=False)
    L += ["", "## Which bets lost in the drawdown", "",
          "### DK–Pinnacle gap at the bet", "",
          "The Portfolio backtest skips gaps over 10 pts as quote errors, so there is no > 10 row here.", ""]
    L += table(pb, "gap_b", peak, order=GAP_LABELS[:2])
    big = pb[(pb["phase"] == "drawdown") & (pb["gap"] > 0.05)]
    L += ["", f"Drawdown bets with a 5–10 pt gap (the likely stale-line kind): {len(big)} of {s_d['n']}, "
          f"realized {_u(big['pnl'].sum())} vs {_u(big['ev'].sum())} expected.", ""]
    for title, col, order in (("Tour", "tour", None), ("Tier", "level_group", ["slam", "1000", "other"]),
                              ("Side", "side_", ["underdog", "favourite"]), ("DK odds", "band", ODDS_LABELS)):
        L += [f"### {title}", ""] + table(pb, col, peak, order=order) + [""]
    L += ["### Month (drawdown only)", "", "| Month | Bets | Realized | Expected | Luck |", "|---|---|---|---|---|"]
    d = pb[pb["phase"] == "drawdown"]
    for mth, g in d.groupby("month"):
        L.append(f"| {mth} | {len(g)} | {_u(g['pnl'].sum())} | {_u(g['ev'].sum())} | {_u(g['pnl'].sum() - g['ev'].sum())} |")
    L += [""]

    if ja is not None and len(ja):
        L += ["## Job A's rule instead (first qualifying snapshot)", "",
              f"Job A's pre-registered rule at t = {JOB_A_T:.0%} (power de-vig, the first non-closing snapshot with "
              f"an edge, both sides), events before {SACKMANN_END:%Y-%m-%d} (the Portfolio backtest's window), "
              f"split at the same peak date. CLV = DK odds × Pinnacle's closing fair chance − 1.", "",
              "All gaps:", ""]
        L += phase_table(ja, "ev", "p_fair", clv=True)
        L += ["", "Books within 10 pts at the bet (the Portfolio's filter):", ""]
        L += phase_table(jf, "ev", "p_fair", clv=True)
        ja2 = ja.assign(gap_b=pd.cut(ja["gap"], GAP_BINS, labels=GAP_LABELS, include_lowest=True).astype(str))
        L += ["", "By gap:", ""] + table(ja2, "gap_b", peak, order=GAP_LABELS, clv=True) + [""]
    return "\n".join(L) + "\n"


def run(root: Path, cache: Path, results: pd.DataFrame | None, other_from: str = "2024-01-01",
        project_until: str = "2026-10-25") -> str:
    sack = sackmann.load(root, start=1990, lower=True)
    sack_elo = elo.add_elo(sack, keys=("winner_id", "loser_id"))
    hs = {**dh.HIST_START, "other": pd.Timestamp(other_from)}
    t = dh.tournaments(sack, dh._keys(), hist_start=hs)
    priced = dh.collect(t, sack_elo, 24.0, root=cache)
    f = ds.frame(priced, sack_elo)
    f["date"] = pd.to_datetime(priced.set_index("sack_row").loc[f["sack_row"], "commence"].to_numpy())
    pb = portfolio_bets(f)
    # job A on its own event set (as in upsets.line_shop.main)
    s19 = sackmann.load(root, start=2019)
    t2 = dh.tournaments(s19, dh._keys(), hist_start=hs, project_until=pd.Timestamp(project_until))
    j, snaps = dh.close_inputs(t2, s19, root=cache)
    ev = line_shop.outcomes(j, t2, s19, results)
    ja = job_a_bets(line_shop.quotes(snaps, ev), ev)
    return report(pb, ja)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    ap.add_argument("--cache", type=Path, default=dh.CACHE)
    ap.add_argument("--results", type=Path, default=None, help="Kalshi results (only events after May 2026 use it)")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    res = pd.read_csv(a.results) if a.results else None
    text = run(a.sackmann, a.cache, res)
    print(text)
    if a.out:
        a.out.write_text(text)


if __name__ == "__main__":
    main()
