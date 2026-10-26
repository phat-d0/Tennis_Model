"""Early-round upsets at DraftKings' price: Slams 2020+ and 1000s 2024+, rounds 1-2, ATP + WTA.

    python -m upsets.dk_study [--sackmann PATH] [--out reports/upsets_dk.md]

Reads the cached Odds API snapshots (upsets.dk_history; never committed) and the Sackmann results.
A bet is 1 unit on the underdog (longer DraftKings odds) at the snapshot price taken >= 5 min before
the listed commence time. Payout = stake x (odds - 1); DraftKings voids walkovers and retirements
before set 1 is complete (stake back). Haircuts cut the winnings (the price may have moved by the
time a bet is placed). Prints aggregates only.

(a) Every early-round underdog, against a seeded favourite and overall, by DraftKings price band.
(b) Elo model walk-forward by season: P(win) = logistic(Elo logit, x best-of-5) refitted on
    Sackmann rounds 1-2 before each season; bet the dog when p x odds - 1 >= threshold, with the
    threshold chosen on earlier seasons only (best P&L at the 3% haircut, >= `min_select_bets`).
    Gate: >= 30 OOS bets, OOS P&L > 0 at 0% and 3%, >= 3 of the last 4 seasons positive at 3%.
(c) DraftKings vs Pinnacle: margins, de-vigged calibration, log loss.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import dk_history as dh
from . import elo, sackmann
from . import kalshi_elo as ke  # noqa: F401  (name matching, TOURS)
from .backtest import payout_odds, settle
from .odds import devig_power, overround

EDGE_GRID = (0.0, 0.02, 0.05, 0.08, 0.10, 0.15)
ODDS_BANDS = (1.0, 2.0, 3.0, 5.0, 10.0, np.inf)
P_BINS = (0.0, 0.15, 0.25, 0.35, 0.45, 0.5)
HAIRCUTS = (0.0, 0.03)


def frame(priced: pd.DataFrame, sack_elo: pd.DataFrame, fit_min_n: int = 10) -> pd.DataFrame:
    """Priced matches (dk_history.collect) + Sackmann rows -> one row per match, favourite/underdog
    by DraftKings' odds (pre-match), with model p for the dog."""
    p = priced.dropna(subset=["odds_w_draftkings", "odds_l_draftkings"])
    s = sack_elo.loc[p["sack_row"].to_numpy()].reset_index(drop=True)
    p = p.reset_index(drop=True)
    w, l = p["odds_w_draftkings"], p["odds_l_draftkings"]
    w_rank, l_rank = s["w_rank"].fillna(1500), s["l_rank"].fillna(1500)
    dog_w = (w > l) | ((w == l) & (w_rank > l_rank))
    pick = lambda a, b, dog: np.where(dog_w, a, b) if dog else np.where(dog_w, b, a)  # noqa: E731
    f = pd.DataFrame({
        "sack_row": p["sack_row"], "key": p.get("key"), "season": s["season"], "tour": s["tour"],
        "level_group": s["level_group"], "tournament": s["tournament"], "round_idx": s["round_idx"],
        "best_of": s["best_of"], "upset": dog_w.astype(int).to_numpy(), "void": s["void"].to_numpy(),
        "seed_dog": pick(s["w_seed"], s["l_seed"], True), "seed_fav": pick(s["w_seed"], s["l_seed"], False),
        "odds_dog_dk": pick(w, l, True), "odds_fav_dk": pick(w, l, False),
        "age_min_dk": p["age_min_draftkings"],
        "elo_dog": pick(s["w_elo"], s["l_elo"], True), "elo_fav": pick(s["w_elo"], s["l_elo"], False),
        "min_n": np.minimum(s["w_n"], s["l_n"]),
    })
    if "odds_w_pinnacle" in p:
        f["odds_dog_pin"] = pick(p["odds_w_pinnacle"], p["odds_l_pinnacle"], True)
        f["odds_fav_pin"] = pick(p["odds_w_pinnacle"], p["odds_l_pinnacle"], False)
    else:
        f["odds_dog_pin"] = f["odds_fav_pin"] = np.nan
    f["p_dk"] = devig_power(f["odds_dog_dk"].to_numpy(), f["odds_fav_dk"].to_numpy())
    has_pin = f["odds_dog_pin"].notna() & f["odds_fav_pin"].notna()
    f["p_pin"] = np.nan
    f.loc[has_pin, "p_pin"] = devig_power(f.loc[has_pin, "odds_dog_pin"].to_numpy(),
                                          f.loc[has_pin, "odds_fav_pin"].to_numpy())
    f["margin_dk"] = overround(f["odds_dog_dk"], f["odds_fav_dk"])
    f["margin_pin"] = overround(f["odds_dog_pin"], f["odds_fav_pin"])
    # model p: calibration refitted before each season on Sackmann rounds 1-2 only
    f["p_model"] = np.nan
    for season in sorted(f["season"].unique()):
        cal = ke.fit_calibration(sack_elo, pd.Timestamp(f"{season}-01-01"), min_n=fit_min_n)
        m = f["season"] == season
        bo5 = (f.loc[m, "best_of"] == 5).to_numpy()
        f.loc[m, "p_model"] = cal.predict(ke._x((f.loc[m, "elo_dog"] - f.loc[m, "elo_fav"]).to_numpy(), bo5))
    f["edge"] = f["p_model"] * f["odds_dog_dk"] - 1.0
    f["band"] = pd.cut(f["odds_dog_dk"], ODDS_BANDS)
    return f


def frame_unresolved(u: pd.DataFrame, results: pd.DataFrame) -> pd.DataFrame:
    """Projected-event price rows (dk_history.unresolved_prices) + a results table
    (event_id, winner = 'home' | 'away', void) -> rows shaped like frame(); no Sackmann seeds or Elo."""
    r = u.merge(results[["event_id", "winner", "void"]], on="event_id", how="inner")
    r = r.dropna(subset=["odds_home_draftkings", "odds_away_draftkings"])
    r = r[r["winner"].isin(["home", "away"]) | r["void"].astype(bool)]
    h, a = r["odds_home_draftkings"], r["odds_away_draftkings"]
    dog_home = h > a
    pick = lambda x, y, dog: np.where(dog_home, x, y) if dog else np.where(dog_home, y, x)  # noqa: E731
    f = pd.DataFrame({
        "sack_row": -1, "key": r["key"].to_numpy(), "season": r["commence"].dt.year.to_numpy(),
        "tour": r["key"].str.extract(r"tennis_(atp|wta)_")[0].to_numpy(), "level_group": "other",
        "tournament": r["tourney_id"].to_numpy(), "round_idx": np.nan, "best_of": 3.0,
        "upset": (np.where(dog_home, r["winner"] == "home", r["winner"] == "away")).astype(int),
        "void": r["void"].astype(bool).to_numpy(), "seed_dog": np.nan, "seed_fav": np.nan,
        "odds_dog_dk": pick(h, a, True), "odds_fav_dk": pick(h, a, False),
        "age_min_dk": np.where(dog_home, r["age_min_draftkings"], r["age_min_draftkings"]),
        "elo_dog": np.nan, "elo_fav": np.nan, "min_n": np.nan,
        "odds_dog_pin": pick(r["odds_home_pinnacle"], r["odds_away_pinnacle"], True),
        "odds_fav_pin": pick(r["odds_home_pinnacle"], r["odds_away_pinnacle"], False)})
    f["p_dk"] = devig_power(f["odds_dog_dk"].to_numpy(), f["odds_fav_dk"].to_numpy())
    has_pin = f["odds_dog_pin"].notna() & f["odds_fav_pin"].notna()
    f["p_pin"] = np.nan
    f.loc[has_pin, "p_pin"] = devig_power(f.loc[has_pin, "odds_dog_pin"].to_numpy(),
                                          f.loc[has_pin, "odds_fav_pin"].to_numpy())
    f["margin_dk"] = overround(f["odds_dog_dk"], f["odds_fav_dk"])
    f["margin_pin"] = overround(f["odds_dog_pin"], f["odds_fav_pin"])
    f["p_model"], f["edge"] = np.nan, np.nan
    f["band"] = pd.cut(f["odds_dog_dk"], ODDS_BANDS)
    return f


def match_list(u: pd.DataFrame) -> pd.DataFrame:
    """What Data needs to find results: no odds (event_id, tour, commence, home, away)."""
    return u.assign(tour=u["key"].str.extract(r"tennis_(atp|wta)_")[0])[
        ["event_id", "tour", "commence", "home", "away"]]


def results_from_kalshi(ml: pd.DataFrame, matches: pd.DataFrame, sets: pd.DataFrame | None = None,
                        max_days: float = 1.5) -> pd.DataFrame:
    """Run where the Kalshi data lives (Data). Match each listed event to a Kalshi ATP/WTA match by
    the two players' names (accent/word-order insensitive) and start within max_days; winner from
    settle_a/settle_b. void = DraftKings' rule as far as Kalshi shows it: a fair-price settlement
    (not started) or, with the sets table, set 1 settled at a fair price (retirement in set 1).
    Returns event_id, winner ('home' | 'away'), void, match_id."""
    km = matches[matches["series"].isin(ke.TOURS)].copy()
    km["tour"] = km["series"].map(ke.TOURS)
    km["pair"] = [" | ".join(sorted((ke.name_key(a), ke.name_key(b))))
                  for a, b in zip(km["player_a"], km["player_b"])]
    ml = ml.copy()
    ml["pair"] = [" | ".join(sorted((ke.name_key(a), ke.name_key(b)))) for a, b in zip(ml["home"], ml["away"])]
    j = ml.merge(km[["match_id", "tour", "pair", "scheduled_start", "player_a", "settle_a", "settle_b"]],
                 on=["tour", "pair"])
    start = pd.to_datetime(j["scheduled_start"], utc=True).dt.tz_localize(None)
    com = pd.to_datetime(j["commence"], utc=True).dt.tz_localize(None)
    j = j[(start - com).abs() <= pd.Timedelta(days=max_days)]
    j = j.assign(gap=(start - com).abs()).sort_values("gap").drop_duplicates("event_id")
    home_is_a = [ke.name_key(h) == ke.name_key(a) for h, a in zip(j["home"], j["player_a"])]
    settle_home = np.where(home_is_a, j["settle_a"], j["settle_b"])
    fair = ~np.isin(j["settle_a"], [0.0, 1.0])
    void = fair.copy()
    if sets is not None and len(sets):
        s1 = sets[(sets["set_no"] == 1) & (sets["status"] == "fair_price")]["match_id"]
        void |= j["match_id"].isin(s1).to_numpy()
    out = pd.DataFrame({"event_id": j["event_id"].to_numpy(), "match_id": j["match_id"].to_numpy(),
                        "winner": np.where(fair, None, np.where(settle_home == 1.0, "home", "away")),
                        "void": void})
    return out


def pnl(b: pd.DataFrame, haircut: float = 0.0, odds_col: str = "odds_dog_dk") -> pd.Series:
    return settle(b.assign(_o=payout_odds(b[odds_col], haircut)), "_o")


def summary(b: pd.DataFrame, haircut: float = 0.0, odds_col: str = "odds_dog_dk",
            n_boot: int = 2000, seed: int = 0) -> dict:
    live = b[~b["void"]]
    if not len(live):
        return {"bets": 0, "void": int(b["void"].sum()), "pnl": 0.0, "roi": np.nan, "lo": np.nan,
                "hi": np.nan, "upset": np.nan, "implied": np.nan}
    x = pnl(live, haircut, odds_col).to_numpy()
    rng = np.random.default_rng(seed)
    boots = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1) if len(x) > 1 else x
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return {"bets": len(live), "void": int(b["void"].sum()), "pnl": float(x.sum()), "roi": float(x.mean()),
            "lo": float(lo), "hi": float(hi), "upset": float(live["upset"].mean()),
            "implied": float((1 / live[odds_col]).mean())}


def walk_forward(f: pd.DataFrame, grid=EDGE_GRID, select_haircut: float = 0.03,
                 min_select_bets: int = 30, min_n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """OOS bets (with the chosen threshold) and a per-season table; season i's threshold comes
    from seasons < i only."""
    use = f[f["min_n"] >= min_n]
    seasons = sorted(use["season"].unique())
    picked, rows = [], []
    for i, y in enumerate(seasons):
        if i == 0:
            continue
        prior = use[use["season"] < y]
        best, best_pnl = None, -np.inf
        for t in grid:
            sel = prior[(prior["edge"] >= t) & ~prior["void"]]
            if len(sel) >= min_select_bets:
                v = pnl(sel, select_haircut).sum()
                if v > best_pnl:
                    best, best_pnl = t, v
        test = use[(use["season"] == y) & (use["edge"] >= best)] if best is not None else use.iloc[:0]
        live = test[~test["void"]]
        rows.append({"season": y, "threshold": best, "bets": len(live),
                     **{f"pnl_{int(h * 100)}": float(pnl(live, h).sum()) if len(live) else 0.0 for h in HAIRCUTS}})
        picked.append(test.assign(threshold=best))
    oos = pd.concat(picked, ignore_index=True) if picked else f.iloc[:0].assign(threshold=np.nan)
    cols = ["season", "threshold", "bets"] + [f"pnl_{int(h * 100)}" for h in HAIRCUTS]
    return oos, pd.DataFrame(rows, columns=cols)


def gate(oos: pd.DataFrame, seasons: pd.DataFrame, min_bets: int = 30) -> dict:
    live = oos[~oos["void"]]
    last4 = seasons.tail(4)
    pos = int((last4["pnl_3"] > 0).sum())
    checks = {f"OOS bets >= {min_bets} ({len(live)})": len(live) >= min_bets,
              **{f"OOS P&L > 0 at {h:.0%} haircut": (pnl(live, h).sum() > 0 if len(live) else False)
                 for h in HAIRCUTS},
              f">= 3 of last 4 seasons positive at 3% ({pos}/{len(last4)})": pos >= 3}
    return {"pass": all(checks.values()), "checks": checks}


# --- report ----------------------------------------------------------------------------------

def _pct(x) -> str:
    return "—" if x is None or x != x else f"{x:+.1%}"


ROW_HEAD = ["| Slice | Bets | Voids | Upset rate | DK implied | ROI at DK | 95% CI | ROI DK −3% | ROI at Pinnacle |",
            "|---|---|---|---|---|---|---|---|---|"]


def _row(name: str, b: pd.DataFrame) -> str:
    s = summary(b)
    if not s["bets"]:
        return f"| {name} | 0 | {s['void']} | — | — | — | — | — | — |"
    s3 = summary(b, 0.03)
    pin = b.dropna(subset=["odds_dog_pin"])
    sp = summary(pin, 0.0, "odds_dog_pin") if len(pin) else {"roi": np.nan, "bets": 0}
    return (f"| {name} | {s['bets']:,} | {s['void']} | {s['upset']:.1%} | {s['implied']:.1%} | "
            f"{_pct(s['roi'])} | {_pct(s['lo'])} to {_pct(s['hi'])} | {_pct(s3['roi'])} | "
            f"{_pct(sp['roi'])} ({sp['bets']:,}) |")


def _logloss(y, p) -> float:
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def scope_label(f: pd.DataFrame) -> str:
    names = {"slam": "Slams", "1000": "1000s", "other": "250/500s"}
    parts = [f"{names.get(lv, lv)} {int(g['season'].min())}–{int(g['season'].max())}"
             for lv, g in f.groupby("level_group")]
    return ", ".join(parts) + ", rounds 1–2"


def report(f: pd.DataFrame, priced: pd.DataFrame, oos: pd.DataFrame, seasons: pd.DataFrame, g: dict,
           min_n: int) -> str:
    seeded = f[f["seed_fav"].notna() & f["seed_dog"].isna()]
    age = f["age_min_dk"]
    a = priced.attrs
    lines = [
        f"# Early-round upsets at DraftKings' price ({scope_label(f)})", "",
        "Odds: The Odds API historical snapshots (DraftKings Sportsbook + Pinnacle; not redistributed). "
        "Results: Jeff Sackmann's match files (CC BY-NC-SA 4.0). 1 unit on the underdog (longer DK odds) "
        "at the last snapshot ≥ 5 min before the listed start; DK voids walkovers and retirements before "
        "set 1 is complete. Aggregates only.", "",
        "## Coverage",
        f"- Events listed {a.get('listed', 0):,}; joined to Sackmann {a.get('joined', 0):,}; rounds 1–2 "
        f"{a.get('r12', 0):,}; with a DraftKings price {len(f):,} (Pinnacle too: "
        f"{int(f['odds_dog_pin'].notna().sum()):,}).",
        f"- DraftKings price age before the listed start: median {age.median():.0f} min, p90 "
        f"{age.quantile(0.9):.0f} min.",
        "", "## (a) Every early-round underdog", "", *ROW_HEAD,
        _row("All", f), _row("… ATP", f[f["tour"] == "atp"]), _row("… WTA", f[f["tour"] == "wta"]),
        _row("… Slams", f[f["level_group"] == "slam"]), _row("… 1000s", f[f["level_group"] == "1000"]),
        _row("Seeded favourite vs unseeded dog", seeded),
        _row("… ATP", seeded[seeded["tour"] == "atp"]), _row("… WTA", seeded[seeded["tour"] == "wta"]),
        "", "By DraftKings underdog odds:", "", *ROW_HEAD]
    for band, b in f.groupby("band", observed=True):
        lines.append(_row(f"dog odds {band}", b))
    lines += ["", "Seeded favourite only, by underdog odds:", "", *ROW_HEAD]
    for band, b in seeded.groupby("band", observed=True):
        lines.append(_row(f"dog odds {band}", b))

    lines += ["", "## (b) Elo model, walk-forward by season", "",
              f"**Gate: {'PASS' if g['pass'] else 'FAIL'}**  "
              + "; ".join(f"{k}: {'yes' if v else 'no'}" for k, v in g["checks"].items()), "",
              *ROW_HEAD, _row("OOS, all", oos), _row("… ATP", oos[oos["tour"] == "atp"]),
              _row("… WTA", oos[oos["tour"] == "wta"]), "",
              "| Season | Threshold | Bets | P&L 0% | P&L −3% |", "|---|---|---|---|---|"]
    for r in seasons.itertuples():
        thr = "—" if r.threshold is None or r.threshold != r.threshold else f"{r.threshold:.2f}"
        lines.append(f"| {r.season} | {thr} | {r.bets} | {r.pnl_0:+.1f}u | {r.pnl_3:+.1f}u |")
    use = f[f["min_n"] >= min_n]
    lines += ["", "Fixed thresholds over all seasons (in-sample, diagnostic):", "", *ROW_HEAD,
              _row("Every dog (≥ min history)", use)]
    for t in EDGE_GRID:
        lines.append(_row(f"edge ≥ {t:.2f}", use[use["edge"] >= t]))

    both = f.dropna(subset=["p_pin"])
    done = both[~both["void"]]
    lines += ["", "## (c) DraftKings vs Pinnacle", "",
              "| Book | Matches | Mean margin | Median margin | Log loss (de-vigged) | Mean p(dog) |",
              "|---|---|---|---|---|---|"]
    y = done["upset"].to_numpy()
    for book, mcol, pcol in (("DraftKings", "margin_dk", "p_dk"), ("Pinnacle", "margin_pin", "p_pin")):
        lines.append(f"| {book} | {len(both):,} | {both[mcol].mean():.2%} | {both[mcol].median():.2%} | "
                     f"{_logloss(y, done[pcol]) if len(done) else float('nan'):.4f} | {done[pcol].mean():.1%} |")
    if len(done):
        de = done.dropna(subset=["p_model"])
        lines.append(f"| Elo model (Sackmann-resolved only) | {len(de):,} | | | "
                     f"{_logloss(de['upset'].to_numpy(), de['p_model']):.4f} | "
                     f"{de['p_model'].mean():.1%} |")
        lines.append(f"| Realized | {len(done):,} | | | | {y.mean():.1%} |")
    lines += ["", "Margin by tour:", "", "| Tour | DK margin | Pinnacle margin |", "|---|---|---|"]
    for t, b in both.groupby("tour"):
        lines.append(f"| {t.upper()} | {b['margin_dk'].mean():.2%} | {b['margin_pin'].mean():.2%} |")
    lines += ["", "Calibration by Pinnacle's de-vigged p(dog):", "",
              "| p(dog) | Matches | Upset rate | DK de-vigged | Pinnacle de-vigged | Elo model |",
              "|---|---|---|---|---|---|"]
    for bucket, b in done.groupby(pd.cut(done["p_pin"], P_BINS), observed=True):
        lines.append(f"| {bucket} | {len(b)} | {b['upset'].mean():.1%} | {b['p_dk'].mean():.1%} | "
                     f"{b['p_pin'].mean():.1%} | {b['p_model'].mean():.1%} |")
    return "\n".join(lines) + "\n"


def run(priced: pd.DataFrame, sack_elo: pd.DataFrame, min_n: int = 10, min_select_bets: int = 30,
        fit_min_n: int = 10, results: pd.DataFrame | None = None) -> tuple[str, dict]:
    f = frame(priced, sack_elo, fit_min_n)
    u = priced.attrs.get("unresolved")
    if results is not None and u is not None and len(u):
        f = pd.concat([f, frame_unresolved(u, results)], ignore_index=True)
    oos, seasons = walk_forward(f, min_select_bets=min_select_bets, min_n=min_n)
    g = gate(oos, seasons)
    return report(f, priced, oos, seasons, g, min_n), dict(frame=f, oos=oos, seasons=seasons, gate=g)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    ap.add_argument("--cache", type=Path, default=dh.CACHE)
    ap.add_argument("--events-step-h", type=float, default=24.0)
    ap.add_argument("--min-history", type=int, default=10)
    ap.add_argument("--tiers", default=None, help="comma list: slam,1000,other")
    ap.add_argument("--other-from", default=None)
    ap.add_argument("--project-until", default=None)
    ap.add_argument("--results", type=Path, default=None,
                    help="results for post-Sackmann events (event_id, winner home|away, void): csv/parquet")
    ap.add_argument("--export-matches", type=Path, default=None,
                    help="write the post-Sackmann match list (no odds) for Data's Kalshi results join")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)
    sack = sackmann.load(a.sackmann, start=1990, lower=True)
    sack_elo = elo.add_elo(sack, keys=("winner_id", "loser_id"))
    hs = {**dh.HIST_START, "other": pd.Timestamp(a.other_from)} if a.other_from else None
    t = dh.tournaments(sack, dh._keys(), hist_start=hs,
                       project_until=pd.Timestamp(a.project_until) if a.project_until else None)
    if a.tiers:
        t = t[t["level_group"].isin(a.tiers.split(","))].reset_index(drop=True)
    priced = dh.collect(t, sack_elo, a.events_step_h, root=a.cache)
    if not len(priced):
        raise SystemExit("no priced matches in the cache: run upsets.dk_history first")
    if a.export_matches:
        a.export_matches.parent.mkdir(parents=True, exist_ok=True)
        match_list(priced.attrs.get("unresolved", pd.DataFrame())).to_csv(a.export_matches, index=False)
        print(f"[match list -> {a.export_matches}]")
    res = None
    if a.results:
        res = pd.read_parquet(a.results) if a.results.suffix == ".parquet" else pd.read_csv(a.results)
    text, _ = run(priced, sack_elo, a.min_history, results=res)
    print(text)
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text)


if __name__ == "__main__":
    main()
