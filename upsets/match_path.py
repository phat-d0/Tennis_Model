"""Match path on Kalshi: what happens to the original favourite's price from the pre-match close,
through each set, to the end, and does the original favourite make it out?

    python -m upsets.match_path --data data/processed/kalshi_g0 [--data data/processed/kalshi_g12] \
        --raw data/raw/kalshi [--out reports/upsets_match_path.md] [--examples data/reports/examples.json]

Per match (ATP/WTA have per-set markets; Challenger / WTA 125 don't, so they get pre/post only):
- Original favourite = the side with the higher closing pre-match ask (last quote at or before
  the scheduled start, <= 3 h old; kalshi_preview.closing_quotes). Their pre-match ask and price.
- Price = ask-implied probability p = (ask_fav + 1 - ask_other) / 2 (both legs carried forward
  <= 30 min); the ask is what buying costs. Quotes are 1-min candles.
- In play = scheduled start -> the match's last quote: min / max p, and favourite flips: the
  market favourite changes when the other side's p >= 0.55 (p <= 0.45) for >= 2 min, and back
  when p >= 0.55 for >= 2 min, so 1c noise isn't counted. A favourite who loses always ends
  with a flip (the price goes to 0), so P(win | flip) reads as "recovered after losing it".
- Sets: Kalshi lists sets before the decider only (bo3: 1-2; bo5: 1-3, plus 4 if reached).
  Snapshots as of each set's close_time + 90 s (both legs <= 5 min old). The decider starts at
  the last listed set's close when the score is level. A match is excluded when a set settled
  at a fair price (retirement) and set-based metrics are dropped when a close_time is unreliable
  (> 15 min after the match's last quote, or a batch timestamp shared by many sets). Decider-start
  metrics also need decider.guard: 15-180 min before the match close, not shared by 2+ matches.
- Outcome: settle of the favourite's side (fair-price match settlements reported apart).
Aggregates only; the example timelines go to a separate file (never into git).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from swinglock.config import kalshi_fees
from swinglock.locks import buy_cost

from . import decider as dz
from . import kalshi_preview as kp

TOURS = {"KXATPMATCH": "ATP", "KXWTAMATCH": "WTA", "KXATPCHALLENGERMATCH": "ATP-Ch",
         "KXWTACHALLENGERMATCH": "WTA125"}
P_BINS = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
TEAM_RE = r"(?i)billie jean|\bbjk\b|fed cup|davis cup|united cup|laver cup|hopman"
EXTREME = 0.99          # p >= 0.99 or <= 0.01: the match is effectively over; later quotes are junk
DECIDER_MAX_MIN = 180   # same bound as decider.guard


# --- per-match series ------------------------------------------------------------------------

def leg_series(q: pd.DataFrame, max_carry_s: float = 1800) -> pd.DataFrame:
    """One match's quotes -> ts, ask_a, ask_b, age_a, age_b (s since that leg's last quote)."""
    w = q.pivot_table(index="ts", columns="side", values="ask", aggfunc="last").reindex(columns=["A", "B"])
    out = pd.DataFrame(index=w.index)
    t = pd.Series(w.index, index=w.index)
    for side, col in (("A", "a"), ("B", "b")):
        seen = t.where(w[side].notna()).ffill()
        age = (t - seen).dt.total_seconds()
        val = w[side].ffill()
        out[f"ask_{col}"] = val.where(age <= max_carry_s)
        out[f"age_{col}"] = age
        out[f"seen_{col}"] = seen
    return out.reset_index()


def asof(s: pd.DataFrame, t: pd.Timestamp, max_age_s: float = 300) -> tuple[float, float]:
    """(ask_a, ask_b) as of t, NaN if either leg's last quote is older than max_age_s."""
    i = s["ts"].searchsorted(t, side="right") - 1
    if i < 0:
        return np.nan, np.nan
    r = s.iloc[i]
    if (t - r["seen_a"]).total_seconds() > max_age_s or (t - r["seen_b"]).total_seconds() > max_age_s:
        return np.nan, np.nan
    return r["ask_a"], r["ask_b"]


def implied(ask_fav, ask_oth):
    return (np.asarray(ask_fav, float) + 1.0 - np.asarray(ask_oth, float)) / 2.0


def flips(ts: pd.Series, p: pd.Series, band: float = 0.05, hold_s: float = 120) -> list[pd.Timestamp]:
    """Times the market favourite changed (start of each confirmed run). p = original fav's
    probability; starts with them as favourite. A change needs p on the other side of
    0.5 -/+ band for hold_s (judged at later observations; values carry forward)."""
    state_fav = True
    cand = None
    out = []
    for t, v in zip(ts, p):
        if v != v:
            continue
        crossed = v <= 0.5 - band if state_fav else v >= 0.5 + band
        if crossed:
            if cand is None:
                cand = t
            if (t - cand).total_seconds() >= hold_s:
                out.append(cand)
                state_fav, cand = not state_fav, None
        else:
            cand = None
    return out


# --- per-match table -------------------------------------------------------------------------

def unreliable_sets(sets: pd.DataFrame, last_quote: pd.Series, late_min: float = 15,
                    batch_n: int = 5) -> pd.Series:
    """Per set row: close_time > last quote + late_min, or a close second shared by >= batch_n
    sets of different matches (administrative batch close)."""
    lq = sets["match_id"].map(last_quote)
    late = sets["close_time"] > lq + pd.Timedelta(minutes=late_min)
    sec = sets["close_time"].dt.floor("s")
    shared = sets.groupby(sec)["match_id"].transform("nunique") >= batch_n
    return late | shared


def classify_path(letters: list[str], best_of: float, fav_won: float) -> tuple[str, str]:
    """Listed sets (favourite's view) -> (kind, path label). Kalshi lists only the sets before
    the decider, so: 'complete' = someone reached the winning count within the listed sets;
    'decider' = level after exactly best_of - 1 listed sets (the label appends the match result);
    'incomplete' = sets missing (e.g. bo5 at 1-1 with set 3 unlisted) or best_of unknown;
    'inconsistent' = the listed sets disagree with the settlement. Only complete/decider paths
    get a label; the others are 'incomplete' / 'inconsistent'."""
    if best_of != best_of:
        return "incomplete", "incomplete"
    bo = int(best_of)
    need = (bo + 1) // 2
    w, l, n = letters.count("W"), letters.count("L"), len(letters)
    known = fav_won == fav_won
    if max(w, l) >= need:
        if known and (w >= need) != (fav_won == 1):
            return "inconsistent", "inconsistent"
        return "complete", "".join(letters)
    if w == l and n == bo - 1:
        return "decider", "".join(letters) + (("W" if fav_won == 1 else "L") if known else "?")
    return "incomplete", "incomplete"


def in_play_end(st: pd.DataFrame | None, best_of: float) -> pd.Timestamp | None:
    """Plausible end of play from the listed sets: last set close + 5 min when that set ended the
    match, + DECIDER_MAX_MIN when a decider followed; None when sets are missing or unreliable."""
    if st is None or not len(st) or st["unreliable"].any() or (st["status"] != "decided").any():
        return None
    last = st["close_time"].max()
    if best_of != best_of:
        return last + pd.Timedelta(minutes=DECIDER_MAX_MIN)
    need = (int(best_of) + 1) // 2
    sides = list(st.sort_values("set_no")["winner_side"])
    done = max(sides.count("A"), sides.count("B")) >= need
    return last + pd.Timedelta(minutes=5 if done else DECIDER_MAX_MIN)


def path_table(matches: pd.DataFrame, quotes: pd.DataFrame, sets: pd.DataFrame | None,
               details: pd.DataFrame | None = None, offset_s: float = 90, max_age_s: float = 300,
               prematch_age_h: float = 3.0) -> tuple[pd.DataFrame, dict]:
    """One row per match with a pre-match favourite. Returns (table, per-match series for examples)."""
    m = matches[matches["series"].isin(TOURS)].dropna(subset=["scheduled_start"]).copy()
    pre = kp.closing_quotes(m, quotes, prematch_age_h).dropna(subset=["ask_a", "ask_b"])
    pre = pre[pre["ask_a"] != pre["ask_b"]]
    m = m.merge(pre, on="match_id")
    m["fav"] = np.where(m["ask_a"] > m["ask_b"], "A", "B")
    names = m.get("tournament", pd.Series("", index=m.index)).fillna("").astype(str)
    if details is not None and len(details) and "tournament_name" in details:
        names = names + " " + m["match_id"].map(details.set_index("match_id")["tournament_name"]).fillna("").astype(str)
    m["team"] = names.str.contains(TEAM_RE, regex=True)
    q = quotes[quotes["match_id"].isin(m["match_id"])][["ts", "match_id", "side", "ask"]].dropna(subset=["ask"])
    last_quote = q.groupby("match_id")["ts"].max()
    bo = (pd.to_numeric(details.set_index("match_id")["best_of"], errors="coerce")
          if details is not None and len(details) else pd.Series(dtype=float))
    if sets is not None and len(sets):
        st = sets[sets["match_id"].isin(m["match_id"])].copy()
        st["unreliable"] = unreliable_sets(st, last_quote)
        sets_by = dict(tuple(st.sort_values("set_no").groupby("match_id")))
    else:
        sets_by = {}
    q_by = dict(tuple(q.sort_values("ts").groupby("match_id")))
    rows, series = [], {}
    for r in m.itertuples():
        fa = r.fav == "A"
        a_f, a_o = (r.ask_a, r.ask_b) if fa else (r.ask_b, r.ask_a)
        settle_f = r.settle_a if fa else r.settle_b
        tour = TOURS[r.series] + (" team" if r.team else "")
        b = bo.get(r.match_id, np.nan)
        if b != b and TOURS[r.series] != "ATP":
            b = 3.0  # WTA, ATP-Ch and WTA 125 singles are best of 3
        row = {"match_id": r.match_id, "tour": tour, "start": r.scheduled_start,
               "month": r.scheduled_start.strftime("%Y-%m"), "fee_type": r.fee_type,
               "fee_multiplier": r.fee_multiplier, "fav": r.fav, "pre_ask": a_f, "pre_ask_oth": a_o,
               "pre_p": float(implied(a_f, a_o)), "settle_fav": settle_f,
               "fair": settle_f not in (0.0, 1.0), "fav_won": float(settle_f == 1.0) if settle_f in (0.0, 1.0) else np.nan,
               "best_of": b}
        qm = q_by.get(r.match_id)
        st = sets_by.get(r.match_id)
        cut = in_play_end(st, b)
        if qm is not None:
            s = leg_series(qm)
            live = s[s["ts"] >= r.scheduled_start]
            p = pd.Series(implied(live["ask_a"], live["ask_b"]) if fa else implied(live["ask_b"], live["ask_a"]),
                          index=live.index)
            fl_raw = flips(live["ts"], p)
            row["p_min_raw"] = p.min() if p.notna().any() else np.nan
            row["n_flips_raw"] = len(fl_raw)
            # clean: both legs <= max_age_s old, before the plausible match end, and nothing after
            # the price first reaches the extremes (post-match books are junk)
            keep = (live["age_a"] <= max_age_s) & (live["age_b"] <= max_age_s)
            if cut is not None:
                keep &= live["ts"] <= cut
            p = p.where(keep)
            ext = p[(p >= EXTREME) | (p <= 1 - EXTREME)]
            if len(ext):
                p = p.where(p.index <= ext.index[0])
            row["p_min"], row["p_max"] = (p.min(), p.max()) if p.notna().any() else (np.nan, np.nan)
            fl = flips(live["ts"], p)
            row["n_flips"] = len(fl)
            row["first_flip_min"] = (fl[0] - r.scheduled_start).total_seconds() / 60 if fl else np.nan
            row["_first_flip"] = fl[0] if fl else pd.NaT
            series[r.match_id] = (live["ts"], p)
        else:
            s = None
            row.update(p_min=np.nan, p_max=np.nan, n_flips=np.nan, first_flip_min=np.nan, _first_flip=pd.NaT,
                       p_min_raw=np.nan, n_flips_raw=np.nan)
        row.update(has_sets=st is not None, set_fair=False, set_unreliable=False, n_sets_listed=0,
                   path="", path_listed="", path_kind="", decider=False, pen_fav_won=np.nan,
                   decider_start=pd.NaT)
        if st is not None:
            row["set_fair"] = bool((st["status"] == "fair_price").any())
            row["set_unreliable"] = bool(st["unreliable"].any())
            dec = st[st["status"] == "decided"]
            ok = (not row["set_fair"] and not row["set_unreliable"] and len(dec) == len(st)
                  and list(dec["set_no"]) == list(range(1, len(dec) + 1)))
            if ok:
                sides = list(dec["winner_side"])
                letters = ["W" if x == r.fav else "L" for x in sides]
                n = len(letters)
                row["n_sets_listed"] = n
                row["path_listed"] = "".join(letters)
                kind, path = classify_path(letters, b, row["fav_won"])
                row["path_kind"], row["path"] = kind, path
                if kind == "decider":
                    row["decider"] = True
                    row["pen_fav_won"] = float(letters[-1] == "W")
                    row["decider_start"] = dec["close_time"].iloc[-1]
                need = (int(b) + 1) // 2 if b == b else None
                for k, (ct, who) in enumerate(zip(dec["close_time"], sides), 1):
                    t = ct + pd.Timedelta(seconds=offset_s)
                    aa, ab = asof(s, t, max_age_s) if s is not None else (np.nan, np.nan)
                    af, ao = (aa, ab) if fa else (ab, aa)
                    row[f"set{k}_ask"], row[f"set{k}_ask_oth"] = af, ao
                    row[f"set{k}_p"] = float(implied(af, ao))
                    row[f"set{k}_min"] = (ct - r.scheduled_start).total_seconds() / 60
                    w_k, l_k = letters[:k].count("W"), letters[:k].count("L")
                    row[f"set{k}_live"] = bool(need) and kind in ("decider", "complete") and max(w_k, l_k) < need
                if row["_first_flip"] is not pd.NaT:
                    ends = list(dec["close_time"])
                    row["first_flip_set"] = 1 + sum(e < row["_first_flip"] for e in ends)
        rows.append(row)
    t = pd.DataFrame(rows)
    usable = t["has_sets"] & ~t["set_fair"] & ~t["set_unreliable"]
    if "set1_p" not in t:
        t["set1_p"] = np.nan
    t["set_ok"] = usable & (t["n_sets_listed"] > 0)
    # market favourite at the decider start = the original favourite if p >= 0.5 then
    last_k = t["n_sets_listed"].clip(lower=1)
    t["decider_p"] = [r.get(f"set{int(k)}_p", np.nan) if d else np.nan
                      for (_, r), k, d in zip(t.iterrows(), last_k, t["decider"])]
    # decider-start plausibility (decider.guard): 15-180 min before the match close, not a batch close
    d = t.loc[t["decider"], ["match_id", "decider_start"]]
    g = dz.guard(d, dz.match_end(matches, quotes)) if len(d) else d.assign(ok=pd.Series(dtype=bool))
    t["decider_ok"] = t["match_id"].map(g.set_index("match_id")["ok"]).fillna(False).astype(bool)
    return t.drop(columns=["_first_flip"]), series


# --- bets ------------------------------------------------------------------------------------

def buy(t: pd.DataFrame, ask_col: str, pay: pd.Series, cfg: dict, contracts: float = 100) -> pd.DataFrame:
    """Cost / P&L (0c, 1c) of buying `contracts` at ask_col + taker fee, settling at pay."""
    fees, out = {}, {}
    for slip in (0.0, 0.01):
        cost = []
        for ask, ft, mult in zip(t[ask_col], t["fee_type"], t["fee_multiplier"]):
            if ask != ask:
                cost.append(np.nan)
                continue
            if (ft, mult) not in fees:
                fees[(ft, mult)] = kalshi_fees(cfg, ft, mult)
            cost.append(buy_cost(ask, contracts, fees[(ft, mult)], slip))
        tag = f"{round(slip * 100)}c"
        out[f"cost_{tag}"] = np.asarray(cost, float)
        out[f"pnl_{tag}"] = contracts * np.asarray(pay, float) - out[f"cost_{tag}"]
    return pd.DataFrame(out, index=t.index)


def roi_stats(b: pd.DataFrame, n_boot: int = 2000, seed: int = 0) -> dict:
    b = b.dropna(subset=["cost_0c"])
    if not len(b):
        return {"n": 0, "roi": np.nan, "lo": np.nan, "hi": np.nan, "roi1": np.nan}
    pnl, cost = b["pnl_0c"].to_numpy(), b["cost_0c"].to_numpy()
    if len(b) > 1:
        idx = np.random.default_rng(seed).integers(0, len(b), size=(n_boot, len(b)))
        lo, hi = np.percentile(pnl[idx].sum(1) / cost[idx].sum(1), [2.5, 97.5])
    else:
        lo = hi = np.nan
    return {"n": len(b), "roi": pnl.sum() / cost.sum(), "lo": lo, "hi": hi,
            "roi1": b["pnl_1c"].sum() / b["cost_1c"].sum()}


# --- report ----------------------------------------------------------------------------------

def _p(x, signed=False) -> str:
    return "—" if x is None or x != x else (f"{x:+.1%}" if signed else f"{x:.1%}")


def _fmt(t: pd.DataFrame) -> pd.Series:
    bo = t["best_of"].map(lambda v: f" bo{int(v)}" if v == v else "")
    return t["tour"] + bo


def report(full: pd.DataFrame, cfg: dict) -> str:
    t = full[~full["set_fair"]].copy()
    t["fmt"] = _fmt(t)
    dec = t[t["fav_won"].notna()]
    L = ["# Match path: does the original favourite make it out? (Kalshi)", "",
         "Original favourite = higher closing pre-match ask. p = ask-implied probability "
         "(ask_fav + 1 − ask_other)/2. Flip = the market favourite changes (p crosses 0.45/0.55 and "
         "stays ≥ 2 min). Set snapshots at set close + 90 s. 1-min candles; aggregates only.", "",
         "## Coverage", "",
         "| Tour | Matches | Fair-price settlement | With set rows | Retirement (fair-price set) | "
         "Unreliable set close | Set path usable | Deciders (guard failed) |", "|---|---|---|---|---|---|---|---|"]
    for tour, g in full.groupby("tour"):
        L.append(f"| {tour} | {len(g):,} | {int(g['fair'].sum())} | {int(g['has_sets'].sum()):,} | "
                 f"{int(g['set_fair'].sum())} (excluded) | "
                 f"{int(g['set_unreliable'].sum())} | {int(g['set_ok'].sum()):,} | "
                 f"{int(g['decider'].sum()):,} ({int((g['decider'] & ~g['decider_ok']).sum())}) |")
    kinds = full["path_kind"].fillna("")
    changed = full["p_min_raw"].notna() & ((full["p_min_raw"] - full["p_min"]).abs() > 1e-9)
    junk = changed & (full["fav_won"] == 1) & (full["p_min_raw"] < 0.10) & ~(full["p_min"] < 0.10)
    L += ["", f"Set paths: complete {int((kinds == 'complete').sum()):,}, decider {int((kinds == 'decider').sum()):,}, "
          f"incomplete (sets missing, e.g. bo5 at 1–1 with set 3 unlisted) {int((kinds == 'incomplete').sum()):,}, "
          f"inconsistent with the settlement {int((kinds == 'inconsistent').sum()):,}; only complete and decider "
          "paths are used.", "",
          f"In-play cleaning (both legs ≤ 5 min old, cut at the last set close + 5 min or + {DECIDER_MAX_MIN} min "
          f"for a decider, nothing after p first reaches {EXTREME:.2f}/{1 - EXTREME:.2f}): in-play min changed in "
          f"{int(changed.sum()):,} matches, flip count in "
          f"{int((full['n_flips_raw'].notna() & (full['n_flips_raw'] != full['n_flips'])).sum()):,}; favourite wins "
          f"with a raw min < 0.10 that the cleaning removed: {int(junk.sum()):,}.", "",
          "Win rates leave out fair-price match settlements (not started); ROI keeps them at their "
          "settle price.", "", "## Original favourite: win rate", "", "| Slice | Matches | Fav won | SE |", "|---|---|---|---|"]

    def wr(name, g):
        n = g["fav_won"].notna().sum()
        r = g["fav_won"].mean()
        se = np.sqrt(r * (1 - r) / n) if n else np.nan
        L.append(f"| {name} | {n:,} | {_p(r)} | {_p(se)} |")

    for fmt, g in dec.groupby("fmt"):
        wr(fmt, g)
    L += ["", "By set path (favourite's view; ATP/WTA with usable sets):", "",
          "| Format | Path | Matches | Share | Fav won |", "|---|---|---|---|---|"]
    sp = dec[dec["set_ok"] & dec["path_kind"].isin(["complete", "decider"])]
    for fmt, g in sp.groupby("fmt"):
        for path, h in g.groupby("path"):
            L.append(f"| {fmt} | {path} | {len(h):,} | {len(h) / len(g):.1%} | {_p(h['fav_won'].mean())} |")
    dd = sp[sp["decider"] & sp["decider_ok"]]
    L += ["", "Deciders, by who won the penultimate set:", "", "| Format | Penultimate set | Matches | Fav won |",
          "|---|---|---|---|"]
    for fmt, g in dd.groupby("fmt"):
        for won, h in g.groupby("pen_fav_won"):
            L.append(f"| {fmt} | {'favourite won it' if won == 1 else 'favourite lost it'} | {len(h):,} | "
                     f"{_p(h['fav_won'].mean())} |")

    L += ["", "## Favourite flips (in play)", "",
          "| Format | Matches | ≥ 1 flip | 0 | 1 | 2 | 3+ | Fav won if ≥ 1 flip | if 2+ flips | "
          "if the other player was market fav at the decider start | First flip: median min (IQR) |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    fl = dec[dec["n_flips"].notna()]
    for fmt, g in fl.groupby("fmt"):
        n = len(g)
        c = g["n_flips"].clip(upper=3).value_counts().reindex([0, 1, 2, 3], fill_value=0)
        f1, f2 = g[g["n_flips"] >= 1], g[g["n_flips"] >= 2]
        oth = g[g["decider"] & g["decider_ok"] & (g["decider_p"] < 0.5)]
        ff = g["first_flip_min"].dropna()
        L.append(f"| {fmt} | {n:,} | {(g['n_flips'] >= 1).mean():.1%} | {c[0] / n:.1%} | {c[1] / n:.1%} | "
                 f"{c[2] / n:.1%} | {c[3] / n:.1%} | {_p(f1['fav_won'].mean())} ({len(f1):,}) | "
                 f"{_p(f2['fav_won'].mean())} ({len(f2):,}) | {_p(oth['fav_won'].mean())} ({len(oth):,}) | "
                 + (f"{ff.median():.0f} ({ff.quantile(.25):.0f}–{ff.quantile(.75):.0f})" if len(ff) else "—") + " |")
    if "first_flip_set" in dec:
        L += ["", "Set in which the first flip happened (usable sets):", "", "| Format | Set 1 | Set 2 | Set 3 | Set 4 | Set 5 |",
              "|---|---|---|---|---|---|"]
        for fmt, g in dec[dec["set_ok"]].groupby("fmt"):
            c = g["first_flip_set"].dropna().astype(int).value_counts(normalize=True)
            L.append(f"| {fmt} | " + " | ".join(_p(c.get(k, 0.0)) for k in range(1, 6)) + " |")

    L += ["", "## Average path of the original favourite's price (for a line chart)", "",
          "Mean p at the pre-match close and after each listed set (close + 90 s), by final outcome; a set "
          "column uses only matches still in play at that set end (n in brackets).", "",
          "| Format | Outcome | Matches | Pre | Min in play | Max in play | After set 1 | After set 2 | After set 3 | After set 4 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for fmt, g in dec.groupby("fmt"):
        for won, h in g.groupby("fav_won"):
            cells = []
            for k in range(1, 5):
                v = h.get(f"set{k}_p", pd.Series(dtype=float))[h.get(f"set{k}_live", pd.Series(False, index=h.index))
                                                               .fillna(False).astype(bool)]
                cells.append(f"{_p(v.mean())} ({v.notna().sum():,})" if v.notna().any() else "—")
            L.append(f"| {fmt} | {'fav won' if won == 1 else 'fav lost'} | {len(h):,} | {_p(h['pre_p'].mean())} | "
                     f"{_p(h['p_min'].mean())} | {_p(h['p_max'].mean())} | " + " | ".join(cells) + " |")

    L += ["", "## Price test at each set end", "",
          "Calibration: the original favourite's live p vs how often they won; ROI of buying them (or "
          "the original underdog) at the ask + Kalshi fee, 100 contracts. Only matches still in play at "
          "that set end (e.g. bo3 after set 2 = 1–1 only).", "",
          "| Format | After set | p bin | Matches | Mean p | Fav won | Buy fav ROI 0¢ (95% CI) | ROI 1¢ | Buy dog ROI 0¢ |",
          "|---|---|---|---|---|---|---|---|---|"]
    for fmt, g in dec[dec["set_ok"]].groupby("fmt"):
        for k in range(1, 5):
            col = f"set{k}_p"
            if col not in g or not g[col].notna().any():
                continue
            live = g.get(f"set{k}_live", pd.Series(False, index=g.index)).fillna(False).astype(bool)
            h = g[g[col].notna() & live]  # only states still in play: a finished match isn't tradable
            if not len(h):
                continue
            for bucket, x in h.groupby(pd.cut(h[col], P_BINS), observed=True):
                bf = roi_stats(buy(x, f"set{k}_ask", x["settle_fav"], cfg))
                bd = roi_stats(buy(x, f"set{k}_ask_oth", 1 - x["settle_fav"], cfg))
                L.append(f"| {fmt} | {k} | {bucket} | {len(x):,} | {_p(x[col].mean())} | {_p(x['fav_won'].mean())} | "
                         f"{_p(bf['roi'], True)} ({_p(bf['lo'], True)} to {_p(bf['hi'], True)}) | "
                         f"{_p(bf['roi1'], True)} | {_p(bd['roi'], True)} |")

    L += ["", "## Penultimate-set winner at the decider start", "",
          "Buy the player who won the penultimate set (who just levelled) at the ask + fee as of the "
          "last listed set's close + 90 s.", "",
          "| Format | Who levelled | Matches | Levelling player won | Mean ask | ROI 0¢ (95% CI) | ROI 1¢ |",
          "|---|---|---|---|---|---|---|"]
    for fmt, g in dd.groupby("fmt"):
        k = g["n_sets_listed"].astype(int)
        ask_f = pd.Series([r.get(f"set{kk}_ask", np.nan) for (_, r), kk in zip(g.iterrows(), k)], index=g.index)
        ask_o = pd.Series([r.get(f"set{kk}_ask_oth", np.nan) for (_, r), kk in zip(g.iterrows(), k)], index=g.index)
        lev_fav = g["pen_fav_won"] == 1
        x = g.assign(lev_ask=np.where(lev_fav, ask_f, ask_o),
                     lev_pay=np.where(lev_fav, g["settle_fav"], 1 - g["settle_fav"]),
                     lev_won=np.where(lev_fav, g["fav_won"], 1 - g["fav_won"]))
        for name, h in (("all", x), ("pre-match favourite", x[lev_fav]), ("pre-match underdog", x[~lev_fav])):
            s = roi_stats(buy(h, "lev_ask", h["lev_pay"], cfg))
            L.append(f"| {fmt} | {name} | {s['n']:,} | {_p(h.loc[h['lev_ask'].notna(), 'lev_won'].mean())} | "
                     f"{_p(h['lev_ask'].mean())} | {_p(s['roi'], True)} ({_p(s['lo'], True)} to {_p(s['hi'], True)}) | "
                     f"{_p(s['roi1'], True)} |")
    return "\n".join(L) + "\n"


def examples(t: pd.DataFrame, series: dict, matches: pd.DataFrame, max_points: int = 60) -> list[dict]:
    """Three timelines with a flip: favourite recovers / doesn't / 2+ flips. Never committed."""
    g = t[t["set_ok"] & (t["n_flips"] >= 1) & t["fav_won"].notna()].sort_values("match_id")
    picks = []
    for cond in (lambda x: (x["fav_won"] == 1) & (x["n_flips"] == 2),
                 lambda x: (x["fav_won"] == 0) & (x["n_flips"] >= 1),
                 lambda x: x["n_flips"] >= 3):
        c = g[cond(g) & ~g["match_id"].isin([p["match_id"] for p in picks])]
        if len(c):
            picks.append(c.iloc[0].to_dict())
    names = matches.set_index("match_id")[["player_a", "player_b"]]
    out = []
    for r in picks:
        ts, p = series[r["match_id"]]
        ok = p.notna().to_numpy()
        tt, pp = ts.to_numpy()[ok], p.to_numpy()[ok]
        idx = np.unique(np.linspace(0, len(tt) - 1, min(max_points, len(tt))).astype(int))
        start = r["start"]
        fav_name = names.loc[r["match_id"], "player_a" if r["fav"] == "A" else "player_b"]
        out.append({
            "match_id": r["match_id"], "tour": r["tour"], "favourite": fav_name, "pre_p": round(r["pre_p"], 3),
            "fav_won": bool(r["fav_won"]), "n_flips": int(r["n_flips"]), "path": r["path"],
            "set_ends_min": [round(r[f"set{k}_min"], 1) for k in range(1, int(r["n_sets_listed"]) + 1)],
            "points": [[round((pd.Timestamp(x) - start).total_seconds() / 60, 1), round(float(v), 3)]
                       for x, v in zip(tt[idx], pp[idx])]})
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, action="append", help="processed dir(s); sets.parquet optional")
    ap.add_argument("--raw", type=Path, default=Path("data/raw/kalshi"))
    ap.add_argument("--min-interval", type=float, default=1.0)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--examples", type=Path, default=Path("data/reports/match_path_examples.json"))
    a = ap.parse_args(argv)

    from swinglock.collectors.kalshi import KalshiClient
    from swinglock.config import load_config

    dirs = a.data or [Path("data/processed/kalshi_g0")]
    matches = pd.concat([pd.read_parquet(d / "matches.parquet") for d in dirs], ignore_index=True)
    quotes = pd.concat([pd.read_parquet(d / "quotes.parquet") for d in dirs], ignore_index=True)
    sets = [pd.read_parquet(d / "sets.parquet") for d in dirs if (d / "sets.parquet").exists()]
    sets = pd.concat(sets, ignore_index=True) if sets else None
    since = matches["scheduled_start"].min().strftime("%Y-%m-%dT00:00:00Z")
    client = KalshiClient(raw_dir=a.raw, min_interval_s=a.min_interval)
    details = kp.milestone_details(client, since)
    t, series = path_table(matches, quotes, sets, details)
    text = report(t, load_config())
    print(text)
    print(f"[requests made: {client.requests_made}, cache hits: {client.cache_hits}]")
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(text)
    a.examples.parent.mkdir(parents=True, exist_ok=True)
    a.examples.write_text(json.dumps(examples(t, series, matches), indent=1, default=str))
    print(f"[examples -> {a.examples} (not for git)]")


if __name__ == "__main__":
    main()
