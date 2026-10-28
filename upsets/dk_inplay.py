"""DraftKings in-play studies (DOG50, exit-level curve, MISMATCH50, FAVDIP on DK prices): credit dry run.
Plan only, pre-registered in reports/upsets_dk_inplay.md. This module makes no paid call.

    python -m upsets.dk_inplay plan [--sackmann PATH]
    python -m upsets.dk_inplay pull --pilot KEY:TOURNEY_ID --cap 2000 --yes    # paid, staged (Lead's go)

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


def windows(priced: pd.DataFrame, sack: pd.DataFrame) -> pd.DataFrame:
    """One row per priced match: key, commence (UTC), dur (minutes), season, level, tourney_id, players."""
    s = sack.loc[priced["sack_row"].to_numpy()].reset_index(drop=True)
    w = pd.DataFrame({"key": priced["key"].to_numpy(), "commence": pd.to_datetime(priced["commence"].to_numpy(), utc=True),
                      "minutes": s["minutes"].to_numpy(), "best_of": s["best_of"].to_numpy(),
                      "season": s["season"].to_numpy(), "level": s["level_group"].to_numpy(),
                      "tourney_id": priced["tourney_id"].to_numpy() if "tourney_id" in priced else None,
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
    names) is dropped the same way, since its prices can't be used. fetch(key, when_iso) -> snapshot dict, or None to
    stop (cap reached). -> {"fetched", "stopped", "matches": per-match frame}."""
    w = w.reset_index(drop=True)
    st = pd.DataFrame({"event_id": pd.Series([None] * len(w), dtype=object), "snaps": 0, "gone": 0,
                       "finished_at": pd.Series([pd.NaT] * len(w), dtype="datetime64[ns, UTC]"),
                       "first_seen": pd.Series([pd.NaT] * len(w), dtype="datetime64[ns, UTC]")}, index=w.index)
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


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["plan", "pull"])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    ap.add_argument("--pilot", default=None, help="KEY:TOURNEY_ID, one tournament only")
    ap.add_argument("--since", type=int, default=2023, help="first season of the full pull")
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
    if a.cmd == "plan":
        print(plan(w))
        return
    if a.pilot:
        key, tid = a.pilot.split(":", 1)
        w = w[(w["key"] == key) & (w["tourney_id"].astype(str) == tid)]
    else:
        w = w[w["season"] >= a.since]
    planned = credits(w, a.step, a.slack)
    print(f"[dk_inplay pull: {len(w):,} matches, planned <= {planned:,} credits at {a.step} min, cap {a.cap:,.0f}]")
    if not a.yes or a.cap <= 0:
        raise SystemExit("paid: re-run with --cap and --yes once the Lead has approved.")
    from .odds_api import OddsApi
    log = INPLAY_CACHE / "spend.log"
    api = OddsApi(floor=a.floor, spend_log=log)
    got = []

    def fetch(key, when):
        p = dh.cache_path("odds", key, when, INPLAY_CACHE)
        old = dh.cache_path("odds", key, when)       # the close studies' cache: read, never written
        if p.exists() or old.exists():
            body = dh.read_cache(p if p.exists() else old)
        else:
            if dh.logged_total(log) + 10 > a.cap:
                return None
            body = api.historical_odds(key, when, bookmakers=BOOKS)
            dh.write_cache(p, body)
            time.sleep(0.2)
        got.append(body)
        return body
    res = walk(w, fetch, a.step, a.slack)
    print(f"[fetched {res['fetched']:,} snapshots; spent this run {api.spent:,.0f}; job total "
          f"{dh.logged_total(log):,.0f}" + ("; STOPPED at the cap" if res["stopped"] else "") + "]")
    print(pilot_stats(res["matches"], got, planned, api.spent))


if __name__ == "__main__":
    main()
