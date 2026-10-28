"""Data-quality check of the DK "close": matches whose listed start moved after the close snapshot.

    python -m upsets.dk_close_check [--sackmann PATH] [--out reports/upsets_dk_close_check.md]

dk_history.collect takes each match's close as the last snapshot >= 5 min before the start listed in the close
studies' cache. The DK in-play pull (reports/upsets_dk_inplay.md) showed that a listed start can move after that
snapshot; this measures how often (2–4% of matches per season in 2023–26, median 1.5 h) and whether it matters.
It also checks pairings DK listed as more than one event (a placeholder later re-listed): which event the close
came from. Here, per priced match: final listed start = the event's commence_time in the latest snapshot of either cache;
moved = final start more than MOVED_MIN after the start the close used. The in-play cache covers 2023 - May 2026
only, so earlier seasons are "unknown". Then the existing headlines (#86, #99, #134, the Portfolio backtest) are
re-stated without the moved matches, with the same code on the same Sackmann-span data. 0 credits; aggregates only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import dk_history as dh
from . import dk_inplay as di

MOVED_MIN = 60


def _need(t: pd.DataFrame, sack: pd.DataFrame, root: Path = dh.CACHE) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(events joined to rounds 1-2 Sackmann rows, all of them, as dk_history.collect builds them; snapshots)."""
    snaps = dh.all_snapshots(root)
    ev = pd.concat([dh.load_events(dh.events_schedule(t, 24.0), root), dh.snapshot_events(snaps, t)],
                   ignore_index=True)
    ev = ev.sort_values("listed").drop_duplicates(["key", "event_id"], keep="last")
    j = dh.join_events(ev, sack)
    return j[(j["sack_row"] >= 0) & (j["round_idx"] <= 2)], snaps


def close_events(need: pd.DataFrame, snaps: pd.DataFrame) -> pd.DataFrame:
    """sack_row -> key, event_id, commence, snapshot_ts of the event the DK close was read from: as
    dk_history.prices, the latest DK snapshot >= 5 min before the listed start of its own event, over all the
    events joined to that match (a pairing DK listed twice has two)."""
    dk = snaps[snaps["book"] == "draftkings"]
    m = need[["key", "event_id", "sack_row", "commence"]].merge(dk[["key", "event_id", "snapshot_ts"]],
                                                                 on=["key", "event_id"])
    m = m[m["snapshot_ts"] <= m["commence"] - pd.Timedelta(minutes=5)]
    return m.sort_values("snapshot_ts").drop_duplicates("sack_row", keep="last")[
        ["sack_row", "key", "event_id", "commence", "snapshot_ts"]]


def event_ids(t: pd.DataFrame, sack: pd.DataFrame, root: Path = dh.CACHE) -> pd.DataFrame:
    """sack_row -> key, event_id, the start the close used: the event the DK close was actually read from."""
    need, snaps = _need(t, sack, root)
    return close_events(need, snaps)[["sack_row", "key", "event_id", "commence"]]


def final_starts(roots=(dh.CACHE, di.INPLAY_CACHE)) -> pd.DataFrame:
    """(key, event_id) -> the commence_time in the latest snapshot that lists the event, over all caches."""
    frames = [dh.all_snapshots(r) for r in roots]
    s = pd.concat([f for f in frames if len(f)], ignore_index=True)
    s = s.sort_values("snapshot_ts").drop_duplicates(["key", "event_id"], keep="last")
    return s[["key", "event_id", "commence_time", "snapshot_ts"]].rename(
        columns={"commence_time": "final_start", "snapshot_ts": "last_seen"})


def flag(ids: pd.DataFrame, finals: pd.DataFrame, inplay_from: int = 2023, season: pd.Series | None = None
         ) -> pd.DataFrame:
    """status per sack_row: moved / not_moved / unknown (season before the in-play cache)."""
    d = ids.merge(finals, on=["key", "event_id"], how="left")
    d["move_min"] = (d["final_start"] - d["commence"]).dt.total_seconds() / 60
    d["season"] = season.reindex(d["sack_row"]).to_numpy() if season is not None else np.nan
    d["status"] = np.where(d["move_min"] > MOVED_MIN, "moved", "not_moved")
    d.loc[d["season"] < inplay_from, "status"] = "unknown"
    return d


def duplicates(t: pd.DataFrame, sack: pd.DataFrame, priced: pd.DataFrame, root: Path = dh.CACHE,
               inplay_root: Path = di.INPLAY_CACHE) -> tuple[str, set]:
    """Pairings DK listed as more than one event: was the close read from the match DK actually ran, or from a stale
    duplicate? Reads prices and listings, never results. -> (report section, sack_rows with a stale-duplicate close).
    - "Latest listed" = the pairing's event seen in the latest snapshot. It is shown two ways: close-studies cache only
      (what 2020-22 allows) and both caches (2023 on, with the in-play pull's later snapshots).
    - Where the close's event is not the latest listed (both caches), the in-play snapshots decide: the match DK ran
      is the event quoted in play (>= 15 min after the close's listed start, up to + 4 h). A close counts as stale
      only if its event was never quoted in play while another of the pairing's events was."""
    need, snaps = _need(t, sack, root)
    close = cc_close = close_events(need, snaps)
    n_ev = need.groupby("sack_row")["event_id"].nunique()
    dup = cc_close[cc_close["sack_row"].isin(n_ev[n_ev > 1].index)].copy()
    ip = dh.all_snapshots(inplay_root)
    pair = need[need["sack_row"].isin(dup["sack_row"])][["sack_row", "key", "event_id", "commence"]]

    def latest(snap_frame):
        seen = snap_frame.groupby(["key", "event_id"])["snapshot_ts"].max().rename("last_seen").reset_index()
        x = pair.merge(seen, on=["key", "event_id"], how="left")
        return x.sort_values("last_seen").drop_duplicates("sack_row", keep="last").set_index("sack_row")["event_id"]
    lat_close = latest(snaps)
    lat_all = latest(pd.concat([snaps, ip], ignore_index=True) if len(ip) else snaps)
    dup["season"] = sack.loc[dup["sack_row"], "season"].to_numpy()
    dup["disc_close_cache"] = dup["event_id"].to_numpy() != lat_close.reindex(dup["sack_row"]).to_numpy()
    dup["disc_all"] = dup["event_id"].to_numpy() != lat_all.reindex(dup["sack_row"]).to_numpy()
    live = ip[ip["book"] == "draftkings"] if len(ip) else ip

    def quoted_in_play(r, eid):
        if not len(live):
            return False
        q = live[(live["key"] == r.key) & (live["event_id"] == eid)]
        return bool(((q["snapshot_ts"] >= r.commence + pd.Timedelta(minutes=15)) &
                     (q["snapshot_ts"] <= r.commence + pd.Timedelta(hours=4))).any())
    dup["close_in_play"] = np.nan
    dup["other_in_play"] = np.nan
    for i, r in dup[dup["disc_all"] & (dup["season"] >= 2023)].iterrows():
        others = pair.loc[(pair["sack_row"] == r.sack_row) & (pair["event_id"] != r.event_id), "event_id"]
        dup.at[i, "close_in_play"] = quoted_in_play(r, r.event_id)
        dup.at[i, "other_in_play"] = any(quoted_in_play(r, e) for e in others)
    dup["stale"] = (dup["close_in_play"] == False) & (dup["other_in_play"] == True)   # noqa: E712
    close = cc_close.assign(season=sack.loc[cc_close["sack_row"], "season"].to_numpy())
    L = ["", "### Duplicate DK listings at close time", "",
         "| Season | Priced | Pairing listed as > 1 event | Close ≠ latest listed (close cache only) | "
         "Close ≠ latest listed (both caches) | Of those: close event quoted in play / other event quoted in play | "
         "Stale-duplicate closes |", "|---|---|---|---|---|---|---|"]
    for s_, g in close.groupby("season"):
        d = dup[dup["season"] == s_]
        chk = d[d["disc_all"]]
        L.append(f"| {int(s_)} | {len(g):,} | {len(d):,} | {int(d['disc_close_cache'].sum()):,} | "
                 + (f"{int(chk.shape[0]):,} | {int((chk['close_in_play'] == True).sum())} / "   # noqa: E712
                    f"{int((chk['other_in_play'] == True).sum())} | {int(d['stale'].sum())} |"  # noqa: E712
                    if s_ >= 2023 else "not checkable (no later snapshots) | — | — |"))
    stale = set(dup.loc[dup["stale"], "sack_row"])
    L += ["", "- **\"Latest listed\" depends on how late the snapshots go.** With the close studies' cache alone, a "
          "placeholder listed for a later start (a day later, often 00:00) outlives the real match, so the test flags "
          "most duplicated pairings. With the in-play pull's later snapshots (2023 on), the close's event is the latest "
          "listed in all but a handful.",
          "- **For that handful, the in-play snapshots decide**: the event quoted in play after the close's listed start "
          "is the match DK ran.",
          ("- **No close came from a stale duplicate** where it can be checked (2023–26); 2020–22 can't be checked, and "
           "the 2023–24 comparison above shows the close-cache-only flag is not evidence of staleness. No re-statement "
           "is needed for this." if not stale else
           f"- **{len(stale):,} closes came from a stale duplicate** (2023–26); they are an excluded group in the headline "
           "table, with the moved matches. 2020–22 can't be checked.")]
    return "\n".join(L) + "\n", stale


def _pct(x) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x:+.1%}"


def report(d: pd.DataFrame, rows: list[tuple[str, dict, dict]]) -> str:
    L = ["## Results", "", "Generated by `python -m upsets.dk_close_check` (0 credits). Aggregates only.", "",
         "### Matches whose listed start moved more than 1 h after the close", "",
         "| Season | Priced matches | Moved | Not moved | Unknown (no later snapshots) | Median move of the moved (h) |",
         "|---|---|---|---|---|---|"]
    for s, g in d.groupby("season"):
        mv = g[g["status"] == "moved"]
        L.append(f"| {int(s)} | {len(g):,} | {len(mv):,} ({len(mv) / len(g):.0%}) | "
                 f"{int((g['status'] == 'not_moved').sum()):,} | {int((g['status'] == 'unknown').sum()):,} | "
                 f"{mv['move_min'].median() / 60:.1f} |" if len(mv) else
                 f"| {int(s)} | {len(g):,} | 0 | {int((g['status'] == 'not_moved').sum()):,} | "
                 f"{int((g['status'] == 'unknown').sum()):,} | — |")
    L += ["", "### Headlines re-stated (same code, Sackmann-span matches)", "",
          "| Result | All priced | Without moved matches | Moved matches only |", "|---|---|---|---|"]
    for name, a, b, c in rows:
        L.append(f"| {name} | {a} | {b} | {c} |")
    return "\n".join(L) + "\n"


def _s(x: dict) -> str:
    return f"{x['bets']:,} bets, {_pct(x['roi'])}" if x.get("bets") else "—"


def run(root: Path, cache: Path = dh.CACHE) -> str:
    from . import dk_study as ds
    from . import elo, elo_plus, sackmann
    from . import portfolio_backtest as pb
    from . import seed_portfolio as sp
    sack = elo_plus.prep(sackmann.load(root, start=1990, lower=True))
    sack_elo = elo.add_elo(sack, keys=("winner_id", "loser_id"))
    t = dh.tournaments(sack, dh._keys(), hist_start={**dh.HIST_START, "other": pd.Timestamp("2024-01-01")})
    priced = dh.collect(t, sack_elo, 24.0, root=cache)
    d = flag(event_ids(t, sack, cache), final_starts((cache, di.INPLAY_CACHE)), season=sack["season"])
    dup_text, stale = duplicates(t, sack, priced, cache)
    moved = set(d.loc[d["status"] == "moved", "sack_row"]) | stale     # a stale-duplicate close is excluded too
    parts = {"all": priced, "kept": priced[~priced["sack_row"].isin(moved)],
             "moved": priced[priced["sack_row"].isin(moved)]}
    rows = []
    fr = {k: ds.frame(v, sack_elo) for k, v in parts.items()}
    for name, sel in [("Every early-round dog at DK (#99, all tiers)", lambda f: f),
                      ("Every early-round dog at DK, 250/500s (#86)", lambda f: f[f["level_group"] == "other"])]:
        rows.append((name, *[_s(ds.summary(sel(fr[k]))) for k in ("all", "kept", "moved")]))
        rows.append((name.replace("at DK", "at Pinnacle"),
                     *[_s(ds.summary(sel(fr[k]).dropna(subset=["odds_dog_pin"]), odds_col="odds_dog_pin"))
                       for k in ("all", "kept", "moved")]))
    for k in ("all", "kept", "moved"):
        f = fr[k]
        fr[k + "_margin"] = (f["margin_dk"].mean(), f["margin_pin"].mean())
    rows.append(("Mean margin, DK vs Pinnacle", *[f"{fr[k + '_margin'][0]:.2%} vs {fr[k + '_margin'][1]:.2%}"
                                                    for k in ("all", "kept", "moved")]))
    for name, rid in [("Seed loses early, all (#134)", "a"), ("Seed loses early, qualifiers (#134)", "b")]:
        vals = []
        for k in ("all", "kept", "moved"):
            b = sp.subrule(sp.bets(parts[k], sack), rid)
            vals.append(f"{len(b):,} bets, {_pct(b['pnl'].mean())}" if len(b) else "—")
        rows.append((name, *vals))
    full = fr["all"].copy()
    full["p_model"] = elo_plus.walk_forward(sack, full, only=("+serve",))[0]["+serve"]
    full["date"] = pd.to_datetime(priced.set_index("sack_row").loc[full["sack_row"], "commence"].to_numpy())
    for k in ("all", "kept", "moved"):
        sel = full if k == "all" else full[full["sack_row"].isin(moved) == (k == "moved")]
        fr["pb_" + k] = pb.bets(sel)
    for sid in ("model", "line", "dogs"):
        vals = []
        for k in ("all", "kept", "moved"):
            a = pb.aggregate(fr["pb_" + k][sid], sid, n_boot=200)
            vals.append(f"{a.get('bets', 0):,} bets, {_pct(a.get('roi'))} vs {_pct(a.get('expected_roi'))} expected"
                        if a.get("bets") else "—")
        rows.append((f"Portfolio backtest: {sid}", *vals))
    return report(d, rows) + dup_text


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sackmann", type=Path, default=Path("/home/user/phat-d0/tennis-sackmann-archive"))
    ap.add_argument("--out", type=Path, default=None, help="append the results to this file")
    a = ap.parse_args(argv)
    text = run(a.sackmann)
    print(text)
    if a.out:
        body = a.out.read_text().split("## Results")[0].rstrip() if a.out.exists() else ""
        a.out.write_text((body + "\n\n" if body else "") + text)


if __name__ == "__main__":
    main()
