"""Line shopping: bet a side at DraftKings when its odds beat Pinnacle's fair price in the same
snapshot. The rule is pre-registered in reports/upsets_line_shop.md (committed before this code).

    python -m upsets.line_shop --results data/reports/dk_big_results.csv \
        [--out reports/upsets_line_shop.md]

Reads only cached Odds API snapshots (no paid calls), Sackmann results (events through May 2026) and
the Kalshi results table from the Data role (Jun-Oct 2026). Prints and writes aggregates only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import dk_history as dh
from . import dk_study as ds
from . import sackmann
from .odds import devig_power

THRESHOLDS = (0.0, 0.01, 0.02, 0.03)
LEAD_MIN = 5.0
MIN_SELECT = 30


# --- data ----------------------------------------------------------------------------------------

def outcomes(j: pd.DataFrame, t: pd.DataFrame, sack: pd.DataFrame, results: pd.DataFrame | None) -> pd.DataFrame:
    """One row per rounds 1-2 event with a result: key, tourney_id, event_id, commence, winner
    ('home' | 'away', NaN if void), void, season, tour, level_group."""
    lv = t[["key", "tourney_id", "level_group"]]
    s = j[(j["sack_row"] >= 0) & (j["round_idx"] <= 2)].copy()
    sr = sack.loc[s["sack_row"].to_numpy()]
    s["winner"] = np.where(s["id_home"].astype(str).to_numpy() == sr["winner_id"].astype(str).to_numpy(),
                           "home", "away")
    s["void"] = sr["void"].to_numpy().astype(bool)
    parts = [s]
    if results is not None and len(results):
        k = j[dh.needed(j, t) & (j["sack_row"] < 0)].merge(results, on="event_id")
        if "round" in k:
            k = k[ds.early_round_mask(k)]
        k["void"] = k["void"].astype(bool)
        parts.append(k)
    cols = ["key", "tourney_id", "event_id", "commence", "winner", "void"]
    ev = pd.concat([p[cols] for p in parts], ignore_index=True).drop_duplicates("event_id")
    ev.loc[ev["void"], "winner"] = np.nan
    ev = ev.merge(lv, on=["key", "tourney_id"], how="left")
    ev["season"] = ev["commence"].dt.year
    ev["tour"] = ev["key"].str.extract(r"tennis_(atp|wta)_")[0]
    return ev


def quotes(snaps: pd.DataFrame, ev: pd.DataFrame, lead_min: float = LEAD_MIN) -> pd.DataFrame:
    """Per (event, snapshot) at least lead_min before the listed start: DK and Pinnacle odds
    (home/away), their last_update times, and is_close (the event's last such snapshot)."""
    s = snaps.merge(ev[["event_id", "commence"]], on="event_id")
    s = s[s["snapshot_ts"] <= s["commence"] - pd.Timedelta(minutes=lead_min)]
    s = s[s["book"].isin(["draftkings", "pinnacle"])]
    s = s.sort_values("snapshot_ts").drop_duplicates(["event_id", "snapshot_ts", "book"], keep="last")
    w = s.pivot(index=["event_id", "snapshot_ts"], columns="book", values=["odds_1", "odds_2", "last_update"])
    w.columns = [f"{v}_{'dk' if b == 'draftkings' else 'pin'}" for v, b in w.columns]
    w = w.reset_index().sort_values(["event_id", "snapshot_ts"])
    for c in ("odds_1_dk", "odds_2_dk", "odds_1_pin", "odds_2_pin"):
        if c not in w:
            w[c] = np.nan
        w[c] = w[c].astype(float)
    w["is_close"] = ~w.duplicated("event_id", keep="last")
    return w.reset_index(drop=True)


def pinnacle_close(q: pd.DataFrame) -> pd.Series:
    """Per event: Pinnacle's de-vigged p(home) at the close (the last Pinnacle quote at or before the
    closing snapshot)."""
    p = q.dropna(subset=["odds_1_pin", "odds_2_pin"]).drop_duplicates("event_id", keep="last")
    return pd.Series(devig_power(p["odds_1_pin"].to_numpy(), p["odds_2_pin"].to_numpy()),
                     index=p["event_id"].to_numpy())


def sides(q: pd.DataFrame) -> pd.DataFrame:
    """Long table, one row per (event, snapshot, side) with both books quoted: DK odds on the side,
    Pinnacle's fair p, edge = odds x p - 1, DK minus Pinnacle last_update (min)."""
    b = q.dropna(subset=["odds_1_dk", "odds_2_dk", "odds_1_pin", "odds_2_pin"]).copy()
    p_home = devig_power(b["odds_1_pin"].to_numpy(), b["odds_2_pin"].to_numpy())
    stale = (pd.to_datetime(b["last_update_dk"]) - pd.to_datetime(b["last_update_pin"])).dt.total_seconds() / 60
    out = []
    for side, odds, other, p in (("home", "odds_1_dk", "odds_2_dk", p_home), ("away", "odds_2_dk", "odds_1_dk", 1 - p_home)):
        out.append(pd.DataFrame({
            "event_id": b["event_id"].to_numpy(), "snapshot_ts": b["snapshot_ts"].to_numpy(),
            "is_close": b["is_close"].to_numpy(), "side": side, "odds": b[odds].to_numpy(),
            "dog": (b[odds] > b[other]).to_numpy(), "p_fair": p, "dk_minus_pin_min": stale.to_numpy()}))
    long = pd.concat(out, ignore_index=True)
    long["edge"] = long["odds"] * long["p_fair"] - 1
    return long.sort_values(["event_id", "side", "snapshot_ts"]).reset_index(drop=True)


def bets(long: pd.DataFrame, ev: pd.DataFrame, p_close: pd.Series, threshold: float) -> pd.DataFrame:
    """The pre-registered bets at one threshold: per (event, side) the first non-closing snapshot with
    edge > threshold. Adds the result, P&L and CLV against Pinnacle's close."""
    q = long[~long["is_close"] & (long["edge"] > threshold)]
    b = q.drop_duplicates(["event_id", "side"], keep="first").merge(ev, on="event_id")
    b["threshold"] = threshold
    b["win"] = (b["winner"] == b["side"]).astype(int)
    b["pnl"] = np.where(b["void"], 0.0, np.where(b["win"] == 1, b["odds"] - 1, -1.0))
    pc = b["event_id"].map(p_close)
    b["p_close"] = np.where(b["side"] == "home", pc, 1 - pc)
    b["clv"] = b["odds"] * b["p_close"] - 1
    return b.reset_index(drop=True)


# --- scoring -------------------------------------------------------------------------------------

def cluster_ci(b: pd.DataFrame, col: str, n_boot: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean of `col` over non-void bets with a 95% bootstrap CI, resampling matches (both sides of
    one match move together)."""
    live = b[~b["void"]].dropna(subset=[col])
    if not len(live):
        return np.nan, np.nan, np.nan
    g = live.groupby("event_id")[col].agg(["sum", "size"])
    s, n = g["sum"].to_numpy(), g["size"].to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(n_boot, len(g)))
    boots = s[idx].sum(1) / n[idx].sum(1)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(s.sum() / n.sum()), float(lo), float(hi)


def walk_forward(by_t: dict[float, pd.DataFrame], min_select: int = MIN_SELECT) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Season S bets at the threshold with the best realized P&L on seasons < S (>= min_select
    non-void bets there)."""
    seasons = sorted(set().union(*[set(b["season"]) for b in by_t.values()]))
    rows, picked = [], []
    for i, y in enumerate(seasons):
        if i == 0:
            continue
        best, best_pnl = None, -np.inf
        for t, b in by_t.items():
            prior = b[(b["season"] < y) & ~b["void"]]
            if len(prior) >= min_select and prior["pnl"].sum() > best_pnl:
                best, best_pnl = t, prior["pnl"].sum()
        test = by_t[best][by_t[best]["season"] == y] if best is not None else None
        live = test[~test["void"]] if test is not None else pd.DataFrame(columns=["pnl"])
        rows.append({"season": y, "threshold": best, "bets": len(live), "pnl": float(live["pnl"].sum())})
        if test is not None:
            picked.append(test)
    oos = pd.concat(picked, ignore_index=True) if picked else next(iter(by_t.values())).iloc[:0]
    return oos, pd.DataFrame(rows, columns=["season", "threshold", "bets", "pnl"])


def gate(oos: pd.DataFrame, seasons: pd.DataFrame, min_bets: int = 30) -> dict:
    live = oos[~oos["void"]]
    last4 = seasons.tail(4)
    pos = int((last4["pnl"] > 0).sum())
    checks = {f"OOS bets >= {min_bets} ({len(live)})": len(live) >= min_bets,
              f"OOS P&L > 0 ({live['pnl'].sum():+.1f}u)": bool(len(live)) and live["pnl"].sum() > 0,
              f">= 3 of last 4 seasons positive ({pos}/{len(last4)})": pos >= 3}
    return {"pass": all(checks.values()), "checks": checks}


# --- report --------------------------------------------------------------------------------------

def _p(x) -> str:
    return "—" if x is None or x != x else f"{x:+.1%}"


HEAD = ["| Slice | Bets | Voids | Win rate | Realized ROI (95% CI) | Expected ROI at Pinnacle fair | "
        "CLV vs Pinnacle close (95% CI) |", "|---|---|---|---|---|---|---|"]


def row(name: str, b: pd.DataFrame) -> str:
    live = b[~b["void"]]
    if not len(live):
        return f"| {name} | 0 | {int(b['void'].sum())} | — | — | — | — |"
    r, rlo, rhi = cluster_ci(b, "pnl")
    c, clo, chi = cluster_ci(b, "clv")
    return (f"| {name} | {len(live):,} | {int(b['void'].sum())} | {live['win'].mean():.1%} | "
            f"{_p(r)} ({_p(rlo)} to {_p(rhi)}) | {_p(live['edge'].mean())} | {_p(c)} ({_p(clo)} to {_p(chi)}) |")


def slices(b: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    names = {"slam": "Slams", "1000": "1000s", "other": "250/500s"}
    out = [("All", b), ("… ATP", b[b["tour"] == "atp"]), ("… WTA", b[b["tour"] == "wta"])]
    out += [(f"… {names.get(k, k)}", g) for k, g in b.groupby("level_group")]
    out += [("… underdog side", b[b["dog"]]), ("… favourite side", b[~b["dog"]])]
    out += [(f"… season {int(y)}", g) for y, g in b.groupby("season")]
    return out


def report(ev: pd.DataFrame, q: pd.DataFrame, long: pd.DataFrame, by_t: dict, oos: pd.DataFrame,
           seasons: pd.DataFrame, g: dict) -> str:
    early = long[~long["is_close"]]
    close = long[long["is_close"]]
    ev_any = early[early["edge"] > 0]["event_id"].nunique()
    n_ev = early["event_id"].nunique()
    stale_q = early[early["edge"] > 0]["dk_minus_pin_min"]
    stale_all = early["dk_minus_pin_min"]
    lines = [
        "## Results", "",
        "Generated by `python -m upsets.line_shop`, following the rule above unchanged.", "",
        "### Coverage",
        f"- Rounds 1–2 events with a result: {len(ev):,} (void {int(ev['void'].sum()):,}). Events with at least "
        f"one non-closing snapshot quoted by both books: {n_ev:,}.",
        f"- (event, side, snapshot) rows before the close with both books: {len(early):,}; closing rows: {len(close):,}.",
        "",
        "### How often DraftKings beats Pinnacle's fair price",
        f"- Before the close: {(early['edge'] > 0).mean():.1%} of (event, side, snapshot) rows, and "
        f"{ev_any / max(n_ev, 1):.1%} of events at least once. Rows with edge > 1% / 2% / 3%: "
        f"{(early['edge'] > 0.01).mean():.1%} / {(early['edge'] > 0.02).mean():.1%} / {(early['edge'] > 0.03).mean():.1%}.",
        f"- At the close: {(close['edge'] > 0).mean():.1%} of (event, side) rows.",
        f"- DK quote age vs Pinnacle's (DK `last_update` − Pinnacle `last_update`) when DK beats fair: median "
        f"{stale_q.median():+.0f} min, p10 {stale_q.quantile(0.1):+.0f}, p90 {stale_q.quantile(0.9):+.0f} "
        f"(all rows: median {stale_all.median():+.0f}, p10 {stale_all.quantile(0.1):+.0f}, p90 "
        f"{stale_all.quantile(0.9):+.0f}). Negative = DK's quote is older.",
        "",
        "### Every threshold, full sample (in-sample, diagnostic)", "", *HEAD]
    for t, b in by_t.items():
        lines.append(row(f"t = {t:.0%}", b))
    lines += ["", "### Walk-forward by season (t chosen on earlier seasons only)", "",
              f"**Gate: {'PASS' if g['pass'] else 'FAIL'}**  " + "; ".join(
                  f"{k}: {'yes' if v else 'no'}" for k, v in g["checks"].items()), "",
              "| Season | t chosen | Bets | P&L |", "|---|---|---|---|"]
    for r in seasons.itertuples():
        thr = "—" if r.threshold is None or r.threshold != r.threshold else f"{r.threshold:.0%}"
        lines.append(f"| {r.season} | {thr} | {r.bets} | {r.pnl:+.1f}u |")
    lines += ["", "Out-of-sample bets by slice:", "", *HEAD, *[row(n, b) for n, b in slices(oos)]]
    for t, b in by_t.items():
        lines += ["", f"### All slices at t = {t:.0%} (in-sample)", "", *HEAD, *[row(n, s) for n, s in slices(b)]]
    return "\n".join(lines) + "\n"


def run(t: pd.DataFrame, sack: pd.DataFrame, results: pd.DataFrame | None, root: Path = dh.CACHE):
    j, snaps = dh.close_inputs(t, sack, root=root)
    ev = outcomes(j, t, sack, results)
    q = quotes(snaps, ev)
    long = sides(q)
    pc = pinnacle_close(q)
    by_t = {th: bets(long, ev, pc, th) for th in THRESHOLDS}
    oos, seasons = walk_forward(by_t)
    g = gate(oos, seasons)
    return report(ev, q, long, by_t, oos, seasons, g), dict(ev=ev, q=q, long=long, by_t=by_t, oos=oos,
                                                            seasons=seasons, gate=g)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    ap.add_argument("--cache", type=Path, default=dh.CACHE)
    ap.add_argument("--results", type=Path, default=None, help="Kalshi results: event_id,winner,void[,round]")
    ap.add_argument("--other-from", default="2024-01-01")
    ap.add_argument("--project-until", default="2026-10-25")
    ap.add_argument("--out", type=Path, default=None, help="append the results to this pre-registration file")
    a = ap.parse_args(argv)
    sack = sackmann.load(a.sackmann, start=2019)
    hs = {**dh.HIST_START, "other": pd.Timestamp(a.other_from)}
    t = dh.tournaments(sack, dh._keys(), hist_start=hs, project_until=pd.Timestamp(a.project_until))
    res = pd.read_csv(a.results) if a.results else None
    text, _ = run(t, sack, res, a.cache)
    print(text)
    if a.out:
        body = a.out.read_text()
        body = body.split("## Results")[0].rstrip() + "\n\n" + text
        a.out.write_text(body)


if __name__ == "__main__":
    main()
