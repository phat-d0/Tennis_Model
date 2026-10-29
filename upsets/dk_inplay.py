"""DraftKings in-play studies (DOG50, exit-level curve, MISMATCH50, FAVDIP on DK prices): credit dry run.
Plan only, pre-registered in reports/upsets_dk_inplay.md. This module makes no paid call.

    python -m upsets.dk_inplay plan [--sackmann PATH]
    python -m upsets.dk_inplay pull --pilot KEY:TOURNEY_ID --cap 2000 --yes    # paid, staged (Lead's go)
    python -m upsets.dk_inplay pull --season 2025 --cap 270000 --per-match-max 87.5 --yes   # one full-pull stage

Universe: the early-round matches we already hold DraftKings + Pinnacle closes for (upsets.dk_history.collect,
from the cached Odds API snapshots, 0 credits), with Sackmann results (through May 2026).

Cost model (docs/research/odds_api.md §4): one /v4/historical/sports/{key}/odds snapshot = 10 credits for
h2h with draftkings + pinnacle (one region block), and it returns every event of that key at that moment,
in-play ones included. So the cost is 10 x the distinct (key, snapshot time) pairs that fall inside any
match's live window. Live window = [commence_time, commence_time + match minutes + slack]; Sackmann's
`minutes`, else the median for that best-of. The slack covers late starts ("followed by" scheduling).
The archive is 10-min before 2022-09-18 and 5-min after, so a 5-min plan uses 10 min before that date.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from .names import name_key

FIVE_MIN_FROM = pd.Timestamp("2022-09-18", tz="UTC")
CREDITS_PER_SNAPSHOT = 10
MAX_MINUTES = 360
GONE_SNAPSHOTS = 3        # a match counts as finished after this many in-play snapshots without its event
MIN_LIVE_MIN = 15         # ... looking only at snapshots at least this long after its commence time
BOOKS = ("draftkings", "pinnacle")
# In-play snapshots live apart from the close studies' cache: dk_history.collect takes each match's close
# from every cached snapshot, so mixing them in would change the closes (and every result built on them).
INPLAY_CACHE = Path("data/raw/odds_api/inplay")


def close_event_ids(t: pd.DataFrame, sack: pd.DataFrame, root: Path | None = None) -> pd.Series:
    """sack_row -> the event the DK close was read from: dk_close_check.close_events (the latest DK snapshot >= 5 min
    before its own event's start, over all events joined to the match), not the first joined event."""
    from . import dk_close_check as cc
    from . import dk_history as dh
    need, snaps = cc._need(t, sack, root or dh.CACHE)
    return cc.close_events(need, snaps).set_index("sack_row")["event_id"]


def windows(priced: pd.DataFrame, sack: pd.DataFrame) -> pd.DataFrame:
    """One row per priced match: key, commence (UTC), dur (minutes), season, level, tourney_id, players."""
    s = sack.loc[priced["sack_row"].to_numpy()].reset_index(drop=True)
    w = pd.DataFrame({"key": priced["key"].to_numpy(), "commence": pd.to_datetime(priced["commence"].to_numpy(), utc=True),
                      "minutes": s["minutes"].to_numpy(), "best_of": s["best_of"].to_numpy(),
                      "season": s["season"].to_numpy(), "level": s["level_group"].to_numpy(),
                      "tourney_id": priced["tourney_id"].to_numpy() if "tourney_id" in priced else None,
                      "sack_row": priced["sack_row"].to_numpy(),
                      "pair": [frozenset((pkey(a), pkey(b))) for a, b in
                               zip(s.get("winner", [""] * len(s)), s.get("loser", [""] * len(s)))]})
    med = w.groupby("best_of")["minutes"].median()
    w["dur"] = w["minutes"].fillna(w["best_of"].map(med)).fillna(med.max() if len(med) else 120).clip(upper=MAX_MINUTES)
    return w.drop(columns="minutes")


def slots(w: pd.DataFrame, step_min: int = 5, slack_min: int = 180) -> set:
    """Distinct (key, snapshot time) pairs covering every live window."""
    out = set()
    for k, c, d in zip(w["key"], w["commence"], w["dur"]):
        step = step_min if c >= FIVE_MIN_FROM else max(step_min, 10)
        a = c.floor(f"{step}min")
        for x in pd.date_range(a, c + pd.Timedelta(minutes=float(d) + slack_min), freq=f"{step}min"):
            out.add((k, x))
    return out


def credits(w: pd.DataFrame, step_min: int = 5, slack_min: int = 180) -> int:
    return CREDITS_PER_SNAPSHOT * len(slots(w, step_min, slack_min))


VARIANTS = [("All seasons (2020–May 2026)", None), ("2023–May 2026 (5-min archive)", 2023),
            ("2024–May 2026", 2024), ("2025–May 2026", 2025)]


def plan(w: pd.DataFrame) -> str:
    L = ["| Universe | Matches | 5 min, +1 h slack | 5 min, +3 h slack | 10 min, +1 h | 10 min, +3 h |",
         "|---|---|---|---|---|---|"]
    for name, since in VARIANTS:
        g = w if since is None else w[w["season"] >= since]
        L.append(f"| {name} | {len(g):,} | " + " | ".join(f"{credits(g, st, sl):,}" for st, sl in
                                                          ((5, 60), (5, 180), (10, 60), (10, 180))) + " |")
    by = ["", "By tier, 2023–May 2026, 10 min, +3 h slack:", "", "| Tier | Matches | Credits |", "|---|---|---|"]
    g = w[w["season"] >= 2023]
    for lv, x in g.groupby("level"):
        by.append(f"| {lv} | {len(x):,} | {credits(x, 10, 180):,} |")
    return "\n".join(L + by) + "\n"


# --- staged pull (paid; only with the Lead's go) ------------------------------------------------

def pkey(name) -> str:
    """name_key ignoring apostrophes ("O'Connell" = "Oconnell")."""
    return name_key(str(name).replace("'", "").replace("\u2019", ""))


def _event_id(snapshot: dict, commence: pd.Timestamp, pair: frozenset) -> str | None:
    """The snapshot event for this match: the same two players (a pair meets once per event). DK moves
    commence_time as the order of play shifts, so it only breaks ties (closest start)."""
    hit = [e for e in snapshot.get("data") or []
           if frozenset((pkey(e["home_team"]), pkey(e["away_team"]))) == pair]
    if not hit:
        return None
    hit.sort(key=lambda e: abs((pd.Timestamp(e["commence_time"]) - commence).total_seconds()))
    return hit[0]["id"]


def walk(w: pd.DataFrame, fetch, step_min: int = 10, slack_min: int = 180) -> dict:
    """Walk each key's snapshot times in order; a time is fetched only while some match of that key is in its
    live window and not yet finished. A match is finished after GONE_SNAPSHOTS consecutive snapshots (each at
    least MIN_LIVE_MIN after its commence) without its event; a match whose event is never found (by player
    names) is dropped the same way, since its prices can't be used. A match with a `close_event_id` (the event its DK
    close came from, joined to Sackmann by player ids) uses that event; player names only find the event otherwise
    (DK can list duplicate events for one pairing, and a stale duplicate may be moved a day later). fetch(key, when_iso) -> snapshot dict, or None to
    stop (cap reached). -> {"fetched", "stopped", "matches": per-match frame}."""
    w = w.reset_index(drop=True)
    known = w["close_event_id"] if "close_event_id" in w else pd.Series([None] * len(w), index=w.index)
    st = pd.DataFrame({"event_id": known.astype(object).where(known.notna(), None), "snaps": 0, "gone": 0,
                       "finished_at": pd.Series([pd.NaT] * len(w), dtype="datetime64[ns, UTC]"),
                       "first_seen": pd.Series([pd.NaT] * len(w), dtype="datetime64[ns, UTC]"),
                       "missing": 0}, index=w.index)
    fetched, stopped = 0, False
    for key, g in w.groupby("key", sort=True):
        times = sorted({x for k, x in slots(g, step_min, slack_min)})
        for x in times:
            active = [i for i in g.index if g.at[i, "commence"].floor(f"{step_min}min") <= x
                      <= g.at[i, "commence"] + pd.Timedelta(minutes=float(g.at[i, "dur"]) + slack_min)
                      and pd.isna(st.at[i, "finished_at"])]
            if not active:
                continue
            snap = fetch(key, x.strftime("%Y-%m-%dT%H:%M:%SZ"))
            if snap is None:
                stopped = True
                break
            if snap.get("missing"):                   # cache-only replay: not pulled, so unknown, not "gone"
                for i in active:
                    st.at[i, "missing"] += 1
                continue
            fetched += 1
            ids = {e["id"] for e in snap.get("data") or []}
            for i in active:
                if st.at[i, "event_id"] is None:
                    st.at[i, "event_id"] = _event_id(snap, g.at[i, "commence"], g.at[i, "pair"])
                eid = st.at[i, "event_id"]
                if eid is None and x >= g.at[i, "commence"] + pd.Timedelta(minutes=MIN_LIVE_MIN):
                    st.at[i, "gone"] += 1               # never found: stop paying for it, too
                    if st.at[i, "gone"] >= GONE_SNAPSHOTS:
                        st.at[i, "finished_at"] = x
                    continue
                if eid in ids:
                    st.at[i, "snaps"] += 1
                    st.at[i, "gone"] = 0
                    if pd.isna(st.at[i, "first_seen"]):
                        st.at[i, "first_seen"] = x
                elif eid is not None and x >= g.at[i, "commence"] + pd.Timedelta(minutes=MIN_LIVE_MIN):
                    st.at[i, "gone"] += 1
                    if st.at[i, "gone"] >= GONE_SNAPSHOTS:
                        st.at[i, "finished_at"] = x
        if stopped:
            break
    return {"fetched": fetched, "stopped": stopped, "matches": pd.concat([w, st], axis=1)}


def walk_recent_first(w: pd.DataFrame, fetch, step_min: int = 10, slack_min: int = 180) -> dict:
    """walk() one season at a time, newest first, so a cap stop loses the oldest seasons."""
    parts, fetched = [], 0
    for season in sorted(w["season"].unique(), reverse=True):
        res = walk(w[w["season"] == season], fetch, step_min, slack_min)
        parts.append(res["matches"])
        fetched += res["fetched"]
        print(f"[season {season}: {res['fetched']:,} snapshots; matches {len(res['matches']):,}, event found "
              f"{int(res['matches']['event_id'].notna().sum()):,}]", flush=True)
        if res["stopped"]:
            return {"fetched": fetched, "stopped": True, "matches": pd.concat(parts, ignore_index=True)}
    return {"fetched": fetched, "stopped": False,
            "matches": pd.concat(parts, ignore_index=True) if parts else w.iloc[:0]}


def pilot_stats(m: pd.DataFrame, snaps: list[dict], planned: int, spent: float) -> str:
    """Pilot report: coverage, stop-on-finish, live window and quote freshness. No outcomes are read."""
    ages, live_rows = {b: [] for b in BOOKS}, 0
    ids = {e: c for e, c in zip(m["event_id"], m["commence"]) if e}
    for s in snaps:
        ts = pd.Timestamp(s["timestamp"])
        for e in s.get("data") or []:
            if e["id"] in ids and ts >= ids[e["id"]] + pd.Timedelta(minutes=MIN_LIVE_MIN):
                live_rows += 1
                for b in e.get("bookmakers") or []:
                    if b["key"] in ages:
                        ages[b["key"]].append((ts - pd.Timestamp(b["last_update"])).total_seconds() / 60)
    fin = m["finished_at"].notna()
    span = ((m.loc[fin, "finished_at"] - m.loc[fin, "commence"]).dt.total_seconds() / 60)
    L = [f"matches {len(m)}; event resolved {int(m['event_id'].notna().sum())}; seen in-play "
         f"{int((m['snaps'] > 0).sum())}; finish detected {int(fin.sum())}",
         f"credits spent {spent:,.0f} vs planned (+3 h slack, no stop) {planned:,}; per match "
         f"{spent / max(len(m), 1):,.0f} vs {planned / max(len(m), 1):,.0f}",
         f"commence -> finish detected (min): median {span.median():.0f}, p10 {span.quantile(0.1):.0f}, "
         f"p90 {span.quantile(0.9):.0f}" if fin.any() else "no finish detected",
         f"in-play event rows (>= {MIN_LIVE_MIN} min after commence): {live_rows}"]
    for b, a in ages.items():
        a = np.array(a)
        L.append(f"{b}: quoted on {len(a)} in-play rows; quote age min median "
                 f"{np.median(a):.1f}, p90 {np.quantile(a, 0.9):.1f}; <= 5 min {np.mean(a <= 5):.0%}" if len(a)
                 else f"{b}: not quoted in play")
    return "\n".join(L)


RETRY_WAITS_S = (10, 30)   # a 5xx or a network error is retried after these pauses, then the stage stops


# --- the in-play window (reports/upsets_dk_inplay.md, amendment 2026-10-28) ---------------------------------

LIVE_AFTER_MIN = 15        # (a) in play from the start listed in that same snapshot + this
STALE_MIN = 15             # (b) the DK quote must have updated within this
SETTLED_LO, SETTLED_HI = 1.01, 50.0   # (c) a DK price at or beyond these ends the window (that snapshot too)
MAX_LIVE_H = 6             # (d) no later than the listed start + this


def quotes(m: pd.DataFrame, roots=None) -> pd.DataFrame:
    """One row per (match, cached snapshot that lists its event): listed start in that snapshot, DK and Pinnacle
    h2h odds by home/away with last_update. m = walk()'s matches (key, event_id). Reads one file at a time."""
    from . import dk_history as dh
    roots = roots or (INPLAY_CACHE, dh.CACHE)
    want = m.dropna(subset=["event_id"]).reset_index().rename(columns={"index": "match"})
    rows = []
    for key, g in want.groupby("key"):
        ids = dict(zip(g["event_id"], g["match"]))
        lo, hi = g["commence"].min() - pd.Timedelta(hours=1), g["commence"].max() + pd.Timedelta(days=3)
        seen = set()
        for root in roots:
            for f in sorted((Path(root) / "odds" / key).glob("*.json.gz")):
                if f.name in seen:
                    continue
                ts_guess = pd.Timestamp(f.name.split(".")[0], tz="UTC")
                if not lo <= ts_guess <= hi:
                    continue
                seen.add(f.name)
                b = dh.read_cache(f)
                ts = pd.Timestamp(b["timestamp"])
                for e in b.get("data") or []:
                    if e["id"] not in ids:
                        continue
                    r = {"match": ids[e["id"]], "ts": ts, "listed_start": pd.Timestamp(e["commence_time"]),
                         "home": e["home_team"], "away": e["away_team"]}
                    for bk in e.get("bookmakers") or []:
                        if bk["key"] not in BOOKS:
                            continue
                        o = {x["name"]: x["price"] for mk in bk["markets"] if mk["key"] == "h2h"
                             for x in mk["outcomes"]}
                        r[f"{bk['key']}_home"] = o.get(e["home_team"])
                        r[f"{bk['key']}_away"] = o.get(e["away_team"])
                        r[f"{bk['key']}_updated"] = pd.Timestamp(bk["last_update"])
                    rows.append(r)
    q = pd.DataFrame(rows)
    if not len(q):
        return q
    for b in BOOKS:
        for c in ("home", "away"):
            if f"{b}_{c}" not in q:
                q[f"{b}_{c}"] = np.nan
        if f"{b}_updated" not in q:
            q[f"{b}_updated"] = pd.NaT
    return q.drop_duplicates(["match", "ts"]).sort_values(["match", "ts"]).reset_index(drop=True)


def window(q: pd.DataFrame, minutes: pd.Series | None = None) -> pd.DataFrame:
    """Flags per quote row (no outcome is read):
    - live: the pre-registered in-play rule, rules (a)-(d) (causal: only what that snapshot and earlier showed);
    - live_minutes: robustness, live and ts <= listed start + Sackmann minutes + 30 min (uses the match's duration);
    - live_final: sensitivity, live and ts >= the match's final listed start + LIVE_AFTER_MIN (uses later information;
      descriptive only, never a gate input)."""
    q = q.copy()
    a = q["ts"] >= q["listed_start"] + pd.Timedelta(minutes=LIVE_AFTER_MIN)
    b = q["draftkings_updated"].notna() & (q["ts"] - q["draftkings_updated"] <= pd.Timedelta(minutes=STALE_MIN))
    lo = q[["draftkings_home", "draftkings_away"]].min(axis=1)
    hi = q[["draftkings_home", "draftkings_away"]].max(axis=1)
    settled = ((lo <= SETTLED_LO) | (hi >= SETTLED_HI)) & a
    c = ~settled.astype(int).groupby(q["match"]).cummax().astype(bool)     # that snapshot and all later ones out
    d = q["ts"] <= q["listed_start"] + pd.Timedelta(hours=MAX_LIVE_H)
    q["live"] = a & b & c & d
    if "close_start" in q:   # variant: (a) and (c) anchored on the start listed at the close (known in advance)
        a2 = q["ts"] >= q["close_start"] + pd.Timedelta(minutes=LIVE_AFTER_MIN)
        settled2 = ((lo <= SETTLED_LO) | (hi >= SETTLED_HI)) & a2
        c2 = ~settled2.astype(int).groupby(q["match"]).cummax().astype(bool)
        d2 = q["ts"] <= q["close_start"] + pd.Timedelta(hours=MAX_LIVE_H)
        q["live_close"] = a2 & b & c2 & d2
        # (a‴) causal: also require the snapshot's own listed start to have stopped leap-frogging (<= its time)
        q["live_started"] = q["live_close"] & (q["listed_start"] <= q["ts"])
    if minutes is not None:
        mm = q["match"].map(minutes)
        q["live_minutes"] = q["live"] & mm.notna() & (q["ts"] <= q["listed_start"] + pd.to_timedelta(mm + 30, unit="m"))
    final = q.groupby("match")["listed_start"].transform("last")
    q["live_final"] = q["live"] & (q["ts"] >= final + pd.Timedelta(minutes=LIVE_AFTER_MIN))
    return q


def cache_fetch(misses: list):
    """walk() fetch that only reads the caches (0 credits); a snapshot we never pulled is returned as missing
    (walk() then counts it per active match and treats it as unknown, not as the event being gone) and recorded."""
    from . import dk_history as dh

    def fetch(key, when):
        for root in (INPLAY_CACHE, dh.CACHE):
            p = dh.cache_path("odds", key, when, root)
            if p.exists():
                return dh.read_cache(p)
        misses.append((key, when))
        return {"timestamp": when, "data": [], "missing": True}
    return fetch


def subset_table(m: pd.DataFrame, f: pd.DataFrame, col: str = "live_started") -> str:
    """Matches DK quoted in play (by `col`) vs the rest, on pre-match data only: tier mix, the dog's DK close odds and
    the Elo gap (dk_study.frame's columns). Never reads results."""
    x = m[["sack_row", "season", col]].merge(
        f[["sack_row", "level_group", "odds_dog_dk", "elo_dog", "elo_fav"]], on="sack_row", how="left")
    x["elo_gap"] = x["elo_fav"] - x["elo_dog"]
    L = ["| Season | Quoted in play | Matches | Slam | 1000 | 250/500 | Dog's DK close odds (median) | "
         "Elo gap (median) |", "|---|---|---|---|---|---|---|---|"]
    for (season, live), g in x.groupby(["season", col]):
        lv = g["level_group"].value_counts(normalize=True)
        L.append(f"| {season} | {'yes' if live else 'no'} | {len(g):,} | {lv.get('slam', 0):.0%} | {lv.get('1000', 0):.0%} | "
                 f"{lv.get('other', 0):.0%} | {g['odds_dog_dk'].median():.2f} | {g['elo_gap'].median():.0f} |")
    return "\n".join(L)


def coverage(w: pd.DataFrame, minutes: pd.Series, step_min: int = 10, slack_min: int = 180,
             f: pd.DataFrame | None = None) -> tuple[str, pd.DataFrame]:
    """Replay the pull from cache, apply window(), count matches each rule keeps (split by finish detected), and
    plan the refinement for postponed matches (final listed start past our pulled window). No outcomes."""
    misses: list = []
    m = walk(w, cache_fetch(misses), step_min, slack_min)["matches"].reset_index(drop=True)
    mins = pd.Series(minutes.to_numpy(), index=range(len(m)))
    q = quotes(m)
    q["close_start"] = q["match"].map(m["commence"])
    q = window(q, mins)
    # Pinnacle's own close (last quote >= 5 min before the close's listed start) vs each snapshot, by home side:
    # real in-play prices move, pre-match ones mostly don't. Prices only, no results.
    ph = (1 / q["pinnacle_home"]) / (1 / q["pinnacle_home"] + 1 / q["pinnacle_away"])
    pre = q[q["ts"] <= q["close_start"] - pd.Timedelta(minutes=5)].assign(ph=ph)
    p0 = pre.groupby("match")["ph"].last()
    q["pin_moved"] = (ph - q["match"].map(p0)).abs() > 0.05
    per = q.groupby("match").agg(live=("live", "any"), live_close=("live_close", "any"),
                                 live_started=("live_started", "any"),
                                 live_minutes=("live_minutes", "any"),
                                 live_final=("live_final", "any"), final_start=("listed_start", "last"),
                                 last_ts=("ts", "max"))
    m = m.join(per)
    cols = ["live", "live_close", "live_started", "live_minutes", "live_final"]
    m[cols] = m[cols].fillna(False).astype(bool)
    m["finished"] = m["finished_at"].notna()
    # postponed = the close's event was later listed for a start > 1 h after the close's and our pull ended before it
    # (an event that simply stops being listed at the start is not postponed: DK offered no in-play market for it)
    m["postponed"] = (m["final_start"].notna() & (m["final_start"] > m["commence"] + pd.Timedelta(hours=1))
                      & (m["final_start"] > m["last_ts"] - pd.Timedelta(minutes=LIVE_AFTER_MIN)))
    L = ["| Season | Stopped (finish seen or event never found) | Matches | Event found | In play, rules (a)–(d) | "
         "(a)–(d) from the close's listed start | + Sackmann-minutes cut | + final-start cut (later info) | "
         "Postponed past our window |", "|---|---|---|---|---|---|---|---|---|"]
    for (season, fin), g in m.groupby(["season", "finished"]):
        L.append(f"| {season} | {'yes' if fin else 'no'} | {len(g):,} | {int(g['event_id'].notna().sum()):,} | "
                 f"{int(g['live'].sum()):,} | {int(g['live_close'].sum()):,} | {int(g['live_minutes'].sum()):,} | "
                 f"{int(g['live_final'].sum()):,} | "
                 f"{int(g['postponed'].sum()):,} |")
    pp = m[m["postponed"]].assign(commence=lambda x: x["final_start"])
    plan_credits = credits(pp, step_min, slack_min) if len(pp) else 0
    L += ["", "| Season | Matches | (a) listed start in that snapshot | (a′) close's listed start | "
          "(a‴) (a′) + listing stopped moving | (a‴) / (a′) | Pinnacle moved > 5 pp: (a) / (a′) / (a‴) |",
          "|---|---|---|---|---|---|---|"]
    q["season"] = q["match"].map(m["season"])
    for season, g in m.groupby("season"):
        qs = q[q["season"] == season]
        sh = [qs.loc[qs[v], "pin_moved"].mean() for v in ("live", "live_close", "live_started")]
        L.append(f"| {season} | {len(g):,} | {int(g['live'].sum()):,} | {int(g['live_close'].sum()):,} | "
                 f"{int(g['live_started'].sum()):,} | {g['live_started'].sum() / max(g['live_close'].sum(), 1):.0%} | "
                 + " / ".join(f"{x:.0%}" for x in sh) + " |")
    short = m[m["missing"] > 0]
    L += ["", f"Coverage of the real (close) event: {len(short):,} of {len(m):,} matches need snapshots we never pulled "
          f"(the pull's start/stop followed the name-matched listing); re-walking them costs {10 * len(set(misses)):,} "
          f"credits ({len(set(misses)):,} snapshots). By season: "
          + ", ".join(f"{s} {int((g['missing'] > 0).sum())}" for s, g in m.groupby("season")) + "."]
    if f is not None:
        L += ["", "Matches DK quoted in play under (a‴) vs the rest (pre-match data only):", "", subset_table(m, f)]
    L += ["", f"Refinement plan for postponed matches: {len(pp):,} matches re-walked from their final listed start at "
          f"{step_min} min, planned <= {plan_credits:,} credits (not run; needs the Lead's approval). Cache misses in the "
          f"replay: {len(misses)}."]
    return "\n".join(L), m


def make_fetch(api, log: Path, cap: float, stage_budget: float | None = None, keep: list | None = None,
               pause_s: float = 0.2, retry_waits_s=RETRY_WAITS_S):
    """fetch(key, when) for walk(): cached snapshots first (in-play cache, then the close studies' cache, read
    only); else one paid call, unless it would take this job's spend log past `cap`, or this stage's spend past
    `stage_budget` (the per-match drift stop), in which case it returns None (walk stops). fetch.why says which.
    A server error (5xx) or a network error is retried after each of `retry_waits_s`; if it persists the stage
    stops the same way (cached snapshots make a re-run free up to that point). A 4xx is never retried."""
    from . import dk_history as dh
    start = dh.logged_total(log)

    def fetch(key, when):
        p = dh.cache_path("odds", key, when, INPLAY_CACHE)
        old = dh.cache_path("odds", key, when)
        if p.exists() or old.exists():
            body = dh.read_cache(p if p.exists() else old)
        else:
            total = dh.logged_total(log)
            if total + CREDITS_PER_SNAPSHOT > cap:
                fetch.why = "job cap"
                return None
            if stage_budget is not None and total - start + CREDITS_PER_SNAPSHOT > stage_budget:
                fetch.why = "per-match drift budget"
                return None
            body = None
            for wait in (*retry_waits_s, None):
                try:
                    body = api.historical_odds(key, when, bookmakers=BOOKS)
                    break
                except requests.RequestException as e:
                    code = getattr(getattr(e, "response", None), "status_code", None)
                    if (code is not None and code < 500) or wait is None:
                        fetch.why = f"API error ({type(e).__name__}{f' {code}' if code else ''})"
                        return None
                    time.sleep(wait)
            dh.write_cache(p, body)
            time.sleep(pause_s)
        if keep is not None:
            keep.append(body)
        return body
    fetch.why = None
    return fetch


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["plan", "pull", "window"])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    ap.add_argument("--pilot", default=None, help="KEY:TOURNEY_ID, one tournament only")
    ap.add_argument("--since", type=int, default=2023, help="first season of the full pull")
    ap.add_argument("--season", type=int, default=None, help="one stage: this season only")
    ap.add_argument("--per-match-max", type=float, default=None,
                    help="stop the stage once it spends more than this x its matches (drift stop)")
    ap.add_argument("--step", type=int, default=10)
    ap.add_argument("--slack", type=int, default=180)
    ap.add_argument("--cap", type=float, required=False, default=0, help="max credits in this job's spend log")
    ap.add_argument("--floor", type=int, default=5000)
    ap.add_argument("--yes", action="store_true", help="required for the paid pull")
    a = ap.parse_args(argv)
    from . import dk_history as dh
    from . import elo, sackmann
    sack = sackmann.load(a.sackmann, start=1990, lower=True)
    t = dh.tournaments(sack, dh._keys(), hist_start={**dh.HIST_START, "other": pd.Timestamp("2024-01-01")})
    priced = dh.collect(t, elo.add_elo(sack, keys=("winner_id", "loser_id")), 24.0)
    w = windows(priced, sack)
    if a.cmd in ("pull", "window"):
        w["close_event_id"] = close_event_ids(t, sack).reindex(priced["sack_row"].to_numpy()).to_numpy()
    if a.cmd == "plan":
        print(plan(w))
        return
    if a.cmd == "window":
        mins = sack.loc[priced["sack_row"].to_numpy(), "minutes"].reset_index(drop=True)
        keep = (w["season"] >= a.since).to_numpy()
        from . import dk_study as ds
        f = ds.frame(priced, elo.add_elo(sack, keys=("winner_id", "loser_id")))
        text, _ = coverage(w[keep].reset_index(drop=True), mins[keep].reset_index(drop=True), a.step, a.slack, f)
        print(text)
        return
    if a.pilot:
        key, tid = a.pilot.split(":", 1)
        w = w[(w["key"] == key) & (w["tourney_id"].astype(str) == tid)]
    elif a.season is not None:
        w = w[w["season"] == a.season]
    else:
        w = w[w["season"] >= a.since]
    planned = credits(w, a.step, a.slack)
    print(f"[dk_inplay pull: {len(w):,} matches, planned <= {planned:,} credits at {a.step} min, cap {a.cap:,.0f}]")
    if not a.yes or a.cap <= 0:
        raise SystemExit("paid: re-run with --cap and --yes once the Lead has approved.")
    from .odds_api import OddsApi
    log = INPLAY_CACHE / "spend.log"
    api = OddsApi(floor=a.floor, spend_log=log)
    api.sports()                    # free: the balance, for the stage's floor check
    start = dh.logged_total(log)
    if api.remaining - min(planned, max(a.cap - start, 0)) < a.floor:
        raise SystemExit(f"this stage could take the balance below the floor {a.floor:,}: stopped before any call")
    got = [] if a.pilot else None   # the pilot's freshness check reads bodies back; a full pull wouldn't fit in memory
    budget = a.per_match_max * len(w) if a.per_match_max else None
    fetch = make_fetch(api, log, a.cap, budget, got)
    res = walk(w, fetch, a.step, a.slack) if (a.pilot or a.season is not None) else \
        walk_recent_first(w, fetch, a.step, a.slack)
    used = dh.logged_total(log) - start
    print(f"[fetched {res['fetched']:,} snapshots; credits this stage {used:,.0f} ({used / max(len(w), 1):.1f}/match, "
          f"planned {planned / max(len(w), 1):.1f}); job total {dh.logged_total(log):,.0f}"
          + (f"; STOPPED: {fetch.why}" if res["stopped"] else "") + "]")
    if a.pilot:
        print(pilot_stats(res["matches"], got, planned, api.spent))
    else:
        m = res["matches"]
        print(f"[matches {len(m):,}; event found {int(m['event_id'].notna().sum()):,}; seen in play "
              f"{int((m['snaps'] > 0).sum()):,}; finish detected {int(m['finished_at'].notna().sum()):,}]")


if __name__ == "__main__":
    main()
