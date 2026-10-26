"""DraftKings (and Pinnacle) historical tennis odds for rounds 1-2 of Slams and 1000s, via The
Odds API: plan, pull (cached, capped) and turn into one bettable price per Sackmann match.

    python -m upsets.dk_history plan [--sackmann PATH]     # dry run: calls + credits, 0 paid calls
    python -m upsets.dk_history events --yes                # paid: historical event listings (1 cr each)
    python -m upsets.dk_history plan                        # dry run again: now exact odds snapshots
    python -m upsets.dk_history odds --yes                  # paid: odds snapshots (10 cr each)

Stages:
1. Tournaments: tennis keys (free /v4/sports?all=true) mapped to Sackmann events by name, tour and
   year. Slams from 2020, 1000s from 2024 (the API's history starts 2020-06 / 2024-25), events that
   started by the Sackmann end date. A key/year without history just returns empty (0 credits).
2. Event listings: /historical/sports/{key}/events every `events_step_h` hours over each event's
   round 1-2 window (from the Sackmann start date and draw size). Gives commence times.
3. Listed events are joined to Sackmann matches (names + pair); only rounds 1-2 need a price.
   Each needs a snapshot at or before deadline = commence - `lead_min`. Deadlines are grouped into
   `snap_h`-hour cells per key; each cell gets one snapshot at its earliest deadline, so a match's
   price is at most `snap_h` hours (+ the API's 5-10 min snapshot step) older than its deadline.
4. Odds: /historical/sports/{key}/odds?date= (10 credits; draftkings + pinnacle = 1 region block).

Every response is cached gzipped under data/raw/odds_api/ by (endpoint, key, date), so no paid
call is ever repeated and a pull resumes where it stopped. Every call goes through OddsApi (floor,
spend log); `cap` stops the pull before its logged total would pass the budget. Odds data never
leaves data/ (gitignored): The Odds API terms forbid redistribution.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import kalshi_elo as ke
from . import sackmann
from .odds_api import parse_h2h

CACHE = Path("data/raw/odds_api")
BOOKS = ("draftkings", "pinnacle")
HIST_START = {"slam": pd.Timestamp("2020-06-06"), "1000": pd.Timestamp("2024-01-01")}

# key suffix -> Sackmann tournament names (both tours); the level filter keeps Slams + 1000s only
KEY_NAMES = {
    "aus_open_singles": ["Australian Open"], "french_open": ["Roland Garros"],
    "wimbledon": ["Wimbledon"], "us_open": ["Us Open", "US Open"],
    "indian_wells": ["Indian Wells Masters", "Indian Wells"], "miami_open": ["Miami Masters", "Miami"],
    "madrid_open": ["Madrid Masters", "Madrid"], "italian_open": ["Rome Masters", "Rome"],
    "canadian_open": ["Canada Masters", "Montreal", "Toronto"],
    "cincinnati_open": ["Cincinnati Masters", "Cincinnati"],
    "shanghai_masters": ["Shanghai Masters"], "paris_masters": ["Paris Masters"],
    "monte_carlo_masters": ["Monte Carlo Masters"], "china_open": ["Beijing"],
    "wuhan_open": ["Wuhan"], "dubai": ["Dubai"], "qatar_open": ["Doha"],
    # 250/500 keys (in scope only with levels including "other")
    "barcelona_open": ["Barcelona"], "halle_open": ["Halle"], "hamburg_open": ["Hamburg"],
    "japan_open": ["Tokyo"], "munich": ["Munich"], "queens_club_champ": ["Queen's Club"],
    "washington_open": ["Washington"], "bad_homburg_open": ["Bad Homburg"],
    "charleston_open": ["Charleston"], "german_open": ["Berlin"], "guadalajara_open": ["Guadalajara"],
    "monterrey_open": ["Monterrey"], "ningbo_open": ["Ningbo"], "singapore_open": ["Singapore"],
    "strasbourg": ["Strasbourg"], "stuttgart_open": ["Stuttgart"],
}


# Every tennis key /v4/sports?all=true listed on 2026-10-26 (free call); used by --offline-keys.
LISTED_KEYS = tuple(f"tennis_{k}" for k in """
atp_aus_open_singles atp_barcelona_open atp_canadian_open atp_china_open atp_cincinnati_open atp_dubai
atp_french_open atp_halle_open atp_hamburg_open atp_indian_wells atp_italian_open atp_japan_open
atp_madrid_open atp_miami_open atp_monte_carlo_masters atp_munich atp_paris_masters atp_qatar_open
atp_queens_club_champ atp_shanghai_masters atp_us_open atp_washington_open atp_wimbledon
wta_aus_open_singles wta_bad_homburg_open wta_canadian_open wta_charleston_open wta_china_open
wta_cincinnati_open wta_dubai wta_french_open wta_german_open wta_guadalajara_open wta_indian_wells
wta_italian_open wta_madrid_open wta_miami_open wta_monterrey_open wta_ningbo_open wta_qatar_open
wta_queens_club_champ wta_singapore_open wta_strasbourg wta_stuttgart_open wta_us_open
wta_washington_open wta_wimbledon wta_wuhan_open""".split())


# --- cache -----------------------------------------------------------------------------------

def cache_path(kind: str, key: str, when: str, root: Path = CACHE) -> Path:
    return root / kind / key / (re.sub(r"[^0-9TZ]", "", when) + ".json.gz")


def read_cache(path: Path):
    with gzip.open(path, "rt") as f:
        return json.load(f)


def write_cache(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt") as f:
        json.dump(obj, f)
    tmp.replace(path)


def iso(ts: pd.Timestamp) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- stage 1: tournaments --------------------------------------------------------------------

def tournaments(sack: pd.DataFrame, keys: list[str], end: pd.Timestamp | None = None,
                hist_start: dict | None = None, project_until: pd.Timestamp | None = None) -> pd.DataFrame:
    """One row per (key, Sackmann event) in scope, with the round 1-2 window (UTC days).

    hist_start: level_group -> first date with history (default HIST_START: Slams + 1000s only;
    add "other" for the 250/500 keys). project_until: also plan events after Sackmann's end by
    shifting the previous year's edition +52 weeks (projected=True; their results must come from
    elsewhere, e.g. Kalshi settlements)."""
    hist_start = hist_start or HIST_START
    main = sack[sack["level_group"].isin(hist_start)]
    # Sackmann gives a Slam the same tourney_id on both tours: key events by (tour, tourney_id)
    ev = (main.groupby(["tour", "tourney_id"])
          .agg(name=("tournament", "first"), date=("date", "first"),
               draw=("draw_size", "max"), level_group=("level_group", "first"),
               n_r12=("round_idx", lambda x: int((x <= 2).sum())))
          .reset_index())
    ev["projected"] = False
    last = sack["date"].max()
    end = end if end is not None else last
    if project_until is not None:
        # next edition of events from the year before Sackmann's end, not yet in the data
        prev = ev[(ev["date"] > last - pd.Timedelta(days=365)) & (ev["date"] + pd.Timedelta(weeks=52) > last)]
        nxt = prev.assign(date=prev["date"] + pd.Timedelta(weeks=52), projected=True,
                          tourney_id=prev["tourney_id"] + "+52w")
        nxt = nxt[nxt["date"] <= project_until]
        have = set(zip(ev["tour"], ev["name"], ev["date"].dt.year))
        nxt = nxt[[(t, n, d.year) not in have for t, n, d in zip(nxt["tour"], nxt["name"], nxt["date"])]]
        ev = pd.concat([ev, nxt], ignore_index=True)
        end = max(end, project_until)
    rows = []
    for key in keys:
        m = re.match(r"tennis_(atp|wta)_(.+)$", key)
        if not m or m.group(2) not in KEY_NAMES:
            continue
        tour, names = m.group(1), [n.lower() for n in KEY_NAMES[m.group(2)]]
        hit = ev[(ev["tour"] == tour) & ev["name"].str.lower().isin(names)]
        for r in hit.itertuples():
            if r.date < hist_start[r.level_group] or r.date > end:
                continue
            # Round 1-2 play days around Sackmann's start date (a Slam's Monday, a 1000's first
            # day): Slams Sun -> Fri, 96/128 draws 4 days, 56/64 draws 3 days; one spare day
            # before for early listings
            slam, big = r.level_group == "slam", r.draw >= 96
            first, last = (-2, 5) if slam else ((-1, 5) if big else (-1, 3))
            if r.projected:  # real dates unknown (shifted +52 w; 2026 events often a week later):
                first, last = first - 7, last + 10  # look either side; empty listings cost 0
            days = 5 if slam else (4 if big or (r.level_group == "other" and r.draw >= 48) else 3)
            rows.append({"key": key, "tourney_id": r.tourney_id, "tour": tour, "name": r.name,
                         "date": r.date, "draw": r.draw, "level_group": r.level_group,
                         "season": r.date.year, "projected": r.projected, "n_r12": r.n_r12,
                         "win_start": r.date + pd.Timedelta(days=first),
                         "win_end": r.date + pd.Timedelta(days=last),
                         "r12_days": days})
    if not rows:
        return pd.DataFrame(columns=["key", "tourney_id", "tour", "name", "date", "draw", "level_group",
                                     "season", "projected", "n_r12", "win_start", "win_end", "r12_days"])
    return pd.DataFrame(rows).sort_values(["date", "key"]).reset_index(drop=True)


# --- stage 2: event listings -----------------------------------------------------------------

def events_schedule(t: pd.DataFrame, step_h: float = 24.0) -> pd.DataFrame:
    """key, tourney_id, when (ISO): listing calls every step_h hours over each window."""
    rows = []
    for r in t.itertuples():
        for ts in pd.date_range(r.win_start, r.win_end, freq=pd.Timedelta(hours=step_h)):
            rows.append({"key": r.key, "tourney_id": r.tourney_id, "when": iso(ts)})
    return pd.DataFrame(rows, columns=["key", "tourney_id", "when"])


def load_events(sched: pd.DataFrame, root: Path = CACHE) -> pd.DataFrame:
    """Cached listings -> one row per event id: latest-listed commence time, players."""
    rows = []
    for r in sched.itertuples():
        p = cache_path("events", r.key, r.when, root)
        if not p.exists():
            continue
        body = read_cache(p)
        for e in body.get("data") or []:
            rows.append({"key": r.key, "tourney_id": r.tourney_id, "event_id": e["id"],
                         "listed": body.get("timestamp") or r.when,
                         "commence": e["commence_time"], "home": e["home_team"], "away": e["away_team"]})
    cols = ["key", "tourney_id", "event_id", "listed", "commence", "home", "away"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)
    df["listed"] = pd.to_datetime(df["listed"], utc=True).dt.tz_localize(None)
    df["commence"] = pd.to_datetime(df["commence"], utc=True).dt.tz_localize(None)
    return df.sort_values("listed").drop_duplicates(["key", "event_id"], keep="last").reset_index(drop=True)


# --- stage 3: join to Sackmann, snapshot plan ------------------------------------------------

def join_events(ev: pd.DataFrame, sack: pd.DataFrame, players: pd.DataFrame | None = None) -> pd.DataFrame:
    """Listed events -> Sackmann row (same tour + tourney_id, same two player ids). Adds sack_row
    (-1 if none), round_idx, id_home, id_away."""
    ev = ev.copy()
    if not len(ev):
        return ev.assign(sack_row=pd.Series(dtype=int), round_idx=pd.Series(dtype=float))
    players = players if players is not None else ke.player_table(sack)
    ev["tour"] = ev["key"].str.extract(r"tennis_(atp|wta)_")[0]
    since = ev["commence"].min() - pd.Timedelta(days=730)
    for side in ("home", "away"):
        ev[f"id_{side}"] = ke.match_names(ev[side], ev["tour"], players, since)["id"]
    pair = lambda a, b: np.where(a < b, a + "|" + b, b + "|" + a)  # noqa: E731
    s = sack[sack["tourney_id"].isin(ev["tourney_id"].unique()) & sack["tour"].isin(ev["tour"].unique())]
    sp = pd.DataFrame({"sack_row": s.index, "tour": s["tour"], "tourney_id": s["tourney_id"],
                       "pair": pair(s["winner_id"].astype(str), s["loser_id"].astype(str)),
                       "round_idx": s["round_idx"]})
    ok = ev["id_home"].notna() & ev["id_away"].notna()
    ev["pair"] = None
    ev.loc[ok, "pair"] = pair(ev.loc[ok, "id_home"].astype(str), ev.loc[ok, "id_away"].astype(str))
    j = ev.merge(sp.drop_duplicates(["tour", "tourney_id", "pair"]), on=["tour", "tourney_id", "pair"],
                 how="left")
    j["sack_row"] = j["sack_row"].fillna(-1).astype(int)
    return j


def needed(j: pd.DataFrame, t: pd.DataFrame | None = None, early_rounds: int = 2,
           margin_days: int = 2) -> pd.Series:
    """Events that need a price: Sackmann rounds 1-2, or, for a projected event (no Sackmann rows;
    results come from Kalshi), every listed match in its first r12_days + margin_days days of play.
    Play starts at the first listing on or after the projected date - 1 day, so a qualifying week
    listed under the same key (Wimbledon) doesn't count; qualifying days and round 3 that still fall
    inside the window are dropped later by Kalshi's round labels (dk_study.frame_unresolved)."""
    sel = (j["sack_row"] >= 0) & (j["round_idx"] <= early_rounds)
    inside = pd.Series(True, index=j.index)
    if t is not None and len(t) and {"win_start", "win_end"} <= set(t.columns):
        # a listing returns the closest snapshot at or before the requested date, which can be
        # an old one (e.g. last year's final): keep only events that start inside the window
        w = t.set_index(["key", "tourney_id"])[["win_start", "win_end"]]
        idx = pd.MultiIndex.from_frame(j[["key", "tourney_id"]])
        ws = pd.Series(w["win_start"].reindex(idx).to_numpy(), index=j.index)
        we = pd.Series(w["win_end"].reindex(idx).to_numpy(), index=j.index)
        inside = ((j["commence"] >= ws - pd.Timedelta(days=1)) & (j["commence"] <= we + pd.Timedelta(days=3))) | ws.isna()
        sel &= inside
    if t is not None and len(t) and "projected" in t and t["projected"].any():
        pt = t[t["projected"]].set_index(["key", "tourney_id"])
        idx = pd.MultiIndex.from_frame(j[["key", "tourney_id"]])
        days = pd.Series(pt["r12_days"].reindex(idx).to_numpy(), index=j.index)
        play = inside
        if "date" in pt:
            start = pd.Series(pt["date"].reindex(idx).to_numpy(), index=j.index)
            play = inside & ~(j["commence"] < start - pd.Timedelta(days=1))
        first = j["commence"].where(play).groupby([j["key"], j["tourney_id"]]).transform("min")
        sel |= play & days.notna() & (j["commence"] < first.dt.floor("D") + pd.to_timedelta(
            days.fillna(0) + margin_days, unit="D"))
    return sel


def snapshot_plan(j: pd.DataFrame, snap_h: float = 6.0, lead_min: float = 5.0,
                  early_rounds: int = 2, t: pd.DataFrame | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(requests: key, when; per-match: sack_row, deadline, planned snapshot, planned staleness)."""
    need = j[needed(j, t, early_rounds)].copy()
    need["deadline"] = need["commence"] - pd.Timedelta(minutes=lead_min)
    need["cell"] = need["deadline"].dt.floor(pd.Timedelta(hours=snap_h))
    need["snap"] = need.groupby(["key", "cell"])["deadline"].transform("min")
    need["planned_stale_min"] = (need["commence"] - need["snap"]).dt.total_seconds() / 60
    req = need[["key", "tourney_id", "snap"]].drop_duplicates(["key", "snap"]).rename(columns={"snap": "ts"})
    req["when"] = req["ts"].map(iso)
    return req.reset_index(drop=True), need.reset_index(drop=True)


# --- closing snapshots -------------------------------------------------------------------------

def close_plan(j: pd.DataFrame, t: pd.DataFrame, snaps: pd.DataFrame, gran_min: float = 60.0,
               lead_min: float = 5.0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Closing-price plan. Per needed match the target is commence - lead_min. A match is already
    covered when a cached snapshot that lists it is at most gran_min older than the target. The rest
    are grouped per key into gran_min cells, one request at each cell's earliest target, so a planned
    close is at most gran_min (+ the API's 5-10 min snapshot step) older than its target.
    -> (requests: key, tourney_id, ts, when; per match: target, cached_close, planned_close, close_age_min)."""
    need = j[needed(j, t)].copy()
    need["target"] = need["commence"] - pd.Timedelta(minutes=lead_min)
    best = pd.Series(pd.NaT, index=need.index, dtype="datetime64[ns]")
    if len(snaps):
        m = need[["key", "event_id", "target"]].reset_index().merge(
            snaps[["key", "event_id", "snapshot_ts"]].drop_duplicates(), on=["key", "event_id"])
        m = m[m["snapshot_ts"] <= m["target"]]
        best = m.groupby("index")["snapshot_ts"].max().reindex(need.index)
    need["cached_close"] = best
    gran = pd.Timedelta(minutes=gran_min)
    covered = need["cached_close"].notna() & (need["target"] - need["cached_close"] <= gran)
    todo = need[~covered].copy()
    todo["cell"] = todo["target"].dt.floor(gran)
    todo["snap"] = todo.groupby(["key", "cell"])["target"].transform("min")
    need["planned_close"] = need["cached_close"].where(covered)
    need.loc[todo.index, "planned_close"] = todo["snap"]
    need["close_age_min"] = (need["target"] - need["planned_close"]).dt.total_seconds() / 60
    req = todo[["key", "tourney_id", "snap"]].drop_duplicates(["key", "snap"]).rename(columns={"snap": "ts"})
    req["when"] = req["ts"].map(iso)
    return req.reset_index(drop=True), need.reset_index(drop=True)


def close_inputs(t: pd.DataFrame, sack: pd.DataFrame, events_step_h: float = 24.0,
                 root: Path = CACHE) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(joined events incl. ones seen only in snapshots, every cached snapshot) for close_plan."""
    snaps = all_snapshots(root)
    ev = pd.concat([load_events(events_schedule(t, events_step_h), root), snapshot_events(snaps, t)],
                   ignore_index=True)
    ev = ev.sort_values("listed").drop_duplicates(["key", "event_id"], keep="last")
    return join_events(ev, sack), snaps


# --- dry run ---------------------------------------------------------------------------------

def dry_run(t: pd.DataFrame, sack: pd.DataFrame, events_step_h: float, snap_h: float,
            lead_min: float, root: Path = CACHE) -> tuple[str, dict]:
    sched = events_schedule(t, events_step_h)
    sched["cached"] = [cache_path("events", k, w, root).exists() for k, w in zip(sched["key"], sched["when"])]
    ev = load_events(sched, root)
    j = join_events(ev, sack) if len(ev) else ev
    req, need = snapshot_plan(j, snap_h, lead_min, t=t) if len(ev) else (pd.DataFrame(columns=["key", "tourney_id", "when"]), pd.DataFrame())
    if len(req):
        req["cached"] = [cache_path("odds", k, w, root).exists() for k, w in zip(req["key"], req["when"])]
    est_cells = int(np.ceil(13.0 / snap_h))  # cells per play day (~13 h of play) until listings are cached
    lines = [f"Dry run: events every {events_step_h:g} h, odds cells {snap_h:g} h, deadline = commence − "
             f"{lead_min:g} min. Costs: listing 1 credit (0 if empty), odds snapshot 10 credits.", "",
             "| Key | Event | Start | Listing calls (to pull) | Odds snapshots | Odds basis | Credits (to pull) |",
             "|---|---|---|---|---|---|---|"]
    tot = {"listing": 0, "listing_new": 0, "odds": 0, "odds_new": 0}
    for r in t.itertuples():
        s = sched[sched["tourney_id"] == r.tourney_id]
        s = s[s["key"] == r.key]
        n_list, n_list_new = len(s), int((~s["cached"]).sum())
        listed_all = n_list_new == 0 and n_list > 0
        if listed_all and len(req):
            q = req[(req["key"] == r.key) & (req["tourney_id"] == r.tourney_id)]
            n_odds, n_odds_new, basis = len(q), int((~q["cached"]).sum()), "exact"
        elif listed_all:
            n_odds, n_odds_new, basis = 0, 0, "exact"
        else:
            n_odds = n_odds_new = r.r12_days * est_cells
            basis = "estimate"
        tot["listing"] += n_list
        tot["listing_new"] += n_list_new
        tot["odds"] += n_odds
        tot["odds_new"] += n_odds_new
        lines.append(f"| {r.key} | {r.name} {r.season} | {r.date.date()} | {n_list} ({n_list_new}) | "
                     f"{n_odds} ({n_odds_new}) | {basis} | {n_list_new + 10 * n_odds_new} |")
    credits_new = tot["listing_new"] + 10 * tot["odds_new"]
    lines += ["", f"**Total:** {len(t)} key-events; listing calls {tot['listing']} ({tot['listing_new']} to pull), "
              f"odds snapshots {tot['odds']} ({tot['odds_new']} to pull). **Credits still to spend: "
              f"≤ {credits_new:,}** (listing calls before a key's history starts cost 0)."]
    if len(need):
        st = need["planned_stale_min"]
        n_r12 = int(needed(j, t).sum())
        lines += [f"Rounds 1–2 matches with a listed event: {n_r12:,} (events listed {len(j):,}, joined to "
                  f"Sackmann {int((j['sack_row'] >= 0).sum()):,}). Planned price age before commence: median "
                  f"{st.median():.0f} min, p90 {st.quantile(0.9):.0f} min, max {st.max():.0f} min "
                  "(+ up to 5–10 min snapshot step)."]
    return "\n".join(lines) + "\n", dict(sched=sched, events=ev, joined=j, req=req, need=need, totals=tot,
                                         credits_new=credits_new)


# --- pull ------------------------------------------------------------------------------------

def logged_total(log: Path) -> float:
    if not log.exists():
        return 0.0
    return sum(float(line.split("\t")[2]) for line in log.read_text().splitlines() if line.strip())


def pull(api, kind: str, todo: pd.DataFrame, cap: float, root: Path = CACHE, pause_s: float = 0.2,
         books=BOOKS) -> dict:
    """Fetch every uncached (key, when) of `kind` ("events" | "odds"). Stops before the spend log's
    total + the call's cost would pass `cap`."""
    cost = 1 if kind == "events" else 10
    done = skipped = 0
    for r in todo.itertuples():
        p = cache_path(kind, r.key, r.when, root)
        if p.exists():
            skipped += 1
            continue
        if logged_total(api.spend_log) + cost > cap:
            return {"done": done, "cached": skipped, "stopped": f"cap {cap:,.0f} reached"}
        before = api.spent
        body = (api.historical_events(r.key, r.when) if kind == "events"
                else api.historical_odds(r.key, r.when, bookmakers=books))
        write_cache(p, body)
        if kind == "events" and not (body.get("data") or []) and api.spent > before:
            return {"done": done + 1, "cached": skipped,
                    "stopped": "an empty listing cost credits (docs say 0): stopped to re-check costs"}
        done += 1
        time.sleep(pause_s)
    return {"done": done, "cached": skipped, "stopped": None}


# --- stage 4: prices -------------------------------------------------------------------------

def load_snapshots(req: pd.DataFrame, root: Path = CACHE) -> pd.DataFrame:
    """Cached odds snapshots -> one row per (snapshot, event, book)."""
    frames = []
    for r in req.itertuples():
        p = cache_path("odds", r.key, r.when, root)
        if not p.exists():
            continue
        body = read_cache(p)
        df = parse_h2h(body.get("data") or [], body.get("timestamp"))
        if len(df):
            frames.append(df.assign(key=r.key))
    if not frames:
        return pd.DataFrame()
    s = pd.concat(frames, ignore_index=True)
    for c in ("snapshot_ts", "commence_time", "last_update"):
        s[c] = pd.to_datetime(s[c], utc=True).dt.tz_localize(None)
    return s


def prices(need: pd.DataFrame, snaps: pd.DataFrame, sack: pd.DataFrame, lead_min: float = 5.0) -> pd.DataFrame:
    """Per Sackmann rounds 1-2 match: the latest snapshot at or before commence - lead_min that
    has the event, per book; odds oriented to Sackmann winner/loser."""
    if not len(snaps):
        return pd.DataFrame()
    m = need[["key", "event_id", "sack_row", "commence", "id_home", "id_away"]].merge(
        snaps, on=["key", "event_id"], how="inner")
    m = m[m["snapshot_ts"] <= m["commence"] - pd.Timedelta(minutes=lead_min)]
    m = m.sort_values("snapshot_ts").drop_duplicates(["sack_row", "book"], keep="last")
    # parse_h2h's player_1 is home_team: orient to Sackmann's winner
    w_id = sack.loc[m["sack_row"], "winner_id"].astype(str).to_numpy()
    home_won = m["id_home"].astype(str).to_numpy() == w_id
    m["odds_w"] = np.where(home_won, m["odds_1"], m["odds_2"])
    m["odds_l"] = np.where(home_won, m["odds_2"], m["odds_1"])
    m["age_min"] = (m["commence"] - m["snapshot_ts"]).dt.total_seconds() / 60
    wide = m.pivot(index="sack_row", columns="book", values=["odds_w", "odds_l", "age_min", "snapshot_ts"])
    wide.columns = [f"{v}_{b}" for v, b in wide.columns]
    for c in wide.columns:
        wide[c] = pd.to_datetime(wide[c]) if c.startswith("snapshot_ts") else pd.to_numeric(wide[c])
    out = wide.reset_index()
    out["commence"] = out["sack_row"].map(need.drop_duplicates("sack_row").set_index("sack_row")["commence"])
    return out


def snapshot_events(snaps: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    """Events seen inside odds snapshots (a match listed between two listing calls still gets
    priced), assigned to the tournament whose key and window contain them."""
    if not len(snaps):
        return pd.DataFrame(columns=["key", "tourney_id", "event_id", "listed", "commence", "home", "away"])
    e = (snaps.sort_values("snapshot_ts").drop_duplicates(["key", "event_id"], keep="last")
         .rename(columns={"snapshot_ts": "listed", "commence_time": "commence",
                          "player_1": "home", "player_2": "away"}))
    w = t[["key", "tourney_id", "win_start", "win_end"]]
    e = e.merge(w, on="key")
    e = e[(e["commence"] >= e["win_start"]) & (e["commence"] <= e["win_end"] + pd.Timedelta(days=2))]
    return e[["key", "tourney_id", "event_id", "listed", "commence", "home", "away"]]


def all_snapshots(root: Path = CACHE) -> pd.DataFrame:
    """Every cached odds snapshot (whatever plan fetched it)."""
    req = [{"key": p.parent.name, "when": p.name.split(".")[0]} for p in sorted((root / "odds").glob("*/*.json.gz"))]
    req = pd.DataFrame(req, columns=["key", "when"])
    return load_snapshots(req, root) if len(req) else pd.DataFrame()


def collect(t: pd.DataFrame, sack: pd.DataFrame, events_step_h: float = 24.0, lead_min: float = 5.0,
            root: Path = CACHE) -> pd.DataFrame:
    """Priced rounds 1-2 Sackmann matches: one row per sack_row with odds_w/l_<book>,
    age_min_<book> (price age before commence), commence, key, tourney_id."""
    snaps = all_snapshots(root)
    ev = pd.concat([load_events(events_schedule(t, events_step_h), root), snapshot_events(snaps, t)],
                   ignore_index=True)
    if not len(ev):
        return pd.DataFrame()
    ev = ev.sort_values("listed").drop_duplicates(["key", "event_id"], keep="last")
    j = join_events(ev, sack)
    need = j[(j["sack_row"] >= 0) & (j["round_idx"] <= 2)]
    out = prices(need, snaps, sack, lead_min)
    if len(out):
        meta = need.drop_duplicates("sack_row").set_index("sack_row")[["key", "tourney_id"]]
        out = out.join(meta, on="sack_row")
    open_ = j[needed(j, t) & (j["sack_row"] < 0)].merge(
        t[["key", "tourney_id", "level_group"]], on=["key", "tourney_id"], how="left")
    out.attrs.update(listed=len(ev), joined=int((j["sack_row"] >= 0).sum()), r12=len(need),
                     unresolved=unresolved_prices(open_, snaps, lead_min))
    return out


def unresolved_prices(ev: pd.DataFrame, snaps: pd.DataFrame, lead_min: float = 5.0) -> pd.DataFrame:
    """Priced events with no Sackmann result (projected events): one row per event with home/away
    names and odds per book at the last snapshot >= lead_min before commence. Results come from
    elsewhere (Kalshi settlements, in Data's container); see dk_study.results_from_table."""
    if not len(ev) or not len(snaps):
        return pd.DataFrame()
    if "level_group" not in ev:
        ev = ev.assign(level_group="other")
    m = ev[["key", "tourney_id", "level_group", "event_id", "commence", "home", "away"]].merge(
        snaps[["key", "event_id", "book", "snapshot_ts", "odds_1", "odds_2"]], on=["key", "event_id"])
    m = m[m["snapshot_ts"] <= m["commence"] - pd.Timedelta(minutes=lead_min)]
    m = m.sort_values("snapshot_ts").drop_duplicates(["event_id", "book"], keep="last")
    m["age_min"] = (m["commence"] - m["snapshot_ts"]).dt.total_seconds() / 60
    w = m.pivot(index=["key", "tourney_id", "level_group", "event_id", "commence", "home", "away"], columns="book",
                values=["odds_1", "odds_2", "age_min"])
    w.columns = [f"{v.replace('odds_1', 'odds_home').replace('odds_2', 'odds_away')}_{b}" for v, b in w.columns]
    return w.astype(float).reset_index()


# --- CLI -------------------------------------------------------------------------------------

def _keys(api=None) -> list[str]:
    if api is not None:
        return sorted(s["key"] for s in api.sports(all_sports=True) if s["key"].startswith("tennis_"))
    return sorted(LISTED_KEYS)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("stage", choices=["plan", "events", "odds", "close"])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    ap.add_argument("--cache", type=Path, default=CACHE)
    ap.add_argument("--events-step-h", type=float, default=24.0)
    ap.add_argument("--snap-h", type=float, default=6.0)
    ap.add_argument("--lead-min", type=float, default=5.0)
    ap.add_argument("--cap", type=float, default=15000, help="max credits for this pull (spend log total)")
    ap.add_argument("--floor", type=int, default=1000)
    ap.add_argument("--offline-keys", action="store_true", help="plan from the built-in key list (no API call)")
    ap.add_argument("--other-from", default=None,
                    help="also plan 250/500 keys, with history assumed from this date (e.g. 2024-01-01)")
    ap.add_argument("--project-until", default=None,
                    help="also plan editions after Sackmann's end up to this date (results from Kalshi)")
    ap.add_argument("--tiers", default=None, help="comma list of level groups to keep: slam,1000,other")
    ap.add_argument("--close-min", type=float, default=10.0,
                    help="close stage: cell size in minutes (a close is at most this old)")
    ap.add_argument("--yes", action="store_true", help="required for paid stages")
    a = ap.parse_args(argv)

    from .odds_api import OddsApi
    sack = sackmann.load(a.sackmann, start=2019)
    api = None if (a.stage == "plan" and a.offline_keys) else OddsApi(
        floor=a.floor, spend_log=a.cache / "spend.log")
    hs = {**HIST_START, "other": pd.Timestamp(a.other_from)} if a.other_from else None
    t = tournaments(sack, _keys(api), hist_start=hs,
                    project_until=pd.Timestamp(a.project_until) if a.project_until else None)
    if a.tiers:
        t = t[t["level_group"].isin(a.tiers.split(","))].reset_index(drop=True)
    if a.stage == "close":
        j, snaps = close_inputs(t, sack, a.events_step_h, a.cache)
        req, need = close_plan(j, t, snaps, a.close_min, a.lead_min)
        req["cached"] = [cache_path("odds", k, w, a.cache).exists() for k, w in zip(req["key"], req["when"])]
        new = int((~req["cached"]).sum())
        age = need["close_age_min"]
        print(f"Close plan, {a.close_min:g} min cells: {len(need):,} matches; {len(req):,} snapshots "
              f"({new:,} to pull) = {10 * new:,} credits; close age median {age.median():.0f}, p90 "
              f"{age.quantile(0.9):.0f}, max {age.max():.0f} min."
              + (f" Balance {api.remaining:,.0f}; cap {a.cap:,.0f}; logged {logged_total(api.spend_log):,.0f}."
                 if api is not None and api.remaining is not None else ""))
        if not a.yes:
            return
        res = pull(api, "odds", req.sort_values("ts", ascending=False), a.cap, a.cache)
        print(f"close: fetched {res['done']}, already cached {res['cached']}"
              + (f", STOPPED: {res['stopped']}" if res["stopped"] else "")
              + f". Spent this run {api.spent:,.0f}; balance {api.remaining:,.0f}.")
        return
    text, parts = dry_run(t, sack, a.events_step_h, a.snap_h, a.lead_min, a.cache)
    if api is not None:
        text += (f"\nBalance now: {api.remaining:,.0f} credits; floor {a.floor:,}; this pull's cap "
                 f"{a.cap:,.0f}, logged so far {logged_total(api.spend_log):,.0f}.\n")
    print(text)
    if a.stage == "plan":
        return
    if not a.yes:
        raise SystemExit(f"'{a.stage}' makes paid calls: re-run with --yes once the Lead has approved.")
    todo = parts["sched"] if a.stage == "events" else parts["req"]
    if a.stage == "odds" and not len(todo):
        raise SystemExit("no odds snapshots planned: pull the event listings first")
    todo = todo.sort_values("when", ascending=False)  # most recent first: a cap stop drops the oldest
    res = pull(api, a.stage, todo, a.cap, a.cache)
    print(f"{a.stage}: fetched {res['done']}, already cached {res['cached']}"
          + (f", STOPPED: {res['stopped']}" if res["stopped"] else "")
          + f". Spent this run {api.spent:,.0f}; balance {api.remaining:,.0f}; logged total "
          f"{logged_total(api.spend_log):,.0f}.")


if __name__ == "__main__":
    main()
