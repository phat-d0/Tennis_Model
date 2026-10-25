"""Preview of the upset question on Kalshi prices: do underdogs win more often than their
pre-match price implies, after Kalshi's taker fee and the ask spread?

    python -m upsets.kalshi_preview --data data/processed/kalshi_g0 --raw data/raw/kalshi \
        [--out reports/upsets_kalshi_preview.md]

For each settled match: the last quote per side at or before the scheduled start (at most
`max_quote_age_h` old) is the closing price. The underdog is the side with the lower ask; the
bet buys `contracts` of it at the ask (+ slippage) with the series' taker fee, and settles at
settle_a/settle_b (fair prices for matches that never started). Round, best-of and tournament
come from Kalshi milestones (one bulk listing, cached). Kalshi has no rankings, so a strong
favourite (closing ask >= `strong_fav`) stands in for "seeded". No model and no fitting: this is
the "bet every underdog in the bucket" test. Prints aggregates only (Kalshi data stays private).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

from swinglock.config import kalshi_fees, load_config
from swinglock.locks import buy_cost

DOG_BINS = (0.0, 0.15, 0.25, 0.35, 0.45, 0.5)


def round_number(label) -> float:
    """'Round of 32' -> 32 (draw size); 'Round 2' / '2nd Round' -> -2 (round index, negative to
    tell them apart); qualifying / later rounds / unknown -> NaN."""
    if not isinstance(label, str):
        return np.nan
    s = label.lower()
    if "qualif" in s:
        return np.nan
    m = re.search(r"round of (\d+)", s)
    if m:
        return float(m.group(1))
    m = re.search(r"round (\d+)|(\d+)(?:st|nd|rd|th) round", s)
    if m:
        return -float(m.group(1) or m.group(2))
    return np.nan


def round_group(df: pd.DataFrame) -> pd.Series:
    """qualifying | early (first two main-draw rounds) | later | unknown, per match.

    'Round of N' labels are early when N is the tournament's largest or second-largest draw
    size seen (tournament = name + year); 'Round k' labels are early when k <= 2."""
    label = df["round"].fillna("")
    num = label.map(round_number)
    out = pd.Series("later", index=df.index)
    out[label == ""] = "unknown"
    out[label.str.lower().str.contains("qualif")] = "qualifying"
    key = df["tournament_name"].fillna("") + "|" + df["scheduled_start"].dt.year.astype(str)
    draw = num.where(num > 0)
    top_two = draw.groupby(key).transform(lambda s: s.dropna().drop_duplicates().nlargest(2).min()
                                          if s.notna().any() else np.nan)
    out[(draw.notna()) & (draw >= top_two)] = "early"
    out[(num < 0) & (num >= -2)] = "early"
    return out


def milestone_details(client, since: str | None) -> pd.DataFrame:
    """event_ticker -> round, best_of, tournament_name, gender from tennis milestones."""
    filt = {"type": "tennis_tournament_singles"}
    if since:
        filt["minimum_start_date"] = since
    rows = []
    for m in client.milestones(max_age_s=None, **filt):
        d = m.get("details") or {}
        for ev in {d.get("main_game_event_ticker"), *(m.get("primary_event_tickers") or [])}:
            if ev:
                rows.append({"match_id": ev, "round": d.get("round"), "best_of": d.get("best_of"),
                             "tournament_name": d.get("tournament_name"), "gender": d.get("gender")})
    return pd.DataFrame(rows, columns=["match_id", "round", "best_of", "tournament_name", "gender"]
                        ).drop_duplicates("match_id")


def closing_quotes(matches: pd.DataFrame, quotes: pd.DataFrame, max_age_h: float) -> pd.DataFrame:
    """One row per match: closing ask per side (last quote at/before scheduled start)."""
    start = matches.set_index("match_id")["scheduled_start"]
    q = quotes[["ts", "match_id", "side", "ask"]].copy()
    q["start"] = q["match_id"].map(start)
    q = q[(q["ts"] <= q["start"]) & (q["ts"] >= q["start"] - pd.Timedelta(hours=max_age_h))]
    last = q.sort_values("ts").groupby(["match_id", "side"]).tail(1)
    wide = last.pivot(index="match_id", columns="side", values="ask")
    return wide.rename(columns={"A": "ask_a", "B": "ask_b"}).reset_index()


def build_bets(matches: pd.DataFrame, quotes: pd.DataFrame, details: pd.DataFrame, cfg: dict,
               contracts: float = 100, max_age_h: float = 3.0) -> pd.DataFrame:
    m = matches.dropna(subset=["scheduled_start"]).merge(details, on="match_id", how="left")
    m = m.merge(closing_quotes(matches, quotes, max_age_h), on="match_id", how="inner")
    m = m.dropna(subset=["ask_a", "ask_b", "settle_a", "settle_b"])
    m = m[m["ask_a"] != m["ask_b"]].copy()
    dog_a = m["ask_a"] < m["ask_b"]
    m["dog_ask"] = m["ask_a"].where(dog_a, m["ask_b"])
    m["fav_ask"] = m["ask_b"].where(dog_a, m["ask_a"])
    m["dog_pay"] = m["settle_a"].where(dog_a, m["settle_b"])
    m["upset"] = (m["dog_pay"] == 1.0).astype(int)
    m["group"] = round_group(m)
    fees = {}
    for slip in (0.0, 0.01):
        cost = []
        for ask, ft, mult in zip(m["dog_ask"], m["fee_type"], m["fee_multiplier"]):
            key = (ft, mult)
            if key not in fees:
                fees[key] = kalshi_fees(cfg, ft, mult)
            cost.append(buy_cost(ask, contracts, fees[key], slip))
        tag = f"{round(slip * 100)}c"
        m[f"cost_{tag}"] = cost
        m[f"pnl_{tag}"] = contracts * m["dog_pay"] - m[f"cost_{tag}"]
    m["breakeven"] = m["cost_0c"] / contracts
    m["month"] = m["scheduled_start"].dt.strftime("%Y-%m")
    return m.reset_index(drop=True)


def roi(b: pd.DataFrame, tag: str = "0c") -> float:
    c = b[f"cost_{tag}"].sum()
    return float(b[f"pnl_{tag}"].sum() / c) if c else np.nan


def roi_ci(b: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    if len(b) < 2:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    pnl, cost = b["pnl_0c"].to_numpy(), b["cost_0c"].to_numpy()
    idx = rng.integers(0, len(b), size=(n_boot, len(b)))
    r = pnl[idx].sum(axis=1) / cost[idx].sum(axis=1)
    lo, hi = np.percentile(r, [2.5, 97.5])
    return float(lo), float(hi)


def _pct(x) -> str:
    return "—" if x != x else f"{x:+.1%}"


def _row(name: str, b: pd.DataFrame) -> str:
    lo, hi = roi_ci(b)
    return (f"| {name} | {len(b)} | {b['upset'].mean():.1%} | {b['dog_ask'].mean():.1%} | "
            f"{b['breakeven'].mean():.1%} | {_pct(roi(b))} | {_pct(lo)} to {_pct(hi)} | {_pct(roi(b, '1c'))} |"
            if len(b) else f"| {name} | 0 | — | — | — | — | — | — |")


HEAD = ["| Slice | Bets | Upset rate | Avg dog ask | Break-even (incl. fee) | ROI 0¢ | 95% CI | ROI 1¢ |",
        "|---|---|---|---|---|---|---|---|"]


def report(b: pd.DataFrame, strong_fav: float, n_matches: int) -> str:
    early = b[b["group"] == "early"]
    strong = early[early["fav_ask"] >= strong_fav]
    lines = ["# Upset preview on Kalshi prices (PRELIMINARY)", "",
             f"{n_matches:,} settled matches in; {len(b):,} with a closing ask on both sides before the "
             "scheduled start and a settlement. Bet = buy the underdog (lower ask) at the closing ask with "
             "Kalshi's taker fee; 1-min candles, no depth. Aggregates only.", "",
             "## Headline: early rounds, strong favourite", "", *HEAD,
             _row(f"Early rounds, fav ask ≥ {strong_fav:.2f} (all)", strong)]
    for tour in sorted(b["tier"].dropna().unique()):
        lines.append(_row(f"… {tour.upper()}", strong[strong["tier"] == tour]))
    lines.append(_row("Early rounds, any favourite", early))
    lines += ["", "By month (early rounds, strong favourite):", "", "| Month | Bets | ROI 0¢ |", "|---|---|---|"]
    for mo, g in strong.groupby("month"):
        lines.append(f"| {mo} | {len(g)} | {_pct(roi(g))} |")

    lines += ["", "## Calibration by tour, round group and underdog price", "", *HEAD]
    b = b.assign(bucket=pd.cut(b["dog_ask"], DOG_BINS))
    for (tour, grp), g in b.groupby(["tier", "group"]):
        lines.append(_row(f"**{tour.upper()} {grp} (all)**", g))
        for bucket, gb in g.groupby("bucket", observed=True):
            lines.append(_row(f"{tour.upper()} {grp} dog {bucket}", gb))

    lines += ["", "## Round labels seen (check the early/later mapping)", "", "| Label | Group | Matches |", "|---|---|---|"]
    lab = b.assign(label=b["round"].fillna("(none)")).groupby(["label", "group"]).size().sort_values(ascending=False)
    for (label, grp), n in lab.head(30).items():
        lines.append(f"| {label} | {grp} | {n} |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=Path("data/processed/kalshi_g0"))
    ap.add_argument("--raw", type=Path, default=Path("data/raw/kalshi"))
    ap.add_argument("--since", default=None, help="milestone minimum_start_date (ISO); default = earliest start")
    ap.add_argument("--strong-fav", type=float, default=0.75)
    ap.add_argument("--contracts", type=float, default=100)
    ap.add_argument("--max-quote-age-h", type=float, default=3.0)
    ap.add_argument("--min-interval", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    from swinglock.collectors.kalshi import KalshiClient

    matches = pd.read_parquet(args.data / "matches.parquet")
    quotes = pd.read_parquet(args.data / "quotes.parquet")
    since = args.since or matches["scheduled_start"].min().strftime("%Y-%m-%dT00:00:00Z")
    client = KalshiClient(raw_dir=args.raw, min_interval_s=args.min_interval)
    details = milestone_details(client, since)
    bets = build_bets(matches, quotes, details, load_config(), args.contracts, args.max_quote_age_h)
    text = report(bets, args.strong_fav, len(matches))
    print(text)
    print(f"[requests made: {client.requests_made}, cache hits: {client.cache_hits}]")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text)


if __name__ == "__main__":
    main()
