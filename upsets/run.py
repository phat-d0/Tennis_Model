"""Run the upset study and write a markdown report.

    python -m upsets.run --data-dir data/raw/tennis_data [--book b365] [--tours atp,wta]

Data: tennis-data.co.uk yearly files under <data-dir>/atp/ and <data-dir>/wta/
(python -m upsets.download). Settings: the `upsets:` block in config.yaml.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from swinglock.config import load_config

from . import backtest, elo, features, load


def _pct(x: float) -> str:
    return "—" if x != x else f"{x:+.1%}"


def _fmt_summary(s: dict) -> str:
    if not s["bets"]:
        return "no bets"
    return (f"{s['bets']} bets ({s['wins']} won, {s['voids']} void), avg odds {s['avg_odds']:.2f}, "
            f"P&L {s['pnl']:+.1f}u, ROI {_pct(s['roi'])} (95% CI {_pct(s['roi_lo'])} to {_pct(s['roi_hi'])}), "
            f"max drawdown {s['max_dd']:.1f}u")


def _season_table(df: pd.DataFrame, with_edge: bool) -> list[str]:
    head = "| Season | Bets | Won | ROI | P&L (u) |" + (" Edge ≥ |" if with_edge else "")
    sep = "|---|---|---|---|---|" + ("---|" if with_edge else "")
    lines = [head, sep]
    for _, r in df.iterrows():
        row = f"| {int(r['season'])} | {int(r['bets'])} | {int(r['wins'])} | {_pct(r['roi'])} | {r['pnl']:+.1f} |"
        if with_edge:
            row += f" {r['edge']:.0%} |"
        lines.append(row)
    return lines


def report(frame: pd.DataFrame, rule: backtest.Rule, test_seasons: list[int],
           haircuts: list[float], tours: list[str]) -> str:
    lines = [f"# Early-round upset study ({', '.join(t.upper() for t in tours)})", "",
             f"Bet book: `{rule.bet_book}`. Filter: {'rounds 1–2' if rule.early_only else 'all rounds'}, "
             f"favourite ranked ≤ {rule.fav_rank_max}, underdog odds {rule.min_odds}–{rule.max_odds}, "
             f"both players ≥ {rule.min_history} prior matches. 1-unit flat stakes at closing odds; "
             "walkovers and retirements before a completed first set are void.", ""]

    lines += ["## Do underdogs win more often than the odds say?", "",
              "| Tour | Market prob of dog | Matches | Upset rate | Market (de-vigged) | Break-even | ROI betting all |",
              "|---|---|---|---|---|---|---|"]
    for _, r in backtest.calibration(frame, rule).iterrows():
        lines.append(f"| {r['tour'].upper()} | {r['bucket']} | {r['n']} | {r['upset_rate']:.1%} | "
                     f"{r['p_mkt']:.1%} | {r['breakeven']:.1%} | {r['roi_all']:+.1%} |")
    lines.append("")

    oos = {h: backtest.walk_forward(frame, test_seasons, rule, h) for h in haircuts}
    for h in haircuts:
        o = oos[h]
        if o.empty:
            lines += [f"No out-of-sample seasons at haircut {h:.0%} (not enough data).", ""]
            continue
        lines += [f"## Out of sample, odds haircut {h:.0%}", "",
                  f"- Model (market + Elo + rank): {_fmt_summary(backtest.summarize(o[o['bet_model']]))}",
                  f"- Market-only model: {_fmt_summary(backtest.summarize(o[o['bet_mktonly']]))}",
                  f"- Bet every candidate underdog: {_fmt_summary(backtest.summarize(o))}", ""]
        for tour in tours:
            t = o[o["tour"] == tour]
            lines.append(f"- {tour.upper()} model bets: {_fmt_summary(backtest.summarize(t[t['bet_model']]))}")
        lines += ["", "Model bets by season:", ""] + _season_table(backtest.by_season(o, "bet_model"), True) + [""]

    if all(not o.empty for o in oos.values()):
        g = backtest.gate(oos)
        verdict = "PASS" if g["pass"] else "FAIL"
        lines += ["## Gate", "", f"**{verdict}**: {g['positive']}/{g['seasons']} recent seasons positive, "
                  f"{g['bets']} OOS bets, totals " + ", ".join(f"{h:.0%}: {p:+.1f}u" for h, p in g["totals"].items()), ""]
        lines += [f"- {r}" for r in g["reasons"]] + [""]
    return "\n".join(lines)


def main(argv=None) -> None:
    cfg = load_config()["upsets"]
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data-dir", default=cfg["data_dir"])
    ap.add_argument("--book", default=cfg["bet_book"])
    ap.add_argument("--tours", default=",".join(cfg["tours"]))
    ap.add_argument("--out", default="reports/upsets_findings.md")
    args = ap.parse_args(argv)

    tours = args.tours.split(",")
    matches = elo.add_elo(load.load_dir(args.data_dir, tuple(tours)))
    frame = features.build(matches, cfg["early_rounds"])
    r = cfg["rule"]
    rule = backtest.Rule(bet_book=args.book, early_only=r["early_only"], fav_rank_max=r["fav_rank_max"],
                         min_odds=r["min_odds"], max_odds=r["max_odds"], min_history=r["min_history"],
                         edge_grid=r["edge_grid"], default_edge=r["default_edge"],
                         min_select_bets=r["min_select_bets"], l2=r["l2"], burn_in_seasons=r["burn_in_seasons"])
    seasons = sorted(frame["season"].unique())
    test_seasons = [int(s) for s in seasons if s >= seasons[0] + cfg["min_train_seasons"]]
    text = report(frame, rule, test_seasons, cfg["haircuts"], tours)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
