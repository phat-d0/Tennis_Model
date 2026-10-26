"""Elo upgrades, judged against Pinnacle's de-vigged price on the same matches (job B).

    python -m upsets.elo_plus [--out reports/upsets_elo_plus.md]

Variants, all wrapped in the same calibration as the current model (a symmetric logistic on the
rating logit, x best-of-5, plus any extra features), refitted before each season on Sackmann
tour-level rounds 1-2 dated before it:
  base      the current model: overall Elo, K = 250 / (n + 5) ** 0.4
  K         K scale tuned
  MOV       margin of victory: update x (1 + mov x (game share - 0.25))
  decay     inactivity: after a 60-day gap, ratings shrink toward 1500 by exp(-decay x years)
  surface   rating = w x surface Elo + (1 - w) x overall Elo
  tuned     K, MOV, decay and w tuned together
  +fatigue  tuned + sets played in the 10 days before the match (both players)
  +serve    tuned + a serve/return points model (shrunk EW serve and return points won, iid
            points -> match probability)
  +both     tuned + fatigue + serve
Every tuned parameter is picked walk-forward: for season S, by log loss on Sackmann tour-level
rounds 1-2 in seasons S-3..S-1. Evaluation: the priced, Sackmann-resolved DK matches of season S.
Betting: a side at DK's pre-match price when model p x odds - 1 >= x, x chosen on earlier seasons.
Aggregates only; odds data never leave the machine.
"""

from __future__ import annotations

import argparse
import itertools
import re
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

from . import dk_history as dh
from . import dk_study as ds
from . import elo, model, sackmann, seeds

LN10_400 = np.log(10) / 400.0
K_GRID = (200.0, 250.0, 320.0)
MOV_GRID = (0.0, 0.5, 1.0)
DECAY_GRID = (0.0, 0.5, 1.0)
W_GRID = (0.0, 0.25, 0.5, 0.75)
EDGE_GRID = (0.0, 0.02, 0.05, 0.10)
FIRST_FIT = 2015


# --- score parsing ----------------------------------------------------------------------------

def games_sets(score) -> tuple[int, int, int, int]:
    """'6-3 4-6 7-6(5)' -> (winner games, loser games, winner sets, loser sets)."""
    if not isinstance(score, str):
        return 0, 0, 0, 0
    gw = gl = sw = sl = 0
    for a, b in re.findall(r"(\d+)-(\d+)", score):
        a, b = int(a), int(b)
        gw, gl = gw + a, gl + b
        if a > b:
            sw += 1
        elif b > a:
            sl += 1
    return gw, gl, sw, sl


# --- rating engine --------------------------------------------------------------------------

def run(df: pd.DataFrame, keep: np.ndarray, k_scale: float = 250.0, mov: float = 0.0,
        decay: float = 0.0, keys=("winner_id", "loser_id")) -> dict:
    """Pre-match overall and surface ratings for the rows where `keep` is True (df in playing
    order). Same K-factor shape as upsets.elo (K = k_scale / (n + 5) ** 0.4)."""
    rating, s_rating = defaultdict(lambda: elo.START), defaultdict(lambda: elo.START)
    played, s_played = defaultdict(int), defaultdict(int)
    last: dict = {}
    n = len(df)
    out = {c: np.full(keep.sum(), np.nan) for c in ("e_w", "e_l", "s_w", "s_l", "n_w", "n_l")}
    pos = np.cumsum(keep) - 1
    walk = df["comment"].fillna("").str.lower().str.startswith("walk").to_numpy()
    tours, surf = df["tour"].to_numpy(), df["surface"].fillna("?").to_numpy()
    W, L = df[keys[0]].to_numpy(), df[keys[1]].to_numpy()
    days = (df["date"].to_numpy().astype("datetime64[D]").astype(np.int64))
    share = df["_share"].to_numpy()

    def shrink(p, d):
        if decay and p in last:
            gap = d - last[p]
            if gap > 60:
                f = np.exp(-decay * (gap - 60) / 365.0)
                rating[p] = elo.START + (rating[p] - elo.START) * f
                for s in ("Hard", "Clay", "Grass", "Carpet", "?"):
                    if (p, s) in s_rating:
                        s_rating[(p, s)] = elo.START + (s_rating[(p, s)] - elo.START) * f
        last[p] = d

    for i in range(n):
        w, l = (tours[i], W[i]), (tours[i], L[i])
        shrink(w, days[i])
        shrink(l, days[i])
        ws, ls_ = (w, surf[i]), (l, surf[i])
        if keep[i]:
            j = pos[i]
            out["e_w"][j], out["e_l"][j] = rating[w], rating[l]
            out["s_w"][j], out["s_l"][j] = s_rating[ws], s_rating[ls_]
            out["n_w"][j], out["n_l"][j] = played[w], played[l]
        if walk[i]:
            continue
        m = max(0.25, 1.0 + mov * (share[i] - 0.25)) if mov else 1.0
        e = elo.expected(rating[w], rating[l])
        rating[w] += k_scale / (played[w] + 5) ** 0.4 * (1 - e) * m
        rating[l] -= k_scale / (played[l] + 5) ** 0.4 * (1 - e) * m
        es = elo.expected(s_rating[ws], s_rating[ls_])
        s_rating[ws] += k_scale / (s_played[ws] + 5) ** 0.4 * (1 - es) * m
        s_rating[ls_] -= k_scale / (s_played[ls_] + 5) ** 0.4 * (1 - es) * m
        played[w] += 1
        played[l] += 1
        s_played[ws] += 1
        s_played[ls_] += 1
    return out


# --- extra features -------------------------------------------------------------------------

def fatigue(df: pd.DataFrame, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sets played by winner / loser of each row in `rows` in the 10 days before it: matches of
    other events that started in [date - 10 d, date), the same event's earlier main-draw rounds,
    and its qualifying (rows of the same tournament name and start date, round Q1-Q4; not QF)."""
    long = pd.concat([
        df[["winner_id", "tour", "date", "tourney_id", "tournament", "round", "round_idx", "_sets"]]
        .set_axis(["p", "tour", "date", "tid", "name", "round", "ri", "sets"], axis=1),
        df[["loser_id", "tour", "date", "tourney_id", "tournament", "round", "round_idx", "_sets"]]
        .set_axis(["p", "tour", "date", "tid", "name", "round", "ri", "sets"], axis=1)], ignore_index=True)
    by_event = long.groupby(["p", "tour", "date", "tid"])["sets"].sum().reset_index()
    by_day = by_event.groupby(["p", "tour", "date"])["sets"].sum()
    quali = long[long["round"].astype(str).str.fullmatch(r"Q\d")].groupby(["p", "tour", "name", "date"])["sets"].sum()
    main = long[long["ri"].notna()]
    out = []
    for side in ("winner_id", "loser_id"):
        t = df.loc[rows, [side, "tour", "date", "tourney_id", "tournament", "round_idx"]].reset_index(drop=True)
        t.columns = ["p", "tour", "date", "tid", "name", "ri"]
        tot = np.zeros(len(t))
        for d in range(1, 11):   # events that started 1-10 days earlier (other events by construction)
            key = pd.MultiIndex.from_arrays([t["p"], t["tour"], t["date"] - pd.Timedelta(days=d)])
            tot += by_day.reindex(key).fillna(0).to_numpy()
        key = pd.MultiIndex.from_arrays([t["p"], t["tour"], t["name"], t["date"]])
        tot += quali.reindex(key).fillna(0).to_numpy()
        same = t.reset_index().merge(main, on=["p", "tour", "tid"], suffixes=("", "_m"))
        same = same[same["ri_m"] < same["ri"]].groupby("index")["sets"].sum()
        tot += same.reindex(range(len(t))).fillna(0).to_numpy()
        out.append(tot)
    return out[0], out[1]


def serve_return(df: pd.DataFrame, keep: np.ndarray, halflife: float = 30.0, prior: float = 10.0):
    """Pre-match exponentially weighted serve and return points won (per player and tour, shrunk to
    the tour mean with `prior` pseudo-matches), for the kept rows. -> (spw_w, rpw_w, spw_l, rpw_l, mean_spw)."""
    a = 0.5 ** (1.0 / halflife)
    S, R, N = defaultdict(float), defaultdict(float), defaultdict(float)
    tours, W, L = df["tour"].to_numpy(), df["winner_id"].to_numpy(), df["loser_id"].to_numpy()
    w_spw = (df["w_1stWon"] + df["w_2ndWon"]) / df["w_svpt"]
    l_spw = (df["l_1stWon"] + df["l_2ndWon"]) / df["l_svpt"]
    ok = (df["w_svpt"] > 20) & (df["l_svpt"] > 20) & w_spw.between(0.2, 1) & l_spw.between(0.2, 1)
    mean = {t: float(pd.concat([w_spw[ok & (df["tour"] == t)], l_spw[ok & (df["tour"] == t)]]).mean())
            for t in df["tour"].unique()}
    ws, ls_, okv = w_spw.to_numpy(), l_spw.to_numpy(), ok.to_numpy()
    pos = np.cumsum(keep) - 1
    out = np.full((keep.sum(), 4), np.nan)

    def est(p, t):
        n = N[p]
        return ((S[p] + prior * mean[t]) / (n + prior), (R[p] + prior * (1 - mean[t])) / (n + prior))

    for i in range(len(df)):
        t = tours[i]
        w, l = (t, W[i]), (t, L[i])
        if keep[i]:
            sw, rw = est(w, t)
            sl, rl = est(l, t)
            out[pos[i]] = (sw, rw, sl, rl)
        if okv[i]:
            for p, sp, rp in ((w, ws[i], 1 - ls_[i]), (l, ls_[i], 1 - ws[i])):
                S[p], R[p], N[p] = a * S[p] + sp, a * R[p] + rp, a * N[p] + 1
    mean_rows = np.array([mean[t] for t in tours[keep]])
    return out[:, 0], out[:, 1], out[:, 2], out[:, 3], mean_rows


def _game(p):
    """P(server holds) with point-win probability p (iid points)."""
    q = 1 - p
    deuce = p * p / (p * p + q * q)
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * deuce


def _tiebreak(pa, pb, n=7):
    """P(A wins a tiebreak); A serves the first point (approximate, by simulation of the
    alternating serve pattern with a dynamic programme)."""
    pa, pb = np.asarray(pa, float), np.asarray(pb, float)
    size = 16
    P = np.zeros((size, size) + pa.shape)
    P[0, 0] = 1.0
    win = np.zeros(pa.shape)
    for k in range(2 * size - 2):
        for i in range(max(0, k - size + 1), min(k, size - 1) + 1):
            j = k - i
            if j >= size:
                continue
            cur = P[i, j]
            if not np.any(cur):
                continue
            if (i >= n and i - j >= 2) or (j >= n and j - i >= 2):
                continue
            # serve: A serves point 0, then B, B, A, A, ...
            a_serves = ((k + 1) // 2) % 2 == 0
            p = pa if a_serves else 1 - pb
            if i + 1 < size:
                P[i + 1, j] += cur * p
            if j + 1 < size:
                P[i, j + 1] += cur * (1 - p)
    for i in range(size):
        for j in range(size):
            if i >= n and i - j >= 2:
                win += P[i, j]
    # long tiebreaks beyond the grid: split by the deuce formula at equal scores
    tot = sum(P[i, j] for i in range(size) for j in range(size)
              if (i >= n and i - j >= 2) or (j >= n and j - i >= 2))
    rest = np.clip(1 - tot, 0, 1)
    d = pa * (1 - pb) / (pa * (1 - pb) + (1 - pa) * pb)
    return win + rest * d


def match_prob(pa, pb, best_of):
    """P(A wins the match) when A wins a point on serve with pa and B with pb (iid points)."""
    ga, gb = _game(np.asarray(pa, float)), _game(np.asarray(pb, float))
    tb = _tiebreak(pa, pb)
    # set: dynamic programme over games, A serves first game
    size = 8
    P = np.zeros((size, size) + ga.shape)
    P[0, 0] = 1.0
    for k in range(12):
        for i in range(0, min(k, 6) + 1):
            j = k - i
            if j > 6 or i > 6:
                continue
            if (i == 6 and j <= 4) or (j == 6 and i <= 4) or i == 7 or j == 7:
                continue
            if i == 6 and j == 6:
                continue
            cur = P[i, j]
            hold = ga if k % 2 == 0 else 1 - gb
            P[i + 1, j] += cur * hold
            P[i, j + 1] += cur * (1 - hold)
    s = (P[6, 0] + P[6, 1] + P[6, 2] + P[6, 3] + P[6, 4] + P[7, 5] + P[6, 6] * tb)
    sets_to_win = np.where(np.asarray(best_of) == 5, 3, 2)
    out = np.empty_like(s)
    for need in (2, 3):
        m = sets_to_win == need
        if not np.any(m):
            continue
        x = s[m]
        tot = np.zeros_like(x)
        for lost in range(need):
            from math import comb
            tot += comb(need - 1 + lost, lost) * x ** need * (1 - x) ** lost
        out[m] = tot
    return out


# --- evaluation -----------------------------------------------------------------------------

def logit(p):
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p))


def fit_sym(X: np.ndarray, y_one: np.ndarray | None = None) -> model.Logit:
    """Symmetric logistic: each match in both orientations (features negate, label flips)."""
    return model.fit(np.vstack([X, -X]), np.r_[np.ones(len(X)), np.zeros(len(X))], l2=1.0)


def features(base: dict, w: float, bo5: np.ndarray, extra: list[np.ndarray]) -> np.ndarray:
    """Winner-oriented features: blended rating logit, x best-of-5, plus extras."""
    d = w * (base["s_w"] - base["s_l"]) + (1 - w) * (base["e_w"] - base["e_l"])
    z = d * LN10_400
    return np.column_stack([z, z * bo5] + extra)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    ap.add_argument("--cache", type=Path, default=dh.CACHE)
    ap.add_argument("--other-from", default="2024-01-01")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dump", type=Path, default=None, help="pickle the frame and predictions (local only)")
    a = ap.parse_args(argv)
    text = study(a.sackmann, a.cache, a.other_from, a.dump)
    print(text)
    if a.out:
        a.out.write_text(text)


def study(root: Path, cache: Path, other_from: str, dump: Path | None = None) -> str:
    sack = sackmann.load(root, start=1990, lower=True)
    gs = np.array([games_sets(s) for s in sack["score"]])
    tot = np.maximum(gs[:, 0] + gs[:, 1], 1)
    sack["_share"] = (gs[:, 0] - gs[:, 1]) / tot
    sack["_sets"] = gs[:, 2] + gs[:, 3]
    sack_elo = elo.add_elo(sack, keys=("winner_id", "loser_id"))
    hs = {**dh.HIST_START, "other": pd.Timestamp(other_from)}
    t = dh.tournaments(sack, dh._keys(), hist_start=hs)
    priced = dh.collect(t, sack_elo, 24.0, root=cache)
    f = ds.frame(priced, sack_elo).dropna(subset=["p_pin"])
    f = f[~f["void"].astype(bool)].reset_index(drop=True)

    tour_r12 = (sack["level_group"].isin(seeds.LEVELS) & (sack["round_idx"] <= 2) & ~sack["void"]
                & (sack["season"] >= FIRST_FIT - 3)).to_numpy()
    keep = tour_r12.copy()
    keep[f["sack_row"].to_numpy()] = True
    rows = np.flatnonzero(keep)
    pos = {r: i for i, r in enumerate(rows)}
    fi = np.array([pos[r] for r in f["sack_row"]])
    meta = sack.loc[rows, ["season", "date", "best_of", "level_group", "round_idx", "void"]].reset_index(drop=True)
    bo5 = (meta["best_of"] == 5).to_numpy().astype(float)
    is_fit = tour_r12[rows]

    # ratings for every grid point
    runs = {}
    for kk, mv, dc in itertools.product(K_GRID, MOV_GRID, DECAY_GRID):
        runs[(kk, mv, dc)] = run(sack, keep, kk, mv, dc)
    fw, fl = fatigue(sack, rows)
    sw, rw, sl, rl, mean_spw = serve_return(sack, keep)
    pa = np.clip(mean_spw + (sw - mean_spw) - (rl - (1 - mean_spw)), 0.3, 0.95)
    pb = np.clip(mean_spw + (sl - mean_spw) - (rw - (1 - mean_spw)), 0.3, 0.95)
    p_sr = match_prob(pa, pb, meta["best_of"].fillna(3).to_numpy())
    fat = (fw - fl)
    srz = logit(p_sr)

    # dog orientation for the priced rows: winner-oriented feature x sign
    dog_is_w = f["upset"].to_numpy() == 1
    sign = np.where(dog_is_w, 1.0, -1.0)
    y_dog = f["upset"].to_numpy()

    variants = {
        "base": dict(grid=[(250.0, 0.0, 0.0, 0.0)], extra=[]),
        "K": dict(grid=[(k, 0.0, 0.0, 0.0) for k in K_GRID], extra=[]),
        "MOV": dict(grid=[(250.0, m, 0.0, 0.0) for m in MOV_GRID], extra=[]),
        "decay": dict(grid=[(250.0, 0.0, d, 0.0) for d in DECAY_GRID], extra=[]),
        "surface": dict(grid=[(250.0, 0.0, 0.0, w) for w in W_GRID], extra=[]),
        "tuned": dict(grid=[(k, m, d, w) for k, m, d, w in itertools.product(K_GRID, MOV_GRID, DECAY_GRID, W_GRID)], extra=[]),
        "+fatigue": dict(grid="tuned", extra=["fat"]),
        "+serve": dict(grid="tuned", extra=["sr"]),
        "+both": dict(grid="tuned", extra=["fat", "sr"]),
    }
    extra_cols = {"fat": fat, "sr": srz}
    seasons = sorted(f["season"].unique())
    res = {v: np.full(len(f), np.nan) for v in variants}
    chosen = {v: {} for v in variants}
    nmin = lambda r: np.minimum(r["n_w"], r["n_l"])  # noqa: E731
    for S in seasons:
        tr = is_fit & (meta["season"] < S).to_numpy() & (meta["season"] >= FIRST_FIT).to_numpy()
        tune = is_fit & (meta["season"] >= S - 3).to_numpy() & (meta["season"] < S).to_numpy()
        test = (f["season"] == S).to_numpy()
        tuned_pick = None
        for v, spec in variants.items():
            grid = variants["tuned"]["grid"] if spec["grid"] == "tuned" else spec["grid"]
            ex = [extra_cols[e] for e in spec["extra"]]
            best, best_ll = None, np.inf
            if spec["grid"] == "tuned" and tuned_pick is not None:
                cands = [tuned_pick]
            else:
                cands = grid
            for (kk, mv, dc, w) in cands:
                r = runs[(kk, mv, dc)]
                ok = tr & (nmin(r) >= 10)
                X = features(r, w, bo5, ex)
                cal = fit_sym(X[ok])
                tk = tune & (nmin(r) >= 10)
                ll = model.log_loss(np.ones(tk.sum()), cal.predict(X[tk])) if len(cands) > 1 else 0.0
                if ll < best_ll:
                    best, best_ll, best_cal, best_X = (kk, mv, dc, w), ll, cal, X
            if v == "tuned":
                tuned_pick = best
            chosen[v][S] = best
            Xd = best_X[fi[test]] * sign[test][:, None]
            res[v][test] = best_cal.predict(Xd)
    if dump is not None:
        pd.to_pickle({"f": f, "res": res, "chosen": chosen}, dump)
    return report(f, res, chosen, y_dog)


def report(f: pd.DataFrame, res: dict, chosen: dict, y: np.ndarray) -> str:
    p_pin = f["p_pin"].to_numpy()
    lines = ["# Elo upgrades vs Pinnacle (walk-forward by season)", "",
             "Generated by `python -m upsets.elo_plus`. Matches: priced, Sackmann-resolved DK matches "
             "(rounds 1–2, not void, Pinnacle quoted), seasons as listed. p = probability the DK "
             "underdog wins. Lower log loss is better.", "",
             "## Log loss on the same matches", "",
             "| Variant | Matches | Log loss | vs Pinnacle | vs current Elo |", "|---|---|---|---|---|",
             f"| Pinnacle (de-vigged) | {len(f):,} | {model.log_loss(y, p_pin):.4f} | — | — |",
             f"| DraftKings (de-vigged) | {len(f):,} | {model.log_loss(y, f['p_dk'].to_numpy()):.4f} | "
             f"{model.log_loss(y, f['p_dk'].to_numpy()) - model.log_loss(y, p_pin):+.4f} | — |"]
    base = model.log_loss(y, res["base"])
    for v, p in res.items():
        ll = model.log_loss(y, p)
        lines.append(f"| {v} | {len(f):,} | {ll:.4f} | {ll - model.log_loss(y, p_pin):+.4f} | {ll - base:+.4f} |")
    lines += ["", "Per season (log loss − Pinnacle's):", "",
              "| Season | Matches | " + " | ".join(res) + " |", "|---|---|" + "---|" * len(res)]
    for S, g in f.groupby("season"):
        m = (f["season"] == S).to_numpy()
        lp = model.log_loss(y[m], p_pin[m])
        lines.append(f"| {S} | {m.sum():,} | " + " | ".join(
            f"{model.log_loss(y[m], res[v][m]) - lp:+.4f}" for v in res) + " |")
    lines += ["", "Parameters chosen (k, mov, decay, w) per season:", "",
              "| Variant | " + " | ".join(str(s) for s in sorted(f["season"].unique())) + " |",
              "|---|" + "---|" * f["season"].nunique()]
    for v, c in chosen.items():
        lines.append(f"| {v} | " + " | ".join(str(c[s]) for s in sorted(c)) + " |")
    lines += ["", "## Betting at DK on the model's edge (walk-forward)", "", *betting(f, res)]
    return "\n".join(lines) + "\n"


def betting(f: pd.DataFrame, res: dict) -> list[str]:
    """Both sides: bet side s when p_model(s) x DK odds(s) - 1 >= x; x chosen on earlier seasons
    (best P&L with >= 30 bets). CLV = DK odds x Pinnacle's p at the same (closing) snapshot - 1."""
    out = ["| Variant | OOS bets | Realized ROI (95% CI) | CLV vs Pinnacle | x chosen per season |",
           "|---|---|---|---|---|"]
    for v, p in res.items():
        long = pd.concat([
            pd.DataFrame({"m": f.index, "season": f["season"], "p": p, "odds": f["odds_dog_dk"],
                          "pin": f["p_pin"], "win": f["upset"]}),
            pd.DataFrame({"m": f.index, "season": f["season"], "p": 1 - p, "odds": f["odds_fav_dk"],
                          "pin": 1 - f["p_pin"], "win": 1 - f["upset"]})], ignore_index=True)
        long["edge"] = long["p"] * long["odds"] - 1
        long["pnl"] = np.where(long["win"] == 1, long["odds"] - 1, -1.0)
        long["clv"] = long["pin"] * long["odds"] - 1
        picked, xs = [], []
        seasons = sorted(long["season"].unique())
        for i, S in enumerate(seasons):
            if i == 0:
                continue
            prior = long[long["season"] < S]
            best, bp = None, -np.inf
            for x in EDGE_GRID:
                sel = prior[prior["edge"] >= x]
                if len(sel) >= 30 and sel["pnl"].sum() > bp:
                    best, bp = x, sel["pnl"].sum()
            xs.append("—" if best is None else f"{best:.0%}")
            if best is not None:
                picked.append(long[(long["season"] == S) & (long["edge"] >= best)])
        oos = pd.concat(picked) if picked else long.iloc[:0]
        if len(oos):
            g = oos.groupby("m")["pnl"].agg(["sum", "size"])
            rng = np.random.default_rng(0)
            idx = rng.integers(0, len(g), size=(2000, len(g)))
            boots = g["sum"].to_numpy()[idx].sum(1) / g["size"].to_numpy()[idx].sum(1)
            lo, hi = np.percentile(boots, [2.5, 97.5])
            out.append(f"| {v} | {len(oos):,} | {oos['pnl'].mean():+.1%} ({lo:+.1%} to {hi:+.1%}) | "
                       f"{oos['clv'].mean():+.1%} | {', '.join(xs)} |")
        else:
            out.append(f"| {v} | 0 | — | — | {', '.join(xs)} |")
    return out


if __name__ == "__main__":
    main()
