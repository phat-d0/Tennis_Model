"""Builder for the public tennis odds page (GitHub Pages; plan and JSON contract: docs/site_plan.md).

    python -m upsets.site build --out _site/data --cache data/site_cache \
        --archive data/sackmann --floor 5000 --month-cap 3000

Writes <out>/odds.json: current DraftKings + Pinnacle match odds for tennis keys with a match in the
next 36 h, the de-vigged fair chance, and an Elo model chance from Jeff Sackmann's results
(CC BY-NC-SA 4.0).

Credits (shared paid key, ODDS_API_KEY): /sports and /events are free; one /odds call per key with
a match in the next 36 h (bookmakers=draftkings,pinnacle: 1 credit). Every call keeps the 5,000
reserve (OddsApi floor). The page spends at most `month_cap` a calendar month, paced: today's
allowance = (cap - used before today) / days left in the month, spread over the day's remaining
runs (one every `run_every_h`). Soonest matches are fetched first. With no key, at the cap or
floor, or on any error, no paid call is made and odds.json is written from the cached snapshots,
with `status` saying why.

Cache (<cache>, never committed): h2h.parquet (every snapshot, parse_h2h rows), ledger.json
(credits used this month, by day), sports.json (key -> title), ratings_<archive sha>.parquet/.json,
spend.log.

No Kalshi: this module reads no Kalshi data and imports nothing that does (tests check it).
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import json
import math
import os
import re
import subprocess
from pathlib import Path

import pandas as pd

from . import elo, sackmann
from .names import match_names, player_table
from .odds_api import KEY_NAMES, BudgetError, OddsApi, parse_h2h

BOOKS = ("draftkings", "pinnacle")
HORIZON_H = 36.0
SHOW_PAST_H = 3.0       # keep a match on the page this long after its listed start
MIN_RATED = 20          # model_p1 is null below this many rated matches for either player
ACTIVE_YEARS = 2        # name matching tries players active in the last 2 years first
SURFACE_WEIGHT = 0.5    # model rating difference = 0.5 overall + 0.5 surface


def utcnow() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _iso(t) -> str | None:
    if t is None or pd.isna(t):
        return None
    return pd.Timestamp(t).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, allow_nan=False))
    os.replace(tmp, path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


# --- credits -----------------------------------------------------------------------------------

def load_ledger(cache: Path, now: pd.Timestamp) -> dict:
    """{"month": "YYYY-MM", "used": credits this month, "by_day": {date: credits}, "left": last balance}."""
    led = _read_json(cache / "ledger.json", {})
    month = now.strftime("%Y-%m")
    if led.get("month") != month:
        led = {"month": month, "used": 0, "by_day": {}, "left": led.get("left")}
    return led


def run_allowance(led: dict, cap: int, now: pd.Timestamp, run_every_h: float = 3.0) -> int:
    """Credits this run may spend: today's allowance = (cap - used before today) / days left in the
    month, minus what today already spent, split over today's remaining runs; never past the cap."""
    today = now.strftime("%Y-%m-%d")
    spent_today = led["by_day"].get(today, 0)
    days_left = calendar.monthrange(now.year, now.month)[1] - now.day + 1
    left_today = (cap - (led["used"] - spent_today)) / days_left - spent_today
    hours_left = 24 - (now.hour + now.minute / 60)
    runs_left = max(1, math.ceil(hours_left / run_every_h))
    return int(max(0, min(math.floor(left_today / runs_left + 0.5), cap - led["used"])))


def record_spend(led: dict, credits: float, now: pd.Timestamp) -> None:
    today = now.strftime("%Y-%m-%d")
    led["used"] += credits
    led["by_day"][today] = led["by_day"].get(today, 0) + credits


# --- odds --------------------------------------------------------------------------------------

def keys_to_fetch(api: OddsApi, now: pd.Timestamp, horizon_h: float = HORIZON_H) -> tuple[list[str], dict]:
    """Free calls only. -> (active tennis keys with a match starting in (now, now + horizon], soonest
    first; {key: title} for every active tennis key)."""
    titles, soonest = {}, {}
    for s in api.sports():
        if s["key"].startswith("tennis_") and s.get("active"):
            titles[s["key"]] = s.get("title") or s["key"]
    for key in sorted(titles):
        starts = pd.to_datetime([e["commence_time"] for e in api.events(key)], utc=True)
        starts = starts[(starts > now) & (starts <= now + pd.Timedelta(hours=horizon_h))]
        if len(starts):
            soonest[key] = starts.min()
    return sorted(soonest, key=soonest.get), titles


def append_snapshots(cache: Path, rows: pd.DataFrame) -> pd.DataFrame:
    path = cache / "h2h.parquet"
    old = pd.read_parquet(path) if path.exists() else pd.DataFrame()
    if len(rows):
        old = pd.concat([old, rows], ignore_index=True) if len(old) else rows
        path.parent.mkdir(parents=True, exist_ok=True)
        old.to_parquet(path, index=False)
    return old


def _book(r) -> dict | None:
    if r is None:
        return None
    return {"odds_1": float(r["odds_1"]), "odds_2": float(r["odds_2"]),
            "last_update": _iso(r["last_update"]),
            "margin": round(1 / r["odds_1"] + 1 / r["odds_2"] - 1, 4)}


def _tour(sport_key: str) -> str:
    m = re.match(r"tennis_(atp|wta)_", sport_key)
    return m.group(1).upper() if m else "?"


# --- model -------------------------------------------------------------------------------------

def archive_sha(archive: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(archive), "rev-parse", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        h = hashlib.sha1()
        for p in sorted(archive.glob("*/*_matches_*.csv")):
            h.update(f"{p.name}:{p.stat().st_size}".encode())
        return "files-" + h.hexdigest()


def key_surfaces(sack: pd.DataFrame) -> dict:
    """Odds API key -> surface of the latest Sackmann edition of that tournament on that tour."""
    out = {}
    for suffix, names in KEY_NAMES.items():
        for tour in ("atp", "wta"):
            ev = sack[(sack["tour"] == tour) & sack["tournament"].str.lower().isin([n.lower() for n in names])]
            ev = ev.dropna(subset=["surface"])
            if len(ev):
                out[f"tennis_{tour}_{suffix}"] = str(ev.sort_values("date")["surface"].iloc[-1])
    return out


def load_ratings(archive: Path, cache: Path) -> dict | None:
    """{"ratings": per (tour, id, surface) frame, "players": name table, "through", "surfaces"},
    cached by the archive's commit SHA; None without an archive."""
    if not archive.is_dir():
        return None
    sha = archive_sha(archive)
    rp, mp, pp = (cache / f"ratings_{sha}.parquet", cache / f"ratings_{sha}.json",
                  cache / f"players_{sha}.parquet")
    if rp.exists() and mp.exists() and pp.exists():
        meta = json.loads(mp.read_text())
        return {"ratings": pd.read_parquet(rp), "players": pd.read_parquet(pp), **meta}
    sack = sackmann.load(archive, start=1990, lower=True)
    r = elo.final_ratings(sack, keys=("winner_id", "loser_id"))
    r["id"] = r["id"].astype(str)
    players = player_table(sack)
    players["id"] = players["id"].astype(str)
    meta = {"through": sack["date"].max().strftime("%Y-%m-%d"), "surfaces": key_surfaces(sack)}
    cache.mkdir(parents=True, exist_ok=True)
    for old in cache.glob("ratings_*"):
        old.unlink()
    for old in cache.glob("players_*"):
        old.unlink()
    r.to_parquet(rp, index=False)
    players.to_parquet(pp, index=False)
    _write_json(mp, meta)
    return {"ratings": r, "players": players, **meta}


def model_probs(m: pd.DataFrame, rt: dict | None, now: pd.Timestamp) -> pd.DataFrame:
    """model_p1, model_n1, model_n2 for each match row (sport_key, player_1, player_2); None where
    a name isn't matched uniquely or a player has < MIN_RATED rated matches."""
    out = pd.DataFrame({"model_p1": None, "model_n1": None, "model_n2": None}, index=m.index, dtype=object)
    if rt is None or not len(m):
        return out
    tours = m["sport_key"].map(lambda k: _tour(k).lower())
    since = (now - pd.DateOffset(years=ACTIVE_YEARS)).tz_localize(None)
    players = rt["players"].assign(last=pd.to_datetime(rt["players"]["last"]))
    id1 = match_names(m["player_1"], tours, players, since)["id"]
    id2 = match_names(m["player_2"], tours, players, since)["id"]
    r = rt["ratings"]
    overall = r.drop_duplicates(["tour", "id"]).set_index(["tour", "id"])[["elo", "n"]]
    surf = r.set_index(["tour", "id", "surface"])["selo"]
    for i in m.index:
        t, a, b = tours[i], id1[i], id2[i]
        if pd.isna(a) or pd.isna(b) or (t, a) not in overall.index or (t, b) not in overall.index:
            continue
        ra, rb = overall.loc[(t, a)], overall.loc[(t, b)]
        out.at[i, "model_n1"], out.at[i, "model_n2"] = int(ra["n"]), int(rb["n"])
        if min(ra["n"], rb["n"]) < MIN_RATED:
            continue
        diff = ra["elo"] - rb["elo"]
        s = rt["surfaces"].get(m.at[i, "sport_key"])
        if s:
            sd = surf.get((t, a, s), elo.START) - surf.get((t, b, s), elo.START)
            diff = (1 - SURFACE_WEIGHT) * diff + SURFACE_WEIGHT * sd
        out.at[i, "model_p1"] = round(1 / (1 + 10 ** (-diff / 400)), 4)
    return out


# --- page data ---------------------------------------------------------------------------------

def page_matches(snaps: pd.DataFrame, titles: dict, rt: dict | None, now: pd.Timestamp) -> list[dict]:
    """Latest quote per (event, book) for matches starting after now - SHOW_PAST_H."""
    if not len(snaps):
        return []
    s = snaps[snaps["commence_time"] >= now - pd.Timedelta(hours=SHOW_PAST_H)]
    s = s.sort_values("snapshot_ts").drop_duplicates(["event_id", "book"], keep="last")
    ev = (s.sort_values("snapshot_ts").drop_duplicates("event_id", keep="last")
          .sort_values(["sport_key", "commence_time"]).reset_index(drop=True))
    model = model_probs(ev, rt, now)
    quotes = {(r["event_id"], r["book"]): r for _, r in s.iterrows()}
    out = []
    for i, e in ev.iterrows():
        dk, pin = (quotes.get((e["event_id"], b)) for b in BOOKS)
        # a book's quote must name the players in the same order as the event row
        dk, pin = ((q if q is not None and q["player_1"] == e["player_1"] else None) for q in (dk, pin))
        fair_src = pin if pin is not None else dk
        fair = None
        if fair_src is not None:
            i1, i2 = 1 / fair_src["odds_1"], 1 / fair_src["odds_2"]
            fair = round(i1 / (i1 + i2), 4)
        out.append({
            "event_id": e["event_id"], "sport_key": e["sport_key"],
            "tournament": titles.get(e["sport_key"], e["sport_key"]), "tour": _tour(e["sport_key"]),
            "commence_time": _iso(e["commence_time"]), "player_1": e["player_1"], "player_2": e["player_2"],
            "draftkings": _book(dk), "pinnacle": _book(pin), "fair_1": fair,
            "dk_implied_1": round(1 / dk["odds_1"], 4) if dk is not None else None,
            "model_p1": model.at[i, "model_p1"], "model_n1": model.at[i, "model_n1"],
            "model_n2": model.at[i, "model_n2"]})
    return out


def build(out: Path, cache: Path, archive: Path, floor: int = 5000, month_cap: int = 3000,
          now: pd.Timestamp | None = None, key: str | None = None, session=None,
          run_every_h: float = 3.0) -> dict:
    now = now or utcnow()
    cache.mkdir(parents=True, exist_ok=True)
    led = load_ledger(cache, now)
    titles = _read_json(cache / "sports.json", {})
    status, new_rows = "ok", []
    try:
        api = OddsApi(floor=floor, key=key, session=session, spend_log=cache / "spend.log")
    except RuntimeError:
        api, status = None, "no_key"
    if api is not None:
        try:
            keys, fresh_titles = keys_to_fetch(api, now)
            titles.update(fresh_titles)
            _write_json(cache / "sports.json", titles)
            allowed = run_allowance(led, month_cap, now, run_every_h)
            if api.remaining is not None and api.remaining - 1 < floor:
                status = "below_floor"
            elif not keys:
                status = "no_tournaments"
            elif led["used"] >= month_cap:
                status = "cap_reached"
            elif allowed < 1:
                status = "paced"
            else:
                for k in keys[:allowed]:
                    before = api.spent
                    try:
                        events = api.odds(k, bookmakers=BOOKS)
                    except BudgetError:
                        status = "below_floor"
                        break
                    finally:
                        if api.spent > before:
                            record_spend(led, api.spent - before, now)
                    new_rows.append(parse_h2h(events, _iso(now)))
        except Exception as e:  # never str(e): request errors carry the URL, which holds the key
            code = getattr(getattr(e, "response", None), "status_code", None)
            status = f"error: {type(e).__name__}" + (f" {code}" if code else "")
        if api.remaining is not None:
            led["left"] = api.remaining
    _write_json(cache / "ledger.json", led)
    rows = pd.concat([r for r in new_rows if len(r)], ignore_index=True) if any(len(r) for r in new_rows) \
        else pd.DataFrame()
    snaps = append_snapshots(cache, rows)
    try:
        rt = load_ratings(archive, cache)
    except Exception as e:
        print(f"[ratings unavailable: {type(e).__name__}]")
        rt = None
    matches = page_matches(snaps, titles, rt, now)
    shown = sorted({m["sport_key"] for m in matches})
    doc = {
        "generated_at": _iso(now),
        "odds_fetched_at": _iso(snaps["snapshot_ts"].max()) if len(snaps) else None,
        "status": status,
        "credits": {"left": None if led.get("left") is None else int(led["left"]),
                    "used_this_month": int(led["used"]), "month_cap": month_cap},
        "ratings_through": rt["through"] if rt else None,
        "tournaments": [{"sport_key": k, "title": titles.get(k, k), "tour": _tour(k)} for k in shown],
        "matches": matches,
    }
    _write_json(out / "odds.json", doc)
    return doc


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--out", type=Path, default=Path("_site/data"))
    ap.add_argument("--cache", type=Path, default=Path("data/site_cache"))
    ap.add_argument("--archive", type=Path, default=Path("data/sackmann"))
    ap.add_argument("--floor", type=int, default=5000)
    ap.add_argument("--month-cap", type=int, default=3000)
    ap.add_argument("--run-every-h", type=float, default=3.0)
    a = ap.parse_args(argv)
    doc = build(a.out, a.cache, a.archive, a.floor, a.month_cap, run_every_h=a.run_every_h)
    print(f"[odds.json: status={doc['status']}, {len(doc['matches'])} matches, "
          f"credits used this month {doc['credits']['used_this_month']}/{a.month_cap}, "
          f"left {doc['credits']['left']}]")


if __name__ == "__main__":
    main()
