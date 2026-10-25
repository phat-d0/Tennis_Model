"""Season walk-forward backtest of "bet the early-round underdog when the model sees an edge".

For each test season Y: fit on seasons before Y (after a burn-in so Elo has settled),
predict season Y, and bet the underdog when p_model x odds - 1 >= edge threshold. The
threshold for Y is picked on the earlier test seasons' out-of-sample bets only. Bets are
1 unit, settled at the bet book's closing price (minus an optional haircut for a worse
book such as DraftKings); voided matches return the stake.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import model
from .features import FEATURES


@dataclass
class Rule:
    bet_book: str = "b365"
    early_only: bool = True
    fav_rank_max: float | None = 32     # the favourite is a top-N player ("seeded")
    min_odds: float = 1.0
    max_odds: float = 10.0
    min_history: int = 20               # both players' prior matches (Elo has settled)
    edge_grid: list[float] = field(default_factory=lambda: [0.0, 0.02, 0.05, 0.08, 0.10, 0.15])
    default_edge: float = 0.05
    min_select_bets: int = 50
    l2: float = 1.0
    burn_in_seasons: int = 2


def payout_odds(odds: pd.Series, haircut: float) -> pd.Series:
    """Decimal odds after cutting `haircut` (fraction) off the winnings."""
    return 1.0 + (odds - 1.0) * (1.0 - haircut)


def settle(bets: pd.DataFrame, odds_col: str = "odds_bet") -> pd.Series:
    pnl = np.where(bets["upset"] == 1, bets[odds_col] - 1.0, -1.0)
    return pd.Series(np.where(bets["void"], 0.0, pnl), index=bets.index)


def candidates(test: pd.DataFrame, rule: Rule, haircut: float) -> pd.DataFrame:
    odds = test[f"odds_dog_{rule.bet_book}"]
    ok = odds.notna() & (odds >= rule.min_odds) & (odds <= rule.max_odds)
    ok &= test["min_history"] >= rule.min_history
    if rule.early_only:
        ok &= test["early"] == 1
    if rule.fav_rank_max is not None:
        ok &= test["fav_rank"] <= rule.fav_rank_max
    c = test[ok].copy()
    c["odds_bet"] = payout_odds(c[f"odds_dog_{rule.bet_book}"], haircut)
    return c


def _pick_edge(history: pd.DataFrame, p_col: str, rule: Rule) -> float:
    """Best edge threshold on earlier out-of-sample candidates (total P&L, >= min bets)."""
    best, best_pnl = rule.default_edge, None
    if history.empty:
        return best
    edge = history[p_col] * history["odds_bet"] - 1.0
    for t in rule.edge_grid:
        sel = history[edge >= t]
        if len(sel) < rule.min_select_bets:
            continue
        pnl = settle(sel).sum()
        if best_pnl is None or pnl > best_pnl:
            best, best_pnl = t, pnl
    return best


def walk_forward(frame: pd.DataFrame, test_seasons: list[int], rule: Rule,
                 haircut: float = 0.0, features: list[str] = FEATURES) -> pd.DataFrame:
    """Out-of-sample candidates for every test season with p_model, p_mktonly, chosen
    thresholds and a `bet_model` / `bet_mktonly` flag. Every candidate is also the
    'bet every early-round dog' baseline."""
    first = int(frame["season"].min()) + rule.burn_in_seasons
    train_ok = (~frame["void"]) & (frame["min_history"] >= 5) & (frame["season"] >= first)
    out = []
    for y in sorted(test_seasons):
        train = frame[train_ok & (frame["season"] < y)]
        if len(train) < 500:
            continue
        cand = candidates(frame[frame["season"] == y], rule, haircut)
        if cand.empty:
            continue
        full = model.fit(train[features].to_numpy(), train["upset"].to_numpy(), rule.l2)
        mkt = model.fit(train[["mkt_logit"]].to_numpy(), train["upset"].to_numpy(), rule.l2)
        cand["p_model"] = full.predict(cand[features].to_numpy())
        cand["p_mktonly"] = mkt.predict(cand[["mkt_logit"]].to_numpy())
        hist = pd.concat(out) if out else cand.iloc[:0]
        for p_col, tag in (("p_model", "model"), ("p_mktonly", "mktonly")):
            t = _pick_edge(hist, p_col, rule)
            cand[f"edge_{tag}"] = t
            cand[f"bet_{tag}"] = cand[p_col] * cand["odds_bet"] - 1.0 >= t
        cand["test_season"] = y
        out.append(cand)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def summarize(bets: pd.DataFrame, seed: int = 0, n_boot: int = 2000) -> dict:
    """Units P&L, ROI on non-void stakes, max drawdown, and a bootstrap 95% CI on ROI."""
    if bets.empty:
        return {"bets": 0, "wins": 0, "voids": 0, "staked": 0.0, "pnl": 0.0, "roi": np.nan,
                "roi_lo": np.nan, "roi_hi": np.nan, "max_dd": 0.0, "avg_odds": np.nan}
    b = bets.sort_values("date")
    pnl = settle(b).to_numpy()
    live = ~b["void"].to_numpy()
    staked = float(live.sum())
    cum = np.cumsum(pnl)
    dd = float(np.max(np.maximum.accumulate(np.concatenate([[0.0], cum]))[1:] - cum)) if len(cum) else 0.0
    rng = np.random.default_rng(seed)
    p_live = pnl[live]
    if len(p_live):
        idx = rng.integers(0, len(p_live), size=(n_boot, len(p_live)))
        boots = p_live[idx].mean(axis=1)
        lo, hi = np.percentile(boots, [2.5, 97.5])
    else:
        lo = hi = np.nan
    return {
        "bets": int(len(b)), "wins": int(((b["upset"] == 1) & live).sum()), "voids": int((~live).sum()),
        "staked": staked, "pnl": float(pnl.sum()), "roi": float(pnl.sum() / staked) if staked else np.nan,
        "roi_lo": float(lo), "roi_hi": float(hi), "max_dd": dd, "avg_odds": float(b["odds_bet"].mean()),
    }


def by_season(oos: pd.DataFrame, flag: str | None) -> pd.DataFrame:
    rows = []
    for y, g in oos.groupby("test_season"):
        s = summarize(g[g[flag]] if flag else g)
        s["season"] = y
        if flag:
            s["edge"] = g[f"edge_{flag.removeprefix('bet_')}"].iloc[0]
        rows.append(s)
    return pd.DataFrame(rows)


def gate(oos_by_haircut: dict[float, pd.DataFrame], flag: str = "bet_model",
         last_n: int = 4, min_positive: int = 3, min_bets: int = 200) -> dict:
    """PASS needs: >= min_positive of the last `last_n` test seasons positive at the worst
    haircut, total OOS P&L > 0 at every haircut, and >= min_bets OOS bets."""
    worst = max(oos_by_haircut)
    seasons = by_season(oos_by_haircut[worst], flag).sort_values("season").tail(last_n)
    positive = int((seasons["pnl"] > 0).sum())
    totals = {h: summarize(o[o[flag]])["pnl"] for h, o in oos_by_haircut.items()}
    n_bets = int(oos_by_haircut[worst][flag].sum())
    reasons = []
    if len(seasons) < last_n:
        reasons.append(f"only {len(seasons)} test seasons (need {last_n})")
    if positive < min_positive:
        reasons.append(f"{positive}/{len(seasons)} recent seasons positive (need {min_positive})")
    for h, p in totals.items():
        if not p > 0:
            reasons.append(f"total OOS P&L {p:+.1f}u at haircut {h:.0%}")
    if n_bets < min_bets:
        reasons.append(f"{n_bets} OOS bets (need {min_bets})")
    return {"pass": not reasons, "positive": positive, "seasons": len(seasons),
            "bets": n_bets, "totals": totals, "reasons": reasons}


def calibration(frame: pd.DataFrame, rule: Rule, bins=(0.0, 0.15, 0.25, 0.35, 0.45, 0.5)) -> pd.DataFrame:
    """Do underdogs win more often than the odds say? Early-round candidates by tour and
    de-vigged market probability: count, actual upset rate, mean p_mkt, and the bet book's
    raw implied probability (1/odds, margin included: the break-even win rate), and the
    ROI of betting every one of them at that book."""
    c = candidates(frame, rule, 0.0)
    c = c[~c["void"]].copy()
    c["bucket"] = pd.cut(c["p_mkt"], bins)
    c["pnl"] = settle(c)
    g = c.groupby(["tour", "bucket"], observed=True)
    out = g.agg(n=("upset", "size"), upset_rate=("upset", "mean"), p_mkt=("p_mkt", "mean"),
                breakeven=("odds_bet", lambda o: float((1.0 / o).mean())), roi_all=("pnl", "mean"))
    return out.reset_index()
