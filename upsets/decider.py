"""The penultimate-set theory at Kalshi's in-play price: at the start of a deciding set, buy the
player who won the penultimate set (the one who just levelled).

    python -m upsets.decider --data data/processed/kalshi_g0 --raw data/raw/kalshi \
        --sets data/processed/kalshi_g0/sets.parquet [--out reports/upsets_decider.md]

Inputs: matches + quotes (schema.py), a `sets` table (match_id, set_no, close_time = when the
set ended, winner_side A/B) and milestones (best_of; same cached bulk listing as kalshi_preview).
Decider start = close_time of set N-1 when the match reached its final set (sets 1..N-1 level).
Price = the last quote per side at or before decider start + `offset_s` (default 90 s, inside the
set break; sensitivity at 0 / 60 / 180 s), dropped if older than `max_age_s` (300). The bet buys
`contracts` of the penultimate-set winner at the ask with Kalshi's taker fee (0c and 1c slippage)
and settles at settle_a/settle_b. The other side is reported for comparison. No threshold is
fitted, so there is nothing to walk forward; report the price bands as diagnostics only.
Pre-match favourite = the side with the higher closing pre-match ask (kalshi_preview).
Guard: a decider must start 15-180 min before the match's close (else its set close time is
wrong or a batch close), and a decider start shared by >= 2 matches is a batch close; both
are excluded and counted.
Aggregates only (Kalshi data stays private).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from swinglock.config import kalshi_fees
from swinglock.locks import buy_cost

from . import kalshi_preview as kp

OFFSETS = (0, 60, 90, 180)
PRICE_BANDS = (0.0, 0.2, 0.35, 0.5, 0.65, 0.8, 1.0)
SERIES_TOUR = {"KXATPMATCH": "ATP", "KXWTAMATCH": "WTA", "KXATPCHALLENGERMATCH": "ATP Challenger",
               "KXWTACHALLENGERMATCH": "WTA 125", "KXITFMATCH": "ITF men", "KXITFWMATCH": "ITF women"}


def deciders(sets: pd.DataFrame, best_of: pd.Series | None = None) -> pd.DataFrame:
    """Matches that reached a deciding set: match_id, best_of, n_sets, pen_side (winner of set
    N-1), decider_start (its close_time). best_of per match_id if known; otherwise inferred
    from a level score after N-1 sets with N odd (3 or 5)."""
    s = sets.dropna(subset=["winner_side"]).sort_values(["match_id", "set_no"])
    rows = []
    for mid, g in s.groupby("match_id", sort=False):
        sides = list(g["winner_side"])
        if list(g["set_no"]) != list(range(1, len(g) + 1)):
            continue  # missing a set: can't tell the score
        bo = best_of.get(mid) if best_of is not None else None
        bo = int(bo) if bo is not None and bo == bo else None
        n_known = len(sides)
        # the decider is set N = best_of; we need sets 1..N-1 (set N may still be missing/ongoing)
        n = bo if bo else (n_known if n_known in (3, 5) else n_known + 1)
        if n not in (3, 5) or n_known < n - 1:
            continue
        first = sides[: n - 1]
        if first.count("A") != first.count("B"):
            continue  # not level after N-1 sets: no decider
        rows.append({"match_id": mid, "best_of": n, "n_sets": n_known, "pen_side": first[-1],
                     "decider_start": g["close_time"].iloc[n - 2]})
    return pd.DataFrame(rows, columns=["match_id", "best_of", "n_sets", "pen_side", "decider_start"])


def match_end(matches: pd.DataFrame, quotes: pd.DataFrame) -> pd.Series:
    """match_id -> when the match ended: the market's close_time, else its last quote."""
    last = quotes.groupby("match_id")["ts"].max()
    if "close_time" not in matches:
        return last
    end = pd.to_datetime(matches.set_index("match_id")["close_time"], utc=True)
    ids = last.index.union(end.index)
    return end.reindex(ids).where(lambda x: x.notna(), last.reindex(ids))


def guard(dec: pd.DataFrame, end: pd.Series, min_min: float = 15, max_min: float = 180) -> pd.DataFrame:
    """Plausibility of each decider start: the decider must last min_min..max_min until the match
    close (start after or just before the close = a bad set close time; > 3 h = a stale or
    batch close), and a decider_start shared by >= 2 matches is a batch close. Adds too_short,
    too_long, shared, ok."""
    d = dec.copy()
    left = (d["match_id"].map(end) - d["decider_start"]).dt.total_seconds() / 60
    d["too_short"] = left < min_min
    d["too_long"] = left > max_min
    d["shared"] = d.groupby(d["decider_start"].dt.floor("s"))["match_id"].transform("nunique") >= 2
    d["ok"] = ~(d["too_short"] | d["too_long"] | d["shared"]) & left.notna()
    return d


def price_at(dec: pd.DataFrame, quotes: pd.DataFrame, offset_s: float, max_age_s: float = 300) -> pd.DataFrame:
    """Last ask per side at or before decider_start + offset_s, no older than max_age_s."""
    q = quotes[quotes["match_id"].isin(dec["match_id"])][["ts", "match_id", "side", "ask"]]
    q = q.merge(dec[["match_id", "decider_start"]], on="match_id")
    t = q["decider_start"] + pd.Timedelta(seconds=offset_s)
    q = q[(q["ts"] <= t) & (q["ts"] >= t - pd.Timedelta(seconds=max_age_s))].dropna(subset=["ask"])
    last = q.sort_values("ts").groupby(["match_id", "side"]).tail(1)
    w = last.pivot(index="match_id", columns="side", values="ask").reindex(columns=["A", "B"])
    return w.rename(columns={"A": "ask_a", "B": "ask_b"}).reset_index()


def build(matches: pd.DataFrame, quotes: pd.DataFrame, sets: pd.DataFrame, details: pd.DataFrame,
          cfg: dict, offset_s: float = 90, max_age_s: float = 300, contracts: float = 100,
          prematch_age_h: float = 3.0) -> pd.DataFrame:
    """One row per decider with a price: bet on the penultimate-set winner (pen_*) and on the
    other side (oth_*), pre-match favourite flag, tour, price band."""
    bo = pd.to_numeric(details.set_index("match_id")["best_of"], errors="coerce") if len(details) else None
    dec = deciders(sets, bo)
    m = matches.set_index("match_id")
    dec = dec[dec["match_id"].isin(m.index)]
    dec = guard(dec, match_end(matches, quotes))
    dec = dec[dec["ok"]]
    px = price_at(dec, quotes, offset_s, max_age_s)
    d = dec.merge(px, on="match_id", how="inner").dropna(subset=["ask_a", "ask_b"], how="all")
    if not len(d):
        return d
    pre = kp.closing_quotes(matches[matches["match_id"].isin(d["match_id"])], quotes, prematch_age_h)
    d = d.merge(pre.rename(columns={"ask_a": "pre_a", "ask_b": "pre_b"}), on="match_id", how="left")
    mm = m.loc[d["match_id"]]
    d["series"] = mm["series"].to_numpy() if "series" in mm else pd.NA
    d["tour"] = d["series"].map(SERIES_TOUR).fillna(pd.Series(mm["tier"].to_numpy(), index=d.index))
    d["month"] = pd.to_datetime(d["decider_start"]).dt.strftime("%Y-%m")
    pen_a = d["pen_side"] == "A"
    settle_a, settle_b = mm["settle_a"].to_numpy(), mm["settle_b"].to_numpy()
    d["pen_ask"] = np.where(pen_a, d["ask_a"], d["ask_b"])
    d["oth_ask"] = np.where(pen_a, d["ask_b"], d["ask_a"])
    d["pen_pay"] = np.where(pen_a, settle_a, settle_b)
    d["oth_pay"] = np.where(pen_a, settle_b, settle_a)
    d["pen_won"] = (d["pen_pay"] == 1.0).astype(int)
    pre_pen = np.where(pen_a, d["pre_a"], d["pre_b"])
    pre_oth = np.where(pen_a, d["pre_b"], d["pre_a"])
    d["pen_prematch"] = np.where(np.isnan(pre_pen) | np.isnan(pre_oth), "unknown",
                                 np.where(pre_pen > pre_oth, "favourite",
                                          np.where(pre_pen < pre_oth, "underdog", "even")))
    fees = {}
    for side in ("pen", "oth"):
        for slip in (0.0, 0.01):
            tag = f"{side}_{round(slip * 100)}c"
            cost = []
            for ask, ft, mult in zip(d[f"{side}_ask"], mm["fee_type"], mm["fee_multiplier"]):
                if ask != ask:
                    cost.append(np.nan)
                    continue
                if (ft, mult) not in fees:
                    fees[(ft, mult)] = kalshi_fees(cfg, ft, mult)
                cost.append(buy_cost(ask, contracts, fees[(ft, mult)], slip))
            d[f"cost_{tag}"] = cost
            d[f"pnl_{tag}"] = contracts * d[f"{side}_pay"] - d[f"cost_{tag}"]
    d["pen_breakeven"] = d["cost_pen_0c"] / contracts
    d["band"] = pd.cut(d["pen_ask"], PRICE_BANDS)
    return d.reset_index(drop=True)


def roi(b: pd.DataFrame, side: str = "pen", tag: str = "0c") -> float:
    b = b.dropna(subset=[f"cost_{side}_{tag}"])
    c = b[f"cost_{side}_{tag}"].sum()
    return float(b[f"pnl_{side}_{tag}"].sum() / c) if c else np.nan


def roi_ci(b: pd.DataFrame, side: str = "pen", n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    b = b.dropna(subset=[f"cost_{side}_0c"])
    if len(b) < 2:
        return (np.nan, np.nan)
    pnl, cost = b[f"pnl_{side}_0c"].to_numpy(), b[f"cost_{side}_0c"].to_numpy()
    idx = np.random.default_rng(seed).integers(0, len(b), size=(n_boot, len(b)))
    r = pnl[idx].sum(axis=1) / cost[idx].sum(axis=1)
    return tuple(float(x) for x in np.percentile(r, [2.5, 97.5]))


def _pct(x) -> str:
    return "—" if x != x else f"{x:+.1%}"


HEAD = ["| Slice | Bets | Pen. winner won | Avg ask | Break-even (incl. fee) | ROI 0¢ | 95% CI | ROI 1¢ | Other side ROI 0¢ |",
        "|---|---|---|---|---|---|---|---|---|"]


def _row(name: str, b: pd.DataFrame) -> str:
    b = b.dropna(subset=["pen_ask"]) if "pen_ask" in b else b.iloc[:0]
    if not len(b):
        return f"| {name} | 0 | — | — | — | — | — | — | — |"
    lo, hi = roi_ci(b)
    return (f"| {name} | {len(b):,} | {b['pen_won'].mean():.1%} | {b['pen_ask'].mean():.1%} | "
            f"{b['pen_breakeven'].mean():.1%} | {_pct(roi(b))} | {_pct(lo)} to {_pct(hi)} | "
            f"{_pct(roi(b, 'pen', '1c'))} | {_pct(roi(b, 'oth'))} |")


def report(by_offset: dict[float, pd.DataFrame], default: float, n_dec: int, g: pd.DataFrame | None = None) -> str:
    d = by_offset[default]
    excl = ("" if g is None else
            f" Guard: {int(g['too_short'].sum())} decider starts too close to (or after) the match close "
            f"(< 15 min), {int(g['too_long'].sum())} more than 180 min before it, {int(g['shared'].sum())} "
            f"shared with another match (batch close); {int((~g['ok']).sum())} excluded.")
    lines = ["# Penultimate-set winner at Kalshi's decider price", "",
             f"{n_dec:,} matches reached a deciding set in the `sets` table.{excl} Bet = buy the player who won the "
             "penultimate set at the ask (+ Kalshi taker fee, 100 contracts) as of the decider start "
             f"+ {default:g} s; 'other side' = buying the opponent instead. 1-min candles; aggregates only.", "",
             "## Headline", "", *HEAD, _row("All", d)]
    for t in sorted(d["tour"].dropna().unique()):
        lines.append(_row(f"… {t}", d[d["tour"] == t]))
    for bo in sorted(d["best_of"].unique()):
        lines.append(_row(f"… best of {bo}", d[d["best_of"] == bo]))
    lines += ["", "## By pre-match role of the penultimate-set winner", "", *HEAD]
    for role in ("favourite", "underdog", "even", "unknown"):
        g = d[d["pen_prematch"] == role]
        if len(g):
            lines.append(_row(role, g))
    lines += ["", "## By price of the penultimate-set winner (diagnostic, no threshold fitted)", "", *HEAD]
    for band, g in d.groupby("band", observed=True):
        lines.append(_row(f"ask {band}", g))
    lines += ["", "## Timing sensitivity (quote as of decider start + offset)", "", *HEAD]
    for off, g in sorted(by_offset.items()):
        lines.append(_row(f"+{off:g} s", g))
    lines += ["", "## By month", "", "| Month | Bets | ROI 0¢ |", "|---|---|---|"]
    for mo, g in d.groupby("month"):
        lines.append(f"| {mo} | {g['pen_ask'].notna().sum()} | {_pct(roi(g))} |")
    return "\n".join(lines) + "\n"


def run(matches, quotes, sets, details, cfg, offsets=OFFSETS, default: float = 90, max_age_s: float = 300):
    bo = pd.to_numeric(details.set_index("match_id")["best_of"], errors="coerce") if len(details) else None
    dec = deciders(sets, bo)
    dec = dec[dec["match_id"].isin(matches["match_id"])]
    g = guard(dec, match_end(matches, quotes))
    by = {o: build(matches, quotes, sets, details, cfg, o, max_age_s) for o in sorted(set(offsets) | {default})}
    return report(by, default, len(dec), g), by


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=Path("data/processed/kalshi_g0"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw/kalshi"))
    ap.add_argument("--sets", type=Path, default=None, help="sets parquet (default <data>/sets.parquet)")
    ap.add_argument("--since", default=None)
    ap.add_argument("--offset-s", type=float, default=90)
    ap.add_argument("--max-age-s", type=float, default=300)
    ap.add_argument("--min-interval", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)

    from swinglock.collectors.kalshi import KalshiClient
    from swinglock.config import load_config

    matches = pd.read_parquet(a.data / "matches.parquet")
    quotes = pd.read_parquet(a.data / "quotes.parquet")
    sets = pd.read_parquet(a.sets or a.data / "sets.parquet")
    since = a.since or matches["scheduled_start"].min().strftime("%Y-%m-%dT00:00:00Z")
    client = KalshiClient(raw_dir=a.raw, min_interval_s=a.min_interval)
    details = kp.milestone_details(client, since)
    text, _ = run(matches, quotes, sets, details, load_config(), default=a.offset_s, max_age_s=a.max_age_s)
    print(text)
    print(f"[requests made: {client.requests_made}, cache hits: {client.cache_hits}]")
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text)


if __name__ == "__main__":
    main()
