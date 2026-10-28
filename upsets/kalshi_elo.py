"""Elo vs Kalshi closing prices on early-round ATP/WTA matches, with a monthly walk-forward.

    python -m upsets.kalshi_elo --data data/processed/kalshi_g0 --raw data/raw/kalshi \
        --sackmann /path/to/tennis-sackmann-archive [--out reports/upsets_kalshi_elo.md]

Runs where the Kalshi data lives (the Data container); prints aggregates only.

1. Players: Kalshi names (`player_a/b`, e.g. "Jaime Faria") are matched to Sackmann player ids
   per tour by upsets/names.py, accent- and punctuation-insensitive: exact, then word order, then
   surname + first initial, then a close spelling, each only when unique.
2. Elo timeline: every Sackmann match (tour + qualifying/Challenger/ITF files) gets an estimated
   time (tournament start + its round's share of the event); a Sackmann match that is also a
   Kalshi match takes Kalshi's scheduled start (and its seeds/ranks come along). Kalshi matches
   with no Sackmann row update Elo only after Sackmann's last match, so nothing is counted twice.
   Ratings are strictly pre-match. Overall Elo only (Kalshi has no surface).
3. Model: P(A wins) = logistic(Elo logit, Elo logit x best-of-5), fitted on Sackmann tour-level
   rounds 1-2 that end before the Kalshi window starts (never on Kalshi data).
4. Bets: the early-round underdog (lower closing ask, as in kalshi_preview) is bought at the ask
   with Kalshi's taker fee when model p - break-even >= threshold. Fair-price settlements count.
5. Walk-forward: months in order; the threshold for month M is the one with the best P&L at 1c
   slippage on all earlier months (>= `min_select_bets` bets), so month M is out of sample.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import elo, kalshi_preview as kp, model, sackmann, seeds
from .names import match_names, name_key, norm_name, player_table  # noqa: F401 (name_key, norm_name re-exported)

TOURS = {"KXATPMATCH": "atp", "KXWTAMATCH": "wta"}
EDGE_GRID = (0.0, 0.02, 0.05, 0.08, 0.10, 0.15)
LN10_400 = np.log(10) / 400.0


# --- timeline --------------------------------------------------------------------------------

def _span_days(sack: pd.DataFrame) -> np.ndarray:
    return np.where(sack["draw_size"] >= 96, 13.0, 6.0)


def coverage_end(sack: pd.DataFrame) -> pd.Timestamp:
    """When Sackmann's data ends: the last tournament's start + its span."""
    return (sack["date"] + pd.to_timedelta(_span_days(sack), unit="D")).max()


def estimated_time(sack: pd.DataFrame) -> pd.Series:
    """Tournament start + the round's share of the event (13 days for draws >= 96, else 6).
    Round robin and unsized rounds (qualifying) go at the start."""
    first = 2.0 ** np.ceil(np.log2(sack["draw_size"].where(sack["draw_size"] >= 2)))
    rounds = np.log2(first).clip(lower=1)
    span = _span_days(sack)
    idx = sack["round_idx"].fillna(1.0).clip(lower=1)
    frac = ((idx - 1) / (rounds - 1).clip(lower=1)).clip(0, 1).fillna(0)
    return sack["date"] + pd.to_timedelta(frac * span, unit="D")


def round_monotone(s: pd.DataFrame, eps: pd.Timedelta = pd.Timedelta(microseconds=1)) -> pd.Series:
    """Times made non-decreasing in round order within each tournament: a row in round r is
    moved to just after the latest row of any earlier round (plus r x eps, so rounds never tie).
    Qualifying/round-robin rows (no round_idx) count as the first round; 'BR' goes last.
    Needed because joined rows carry Kalshi's real start while the rest are estimates: an
    unjoined R2 row must never sort before a joined R1 row of the same event."""
    order = sackmann._order_key(s)
    rank = order.groupby(s["tourney_id"]).rank(method="dense").astype(int)
    g = (pd.DataFrame({"t": s["tourney_id"], "r": rank, "time": s["time"]})
         .groupby(["t", "r"], sort=True)["time"].max().reset_index())
    g["prev"] = g.groupby("t")["time"].transform(lambda x: x.cummax().shift())
    prev = pd.MultiIndex.from_frame(pd.DataFrame({"t": s["tourney_id"], "r": rank}))
    floor = g.set_index(["t", "r"])["prev"].reindex(prev).to_numpy()
    floor = pd.Series(floor, index=s.index) + rank * eps
    return s["time"].where(floor.isna() | (s["time"] >= floor), floor)


def kalshi_matches(matches: pd.DataFrame, players: pd.DataFrame, tours: dict = TOURS) -> pd.DataFrame:
    """Kalshi matches of the `tours` series (series -> "atp"/"wta"; ATP/WTA tour-level by default) with
    player ids and the result (a_won: 1/0, NaN if fair-price)."""
    m = matches[matches["series"].isin(tours)].dropna(subset=["scheduled_start"]).copy()
    m["tour"] = m["series"].map(tours)
    since = m["scheduled_start"].min().tz_localize(None) - pd.Timedelta(days=730) if len(m) else None
    for side in ("a", "b"):
        r = match_names(m[f"player_{side}"], m["tour"], players, since)
        m[f"id_{side}"], m[f"how_{side}"] = r["id"], r["how"]
    sa = m["settle_a"]
    m["a_won"] = np.where(sa == 1.0, 1.0, np.where(sa == 0.0, 0.0, np.nan))
    m["start"] = m["scheduled_start"].dt.tz_convert("UTC").dt.tz_localize(None)
    return m.reset_index(drop=True)


def join_sackmann(km: pd.DataFrame, sack: pd.DataFrame, max_days: int = 21) -> pd.Series:
    """Kalshi row -> index of the Sackmann row with the same two players whose tournament
    started within `max_days` before the match (latest one); -1 if none."""
    pair = lambda a, b: np.where(a < b, a + "|" + b, b + "|" + a)  # noqa: E731
    k = km.dropna(subset=["id_a", "id_b"])
    kk = pd.DataFrame({"k": k.index, "tour": k["tour"], "start": k["start"],
                       "pair": pair(k["id_a"].astype(str), k["id_b"].astype(str))})
    s = sack[sack["date"] >= kk["start"].min() - pd.Timedelta(days=max_days)] if len(kk) else sack.iloc[:0]
    ss = pd.DataFrame({"s": s.index, "tour": s["tour"], "date": s["date"],
                       "pair": pair(s["winner_id"].astype(str), s["loser_id"].astype(str))})
    j = kk.merge(ss, on=["tour", "pair"])
    j = j[(j["date"] <= j["start"] + pd.Timedelta(days=1)) &
          (j["date"] >= j["start"] - pd.Timedelta(days=max_days))]
    j = j.sort_values("date").drop_duplicates("k", keep="last").drop_duplicates("s", keep="last")
    out = pd.Series(-1, index=km.index)
    out[j["k"].to_numpy()] = j["s"].to_numpy()
    return out


def timeline(sack: pd.DataFrame, km: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Combined Sackmann + Kalshi rows in time order with pre-match Elo; returns (rows, km)
    where km gains elo_a, elo_b, n_a, n_b, sack_row, seed_a, seed_b, rank_a, rank_b,
    best_of_s, sack_a_won."""
    s = sack.copy()
    s["time"] = estimated_time(s)
    s["wkey"], s["lkey"] = s["winner_id"].astype(str), s["loser_id"].astype(str)
    s["kalshi"] = pd.NA
    km = km.copy()
    km["sack_row"] = join_sackmann(km, sack)
    joined = km[km["sack_row"] >= 0]
    s.loc[joined["sack_row"].to_numpy(), "time"] = joined["start"].to_numpy()
    s.loc[joined["sack_row"].to_numpy(), "kalshi"] = joined.index.to_numpy()
    fixed = round_monotone(s)
    is_joined = s["kalshi"].notna()
    km.attrs["moved_joined"] = int((is_joined & (fixed != s["time"])).sum())
    s["time"] = fixed
    sack_end = coverage_end(sack)

    rest = km[km["sack_row"] < 0]
    # Unjoined Kalshi matches inside Sackmann's span are no-read: their time can't be ordered
    # safely against the event's unjoined Sackmann rows (estimated times), so they neither
    # update Elo nor get bet on.
    km["no_read"] = (km["sack_row"] < 0) & (km["start"] <= sack_end)
    key = lambda side: rest[f"id_{side}"].astype("string").fillna(  # noqa: E731
        "k:" + rest[f"player_{side}"].map(name_key))
    a_first = rest["a_won"].fillna(1.0) == 1.0
    k_rows = pd.DataFrame({
        "tour": rest["tour"], "surface": "?", "time": rest["start"],
        "wkey": key("a").where(a_first, key("b")), "lkey": key("b").where(a_first, key("a")),
        # Elo skips "Walkover" rows: fair-price settlements, and Kalshi-only rows that fall
        # inside Sackmann's span (a missed join must not count a result twice)
        "comment": np.where(rest["a_won"].isna() | (rest["start"] <= sack_end), "Walkover", "Completed"),
        "kalshi": rest.index,
    })
    rows = pd.concat([s[["tour", "surface", "time", "wkey", "lkey", "comment", "kalshi"]], k_rows],
                     ignore_index=True)
    rows["_src"] = np.arange(len(rows))
    rows = rows.sort_values(["time", "_src"], kind="stable").reset_index(drop=True)
    rows = elo.add_elo(rows, keys=("wkey", "lkey"))

    kr = rows.dropna(subset=["kalshi"]).set_index("kalshi")
    kr.index = kr.index.astype(int)
    kr = kr.reindex(km.index)
    a_is_w = kr["wkey"] == km["id_a"].astype("string").fillna("k:" + km["player_a"].map(name_key))
    km["elo_a"] = np.where(a_is_w, kr["w_elo"], kr["l_elo"])
    km["elo_b"] = np.where(a_is_w, kr["l_elo"], kr["w_elo"])
    km["n_a"] = np.where(a_is_w, kr["w_n"], kr["l_n"])
    km["n_b"] = np.where(a_is_w, kr["l_n"], kr["w_n"])
    sr = sack.reindex(km["sack_row"].where(km["sack_row"] >= 0))
    sr.index = km.index
    sw_is_a = (sr["winner_id"].astype("string") == km["id_a"].astype("string")).fillna(False)
    for col in ("seed", "rank"):
        km[f"{col}_a"] = np.where(sw_is_a, sr[f"w_{col}"], sr[f"l_{col}"])
        km[f"{col}_b"] = np.where(sw_is_a, sr[f"l_{col}"], sr[f"w_{col}"])
    km["best_of_s"] = sr["best_of"]
    km["sack_a_won"] = np.where(km["sack_row"] >= 0, sw_is_a.astype(float), np.nan)
    return rows, km


# --- model -----------------------------------------------------------------------------------

def _x(elo_diff: np.ndarray, bo5: np.ndarray) -> np.ndarray:
    z = np.asarray(elo_diff, float) * LN10_400
    return np.column_stack([z, z * np.asarray(bo5, float)])


def fit_calibration(sack_elo: pd.DataFrame, before: pd.Timestamp, from_season: int = 2015,
                    min_n: int = 10) -> model.Logit:
    """Fit P(win) on Elo logit (+ x best-of-5) using Sackmann tour-level rounds 1-2 dated before
    `before` (tournament start + 14 days < before, so no match in the fit is after it)."""
    d = sack_elo[sack_elo["level_group"].isin(seeds.LEVELS) & (sack_elo["round_idx"] <= 2) &
                 ~sack_elo["void"] & (sack_elo["season"] >= from_season) &
                 (sack_elo["date"] + pd.Timedelta(days=14) < before) &
                 (np.minimum(sack_elo["w_n"], sack_elo["l_n"]) >= min_n)]
    diff = (d["w_elo"] - d["l_elo"]).to_numpy()
    bo5 = (d["best_of"] == 5).to_numpy()
    if not len(d):
        raise ValueError(f"no Sackmann rounds 1-2 to fit the calibration on before {before}")
    X = np.vstack([_x(diff, bo5), _x(-diff, bo5)])  # both orientations: symmetric fit
    y = np.r_[np.ones(len(d)), np.zeros(len(d))]
    return model.fit(X, y, l2=1.0)


# --- bets and walk-forward -------------------------------------------------------------------

def add_model(bets: pd.DataFrame, km: pd.DataFrame, cal: model.Logit) -> pd.DataFrame:
    """Merge Elo/model columns onto kalshi_preview.build_bets output (one row per match)."""
    cols = ["match_id", "no_read", "elo_a", "elo_b", "n_a", "n_b", "id_a", "id_b", "sack_row", "seed_a",
            "seed_b", "rank_a", "rank_b", "best_of_s", "a_won", "sack_a_won"]
    b = bets.merge(km[cols], on="match_id", how="inner")
    bo = pd.to_numeric(b["best_of"], errors="coerce").fillna(b["best_of_s"])
    b["bo5"] = (bo == 5).astype(float)
    p_a = cal.predict(_x((b["elo_a"] - b["elo_b"]).to_numpy(), b["bo5"].to_numpy()))
    dog_a = b["ask_a"] < b["ask_b"]
    b["p_dog"] = np.where(dog_a, p_a, 1 - p_a)
    b["p_elo_dog"] = np.where(dog_a, 1 / (1 + 10 ** ((b["elo_b"] - b["elo_a"]) / 400)),
                              1 / (1 + 10 ** ((b["elo_a"] - b["elo_b"]) / 400)))
    b["p_mkt_dog"] = b["dog_ask"] / (b["dog_ask"] + b["fav_ask"])
    b["edge"] = b["p_dog"] - b["breakeven"]
    b["both_matched"] = b["id_a"].notna() & b["id_b"].notna()
    b["readable"] = b["both_matched"] & ~b["no_read"]
    b["min_n"] = np.minimum(b["n_a"], b["n_b"])
    b["seed_fav"] = np.where(dog_a, b["seed_b"], b["seed_a"])
    b["seed_dog"] = np.where(dog_a, b["seed_a"], b["seed_b"])
    return b


def walk_forward(b: pd.DataFrame, grid=EDGE_GRID, min_select_bets: int = 20,
                 first_test: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (out-of-sample bets, per-month table). Month i >= first_test uses the threshold
    with the highest P&L at 1c on months < i (needs >= min_select_bets bets); no eligible
    threshold -> the month is skipped (no bets)."""
    months = sorted(b["month"].unique())
    picked, rows = [], []
    for i, mo in enumerate(months):
        if i < first_test:
            continue
        prior = b[b["month"] < mo]
        best, best_pnl = None, -np.inf
        for t in grid:
            sel = prior[prior["edge"] >= t]
            if len(sel) >= min_select_bets and sel["pnl_1c"].sum() > best_pnl:
                best, best_pnl = t, sel["pnl_1c"].sum()
        test = b[(b["month"] == mo) & (b["edge"] >= best)] if best is not None else b.iloc[:0]
        rows.append({"month": mo, "threshold": best, "bets": len(test),
                     "pnl_0c": test["pnl_0c"].sum(), "pnl_1c": test["pnl_1c"].sum(),
                     "cost": test["cost_0c"].sum()})
        picked.append(test.assign(threshold=best))
    oos = pd.concat(picked, ignore_index=True) if picked else b.iloc[:0].assign(threshold=np.nan)
    return oos, pd.DataFrame(rows, columns=["month", "threshold", "bets", "pnl_0c", "pnl_1c", "cost"])


def gate(oos: pd.DataFrame, months: pd.DataFrame, min_bets: int = 30) -> dict:
    last4 = months.tail(4)
    pos = int((last4["pnl_1c"] > 0).sum())
    checks = {
        "bets >= %d" % min_bets: len(oos) >= min_bets,
        "OOS P&L > 0 at 0c": oos["pnl_0c"].sum() > 0,
        "OOS P&L > 0 at 1c": oos["pnl_1c"].sum() > 0,
        f">= 3 of last 4 months positive at 1c ({pos}/{len(last4)})": pos >= 3,
    }
    return {"pass": all(checks.values()), "checks": checks}


# --- report ----------------------------------------------------------------------------------

def _pct(x) -> str:
    return "—" if x != x else f"{x:+.1%}"


def _line(name: str, b: pd.DataFrame) -> str:
    if not len(b):
        return f"| {name} | 0 | — | — | — | — | — | — |"
    lo, hi = kp.roi_ci(b)
    return (f"| {name} | {len(b)} | {b['upset'].mean():.1%} | {b['p_dog'].mean():.1%} | "
            f"{b['breakeven'].mean():.1%} | {_pct(kp.roi(b))} | {_pct(lo)} to {_pct(hi)} | "
            f"{_pct(kp.roi(b, '1c'))} |")


HEAD = ["| Slice | Bets | Upset rate | Model p | Break-even | ROI 0¢ | 95% CI | ROI 1¢ |",
        "|---|---|---|---|---|---|---|---|"]


def _logloss(y, p) -> float:
    p = np.clip(np.asarray(p, float), 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def report(km: pd.DataFrame, b: pd.DataFrame, oos: pd.DataFrame, months: pd.DataFrame,
           g: dict, cal: model.Logit, min_n: int) -> str:
    n_k = len(km)
    both = km["id_a"].notna() & km["id_b"].notna()
    how = pd.concat([km["how_a"], km["how_b"]]).value_counts()
    joined = km["sack_row"] >= 0
    agree = (km.loc[joined & km["a_won"].notna(), "a_won"] ==
             km.loc[joined & km["a_won"].notna(), "sack_a_won"]).mean()
    early = b[(b["group"] == "early") & b["readable"] & (b["min_n"] >= min_n)]
    done = early[early["dog_pay"].isin([0.0, 1.0])]
    lines = [
        "# Elo vs Kalshi closing prices, early rounds (ATP + WTA)", "",
        "Bet = buy the underdog (lower closing ask) at the ask with Kalshi's taker fee, 100 contracts; "
        "1-min candles, no depth. Elo from Jeff Sackmann's match files (CC BY-NC-SA 4.0) carried "
        "forward with Kalshi results. Aggregates only.", "",
        "## Joins",
        f"- Kalshi ATP/WTA matches: {n_k:,}; both players matched to Sackmann: {both.sum():,} "
        f"({both.mean():.1%}). Name matches by method: "
        + ", ".join(f"{k} {v:,}" for k, v in how.items()) + ".",
        f"- Joined to a Sackmann row (real seeds/ranks): {joined.sum():,}; winner agrees with "
        f"Kalshi's settlement in {agree:.1%} of settled joined matches. Joined rows moved later "
        f"to keep round order within their event: {km.attrs.get('moved_joined', 0):,}.",
        f"- Early-round bets with both players matched and ≥ {min_n} prior matches each: {len(early):,} "
        f"(of {int((b['group'] == 'early').sum()):,} early-round matches with closing asks; "
        f"{int(((b['group'] == 'early') & b['no_read']).sum()):,} unjoined inside Sackmann's span "
        "are left out as no-read).",
        f"- Model: P(win) = logistic(Elo logit, Elo logit × best-of-5), coefficients fitted on "
        f"Sackmann rounds 1–2 before the Kalshi window: {np.round(cal.coef, 3).tolist()} (standardized).",
        "", "## Out-of-sample walk-forward (threshold on earlier months only)", "",
        f"**Gate: {'PASS' if g['pass'] else 'FAIL'}**  " + "; ".join(
            f"{k}: {'yes' if v else 'no'}" for k, v in g["checks"].items()), "", *HEAD,
        _line("OOS, all", oos)]
    for t in ("atp", "wta"):
        lines.append(_line(f"… {t.upper()}", oos[oos["tour"] == t]))
    lines += ["", "| Month | Threshold | Bets | P&L 0¢ | P&L 1¢ | ROI 0¢ |", "|---|---|---|---|---|---|"]
    for r in months.itertuples():
        thr = "—" if r.threshold is None or r.threshold != r.threshold else f"{r.threshold:.2f}"
        roi = r.pnl_0c / r.cost if r.cost else np.nan
        lines.append(f"| {r.month} | {thr} | {r.bets} | {r.pnl_0c:+.2f} | {r.pnl_1c:+.2f} | {_pct(roi)} |")
    lines += ["", "## Fixed thresholds over all months (in-sample, diagnostic)", "", *HEAD,
              _line("Every early underdog", early)]
    for t in EDGE_GRID:
        lines.append(_line(f"edge ≥ {t:.2f}", early[early["edge"] >= t]))
    lines += ["", "## Who prices better? (early rounds, settled 0/1)", "",
              "| Tour | Matches | Log loss: market (asks normalized) | Log loss: model | Upset rate | "
              "Market p(dog) | Model p(dog) |", "|---|---|---|---|---|---|---|"]
    for t, d in [("all", done), *((t.upper(), done[done["tour"] == t]) for t in ("atp", "wta"))]:
        if len(d):
            y = d["upset"].to_numpy()
            lines.append(f"| {t} | {len(d):,} | {_logloss(y, d['p_mkt_dog']):.4f} | "
                         f"{_logloss(y, d['p_dog']):.4f} | {y.mean():.1%} | "
                         f"{d['p_mkt_dog'].mean():.1%} | {d['p_dog'].mean():.1%} |")
    lines += ["", "Calibration by market underdog price:", "",
              "| Dog ask | Matches | Upset rate | Market p | Model p |", "|---|---|---|---|---|"]
    for bucket, d in done.groupby(pd.cut(done["dog_ask"], kp.DOG_BINS), observed=True):
        lines.append(f"| {bucket} | {len(d)} | {d['upset'].mean():.1%} | {d['p_mkt_dog'].mean():.1%} | "
                     f"{d['p_dog'].mean():.1%} |")
    seeded = early[early["seed_fav"].notna() & early["seed_dog"].isna()]
    lines += ["", "## Seeded favourite vs unseeded underdog (Sackmann overlap, real seeds)", "", *HEAD,
              _line("Every such underdog", seeded),
              _line("edge ≥ 0.05 (diagnostic)", seeded[seeded["edge"] >= 0.05])]
    return "\n".join(lines) + "\n"


def run(matches, quotes, details, sack_elo_src: pd.DataFrame, cfg: dict, min_n: int = 10,
        min_select_bets: int = 20, contracts: float = 100, max_age_h: float = 3.0,
        fit_from_season: int = 2015, fit_min_n: int = 10):
    """sack_elo_src: sackmann.load(...) output (no Elo yet). Returns (report text, parts)."""
    players = player_table(sack_elo_src)
    km = kalshi_matches(matches, players)
    _, km = timeline(sack_elo_src, km)
    window = km["start"].min()
    sack_elo = elo.add_elo(sack_elo_src, keys=("winner_id", "loser_id"))
    cal = fit_calibration(sack_elo, window, fit_from_season, fit_min_n)
    bets = kp.build_bets(matches[matches["series"].isin(TOURS)], quotes, details, cfg, contracts,
                         max_age_h)
    b = add_model(bets, km, cal)
    use = b[(b["group"] == "early") & b["readable"] & (b["min_n"] >= min_n)]
    oos, months = walk_forward(use, min_select_bets=min_select_bets)
    g = gate(oos, months)
    return report(km, b, oos, months, g, cal, min_n), dict(km=km, bets=b, oos=oos, months=months,
                                                          gate=g, cal=cal)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=Path("data/processed/kalshi_g0"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw/kalshi"))
    ap.add_argument("--sackmann", type=Path, required=True, help="tennis-sackmann-archive checkout")
    ap.add_argument("--since", default=None, help="milestone minimum_start_date (ISO)")
    ap.add_argument("--min-history", type=int, default=10)
    ap.add_argument("--min-select-bets", type=int, default=20)
    ap.add_argument("--min-interval", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    from swinglock.collectors.kalshi import KalshiClient
    from swinglock.config import load_config

    matches = pd.read_parquet(args.data / "matches.parquet")
    quotes = pd.read_parquet(args.data / "quotes.parquet")
    since = args.since or matches["scheduled_start"].min().strftime("%Y-%m-%dT00:00:00Z")
    client = KalshiClient(raw_dir=args.raw, min_interval_s=args.min_interval)
    details = kp.milestone_details(client, since)
    sack = sackmann.load(args.sackmann, start=1990, lower=True)
    text, _ = run(matches, quotes, details, sack, load_config(), args.min_history, args.min_select_bets)
    print(text)
    print(f"[requests made: {client.requests_made}, cache hits: {client.cache_hits}]")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)


if __name__ == "__main__":
    main()
