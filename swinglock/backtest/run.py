"""Backtest CLI: true-arb scan + swing-lock grid + breakdowns on collected quotes.

    python -m swinglock.backtest.run --data data/processed/kalshi --out reports/

Writes arb_episodes.csv, arb_by_match.csv, grid_metrics.csv, grid_trades.csv,
breakdowns.csv, grid_entries.csv, walkforward_folds.csv, walkforward_trades.csv, walkforward_gate.csv and
backtest_summary.md to --out. Exits cleanly (code 0) with a message
when the data directory has no matches/quotes yet.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..config import load_config
from ..schema import MATCH_COLUMNS, QUOTE_COLUMNS, conform, validate_quotes
from .align import align, staleness_s
from .arb import scan_arb
from .grid import KEYS, entry_diagnostics, grid_metrics, grid_trades
from .metrics import breakdown
from .swing import LOOKAHEAD_FILTERS, MODES, entry_filters, match_paths, settlement
from .walkforward import WalkForward, slip_label, walk_forward

CAVEATS = """\
- Quotes from candles are sampled ask levels with no depth: fills are assumed at the sampled
  ask in full size (optimistic), and opportunities that open and close between samples are
  missed (pessimistic). Arb dollar profit with unknown depth is for 1 contract.
- Fills are at ask + configured slippage with Kalshi taker fees rounded up per order; no
  queue position, latency or partial fills are modelled.
- Settlement time is each match's last aligned quote (capital/drawdown timing proxy).
- The best grid row is chosen in-sample; treat it as a hypothesis, not an expected return.
  The walk-forward section is the headline: rules chosen on earlier months only."""


def _fmt(v) -> str:
    if isinstance(v, float):
        return "" if pd.isna(v) else f"{v:.4g}"
    return str(v)


def md_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_(none)_"
    head = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "|" + "---|" * len(df.columns)
    body = ["| " + " | ".join(_fmt(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join([head, sep, *body])


def load(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """(matches, quotes) conformed to the schema, or None if the data isn't there yet."""
    mp, qp = data_dir / "matches.parquet", data_dir / "quotes.parquet"
    if not (mp.exists() and qp.exists()):
        return None
    matches = conform(pd.read_parquet(mp), MATCH_COLUMNS)
    quotes = conform(pd.read_parquet(qp), QUOTE_COLUMNS)
    if matches.empty or quotes.empty:
        return None
    validate_quotes(quotes)
    return matches, quotes


def walkforward_md(wf: WalkForward) -> list[str]:
    verdict = "PASS" if wf.passed else "FAIL: " + "; ".join(wf.reasons)
    lines = ["## Walk-forward gate (out of sample; the headline number)", "",
             f"- Verdict: **{verdict}**",
             "- Rule (mode, X, Y) chosen per fold on earlier months only (settled before the test month), "
             "then run unchanged on the test month. CI: match-level bootstrap of mean P&L per trade.", "",
             md_table(wf.gate.assign(slippage=wf.gate["slippage"].map(slip_label))), ""]
    if len(wf.folds):
        lines += [md_table(wf.folds), ""]
    return lines


def summary_md(data_dir, matches, quotes, aligned, episodes, by_match, grid, bd, stale, wf=None,
               entries=None, filters=None, arb_age=None) -> str:
    settled = sum(settlement(r) is not None for _, r in matches.iterrows())
    fair = int((matches["settle_a"].notna() & matches["settle_b"].notna()
                & ~matches["settle_a"].isin([0.0, 1.0])).sum())
    src = quotes["source"].value_counts(dropna=False).to_dict()
    lines = [
        "# Backtest summary", "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC from `{data_dir}`.", "",
        "## Data",
        f"- Matches: {len(matches)} ({settled} settled, {fair} at a fair price); quotes: {len(quotes)} rows, sources {src}",
        f"- Quote span: {quotes['ts'].min()} to {quotes['ts'].max()}",
        f"- Aligned observations: {len(aligned)} (as-of join, max staleness {stale:g}s)", "",
        "## True arb (buy both sides at once)",
    ]
    if len(aligned):
        frac = by_match["n_arb"].sum() / max(by_match["n_obs"].sum(), 1)
        lines += [
            f"- Episodes: {len(episodes)} in {(by_match['n_episodes'] > 0).sum()} of {len(by_match)} matches; "
            f"{frac:.2%} of observations in arb",
            f"- Median duration: {_fmt(float(episodes['duration_s'].median())) if len(episodes) else '-'}s; "
            f"sum of one-fill profits: ${episodes['profit'].sum():.2f}; "
            f"depth known for {int(episodes['depth_known'].sum())} of {len(episodes)}",
            f"- Leg-age filter (backtest.arb_max_leg_age_s): {_fmt(arb_age) if arb_age is not None else 'off'}; "
            f"median older-leg age at the best observation: "
            f"{_fmt(float(episodes['leg_age_s'].median())) if len(episodes) else '-'}s", "",
            md_table(episodes.sort_values("profit", ascending=False).head(10)), "",
        ]
    if wf is not None:
        lines += walkforward_md(wf)
    lines += ["## Swing-lock grid, in sample (top 10 by total P&L)", ""]
    cols = [*KEYS, "n_trades", "lock_rate", "avg_locked_pnl", "avg_unlocked_loss", "total_pnl",
            "avg_return", "hit_rate", "max_drawdown", "peak_capital"]
    traded = grid[grid["n_trades"] > 0].sort_values("total_pnl", ascending=False)
    lines += [md_table(traded[cols].head(10)), ""]
    filt = ", ".join(f"{k}={_fmt(v)}" for k, v in (filters or {}).items()) or "none"
    look = [k for k in (filters or {}) if k in LOOKAHEAD_FILTERS]
    lines += [f"Entry filters: {filt}" + (f" (**{', '.join(look)} uses lookahead: diagnostic only**)" if look else ""),
              ""]
    if entries is not None and len(traded):
        top = traded[KEYS].head(10).merge(entries, on=KEYS, how="left")
        lines += ["## Where entries happen (same rules; ask in $, mtc = minutes entry -> last observation)", "",
                  md_table(top), ""]
    if len(traded):
        best = traded.iloc[0]
        sel = (bd["mode"] == best["mode"]) & (bd["x"] == best["x"]) & (bd["y"] == best["y"])
        lines += [f"## Breakdown for mode={best['mode']}, X={best['x']:g}, Y={best['y']:g}", "",
                  md_table(bd.loc[sel, ["dimension", "value", *cols[3:]]]), ""]
    lines += ["## Caveats", CAVEATS, ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default="data/processed/kalshi", type=Path)
    ap.add_argument("--out", default="reports", type=Path)
    ap.add_argument("--config", default=None)
    ap.add_argument("--modes", nargs="+", default=list(MODES), choices=MODES)
    args = ap.parse_args(argv)

    loaded = load(args.data)
    if loaded is None:
        print(f"No backtest input in {args.data}: need non-empty matches.parquet and quotes.parquet "
              "(the collector hasn't produced them yet). Nothing to do.", file=sys.stderr)
        return 0
    matches, quotes = loaded
    cfg = load_config(args.config)
    stale = staleness_s(cfg)

    aligned = align(quotes, matches, stale)
    episodes, by_match = scan_arb(aligned, matches, cfg)
    paths = match_paths(aligned, matches, cfg)
    trades = grid_trades(paths, cfg, args.modes)
    grid = grid_metrics(trades, cfg, args.modes)
    bd = breakdown(trades, keys=KEYS)
    entries = entry_diagnostics(trades, cfg, args.modes)
    wf = walk_forward(paths, cfg, args.modes)

    args.out.mkdir(parents=True, exist_ok=True)
    for name, df in [("arb_episodes", episodes), ("arb_by_match", by_match), ("grid_metrics", grid),
                     ("grid_trades", trades), ("breakdowns", bd), ("grid_entries", entries),
                     ("walkforward_folds", wf.folds),
                     ("walkforward_trades", wf.trades), ("walkforward_gate", wf.gate)]:
        df.to_csv(args.out / f"{name}.csv", index=False)
    md = summary_md(args.data, matches, quotes, aligned, episodes, by_match, grid, bd, stale, wf,
                    entries, entry_filters(cfg), (cfg.get("backtest") or {}).get("arb_max_leg_age_s"))
    (args.out / "backtest_summary.md").write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
