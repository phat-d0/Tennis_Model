"""Sackmann loader + seed base rates, on tiny synthetic CSVs (no real rows committed)."""

import numpy as np
import pandas as pd
import pytest

from upsets import elo, sackmann, seeds

COLS = ["tourney_id", "tourney_name", "surface", "draw_size", "tourney_level", "tourney_date",
        "match_num", "winner_id", "winner_seed", "winner_entry", "winner_name", "loser_id",
        "loser_seed", "loser_entry", "loser_name", "score", "best_of", "round",
        "winner_rank", "winner_rank_points", "loser_rank", "loser_rank_points"]


def row(tid, rnd, w, l, score="6-3 6-4", date=20240101, num=1, draw=32, level="A",
        name="Town", surface="Hard", ws=None, ls=None, wentry=None, lentry=None, wid=None, lid=None):
    return dict(zip(COLS, [tid, name, surface, draw, level, date, num, wid or w, ws, wentry, w,
                           lid or l, ls, lentry, l, score, 3, rnd, 10, 1000, 50, 500]))


def frame(rows):
    return pd.DataFrame(rows, columns=COLS)


def test_parse_score():
    assert sackmann.parse_score("6-3 6-4") == ("Completed", 6.0, 3.0)
    assert sackmann.parse_score("7-6(5) 2-1 RET") == ("Retired", 7.0, 6.0)
    assert sackmann.parse_score("W/O")[0] == "Walkover"
    assert sackmann.parse_score(" W/O")[0] == "Walkover"
    assert sackmann.parse_score("Walkover")[0] == "Walkover"
    c, w1, l1 = sackmann.parse_score("DEF")
    assert c == "Disqualified" and np.isnan(w1)
    assert sackmann.parse_score("6-4 Played and unfinished")[0] == "Unfinished"


def test_normalize_rounds_void_levels():
    raw = frame([
        row("t1", "R32", "A", "B", "4-1 RET", draw=28, num=1),         # 28 draw: R32 = round 1
        row("t1", "R16", "C", "D", "6-3 1-0 RET", draw=28, num=2),     # round 2, set 1 done
        row("t1", "QF", "E", "F", "W/O", draw=28, num=3),
        row("t2", "R128", "G", "H", draw=128, level="G", surface="clay"),
        row("t2", "R64", "G", "I", "7-6(4) RET", draw=128, level="G"),
        row("t3", "R32", "J", "K", draw=32, level="I", name="Town 125"),   # 125 event: dropped
        row("t4", "R32", "J", "K", draw=32, level="50+H"),                  # ITF level: dropped
    ])
    n = sackmann.normalize(raw, "wta")
    assert list(n["tourney_id"]) == ["t1", "t1", "t1", "t2", "t2"]
    assert list(n["round_idx"]) == [1, 2, 3, 1, 2]
    assert list(n["void"]) == [True, False, True, False, False]
    assert list(n["comment"]) == ["Retired", "Retired", "Walkover", "Completed", "Retired"]
    assert list(n["level_group"]) == ["other", "other", "other", "slam", "slam"]
    assert n.loc[3, "surface"] == "Clay"
    assert n["date"].iloc[0] == pd.Timestamp("2024-01-01")


def test_level_groups():
    assert sackmann.level_group("atp", "M") == "1000"
    assert sackmann.level_group("wta", "PM") == "1000"
    assert sackmann.level_group("wta", "P") == "other"
    assert sackmann.level_group("atp", "A") == "other"
    assert sackmann.level_group("atp", "D") == "team"
    assert sackmann.level_group("wta", "F") == "finals"


def _write(tmp_path, tour, name, rows):
    d = tmp_path / tour
    d.mkdir(exist_ok=True)
    frame(rows).to_csv(d / name, index=False)


def test_load_order_years_and_lower_files(tmp_path):
    _write(tmp_path, "atp", "atp_matches_2024.csv", [
        row("b", "R16", "A", "C", date=20240108, num=5),
        row("b", "R32", "A", "B", date=20240108, num=9),
        row("b", "R32", "C", "D", date=20240108, num=2),
        row("a", "F", "X", "Y", date=20240101, num=1, draw=4),
        row("f", "RR", "X", "Y", date=20240101, num=7, draw=8, level="F"),
    ])
    _write(tmp_path, "atp", "atp_matches_2023.csv", [row("z", "R32", "P", "Q", date=20230101)])
    _write(tmp_path, "atp", "atp_matches_qual_chall_2024.csv",
           [row("c", "Q1", "A", "Z", date=20240108, level="Q")])
    df = sackmann.load(tmp_path, tours=("atp",), start=2024)
    assert list(zip(df["tourney_id"], df["round"])) == [
        ("f", "RR"), ("a", "F"), ("b", "R32"), ("b", "R32"), ("b", "R16")]
    assert list(df.loc[df["tourney_id"] == "b", "match_num"]) == [2, 9, 5]
    assert len(sackmann.load(tmp_path, tours=("atp",))) == 6
    low = sackmann.load(tmp_path, tours=("atp",), start=2024, lower=True)
    assert (low.loc[low["tourney_id"] == "c", "level_group"] == "lower").all()
    # the qualifying match (unsized round) is played before the main draw of the same week
    assert low.index[low["tourney_id"] == "c"][0] < low.index[(low["tourney_id"] == "b")][0]


def test_elo_keys_by_id_not_name():
    df = sackmann.normalize(frame([
        row("t", "R32", "Same Name", "B", wid="1", lid="2", num=1),
        row("t", "R32", "C", "Same Name", wid="3", lid="4", num=2),
    ]), "atp")
    by_id = elo.add_elo(df, keys=("winner_id", "loser_id"))
    assert by_id.loc[1, "l_elo"] == elo.START  # player 4 never played before
    by_name = elo.add_elo(df)
    assert by_name.loc[1, "l_elo"] > elo.START  # names merge the two players


def _tourney(tid, date, rows_spec, draw=28, level="A"):
    return [row(tid, r, w, l, s, date=date, num=i, draw=draw, level=level, ws=ws, ls=ls)
            for i, (r, w, l, s, ws, ls) in enumerate(rows_spec)]


def test_seed_matches_and_exits():
    rows = _tourney("t1", 20240101, [
        ("R32", "U1", "S5", "6-3 6-3", None, 5),     # seed 5 loses round 1
        ("R32", "S6", "U2", "6-3 6-3", 6, None),     # seed 6 wins round 1
        ("R32", "U3", "S7", "2-1 RET", None, 7),     # seed retires in set 1: void, left out
        ("R32", "S8", "S9", "6-3 6-3", 8, 9),        # seed vs seed: left out of match view
        ("R16", "U4", "S1", "6-3 6-3", None, 1),     # top seed (bye) loses its first match
        ("R16", "S6", "U1", "6-3 6-3", 6, None),
        ("QF", "S6", "S8", "6-3 6-3", 6, 8),
        ("SF", "S6", "U4", "6-3 6-3", 6, None),
        ("F", "S6", "U9", "6-3 6-3", 6, None),
    ])
    rows += _tourney("rr", 20240101, [("RR", "S1", "U1", "6-3 6-3", 1, None),
                                     ("R32", "U1", "S2", "6-3 6-3", None, 2)], draw=32)
    rows += _tourney("dc", 20240101, [("R32", "U1", "S2", "6-3 6-3", None, 2)], level="D")
    df = elo.add_elo(sackmann.normalize(frame(rows), "atp"), keys=("winner_id", "loser_id"))
    m = seeds.seed_matches(df)
    assert sorted(zip(m["seed"], m["seed_lost"])) == [(1, 1), (5, 1), (6, 0), (6, 0)]
    assert list(m["band"].astype(str)) == ["5-8", "5-8", "1-4", "5-8"]
    assert m["p_elo_lose"].between(0, 1).all()

    x = seeds.seed_exits(df).set_index("seed")
    assert x.loc[1, "out_early"] == 1 and x.loc[5, "out_early"] == 1
    assert x.loc[6, "out_early"] == 0       # won the event
    assert x.loc[8, "out_early"] == 0       # lost in the QF
    assert x.loc[9, "out_early"] == 1       # lost round 1 to seed 8
    assert 7 not in x.index                 # exit by early retirement is void


def test_report_smoke():
    rng = np.random.default_rng(0)
    rows = []
    for t in range(30):
        for i in range(8):
            seeded_wins = rng.random() < 0.7
            s, u = f"S{i}", f"U{t}_{i}"
            w, l, ws, ls = (s, u, i + 1, None) if seeded_wins else (u, s, None, i + 1)
            rows.append(row(f"t{t}", "R32", w, l, date=20150105 + 7 * t, num=i, ws=ws, ls=ls))
    df = elo.add_elo(sackmann.normalize(frame(rows), "atp"), keys=("winner_id", "loser_id"))
    text = seeds.report(df, 2015, 2015)
    assert "By tour and seed band" in text and "| atp | 1-4 |" in text


@pytest.mark.parametrize("seed,label", [(1, "1-4"), (4, "1-4"), (5, "5-8"), (16, "9-16"),
                                        (32, "17-32")])
def test_band(seed, label):
    assert str(seeds.band(pd.Series([float(seed)]))[0]) == label
    assert pd.isna(seeds.band(pd.Series([33.0]))[0])
