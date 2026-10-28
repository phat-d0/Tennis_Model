"""DK in-play credit dry run (upsets/dk_inplay.py), synthetic frames only."""

import pandas as pd

from upsets import dk_inplay as di


def w(rows):
    return pd.DataFrame([{"key": k, "commence": pd.Timestamp(c, tz="UTC"), "dur": d, "season": int(c[:4]),
                          "level": "slam"} for k, c, d in rows])


def test_overlapping_matches_of_one_key_share_snapshots():
    one = w([("k", "2024-01-15 10:00", 60)])
    assert len(di.slots(one, 5, 0)) == 13                      # 10:00 .. 11:00 inclusive
    both = w([("k", "2024-01-15 10:00", 60), ("k", "2024-01-15 10:30", 60)])
    assert len(di.slots(both, 5, 0)) == 19                     # 10:00 .. 11:30: shared half hour counted once
    other_key = w([("k", "2024-01-15 10:00", 60), ("j", "2024-01-15 10:00", 60)])
    assert di.credits(other_key, 5, 0) == 2 * 13 * 10


def test_slack_and_the_ten_minute_archive_before_sept_2022():
    m = w([("k", "2024-01-15 10:02", 60)])
    assert min(x for _, x in di.slots(m, 5, 0)) == pd.Timestamp("2024-01-15 10:00", tz="UTC")
    assert len(di.slots(m, 5, 60)) == len(di.slots(m, 5, 0)) + 12
    old = w([("k", "2021-01-15 10:00", 60)])
    assert len(di.slots(old, 5, 0)) == len(di.slots(old, 10, 0)) == 7   # 10-min snapshots only back then


def test_windows_fill_missing_minutes_with_the_best_of_median():
    sack = pd.DataFrame({"minutes": [90.0, 110.0, None, 400.0], "best_of": [3, 3, 3, 5],
                         "season": [2024] * 4, "level_group": ["slam"] * 4})
    priced = pd.DataFrame({"sack_row": [0, 1, 2, 3], "key": "k",
                           "commence": pd.to_datetime(["2024-01-15 10:00"] * 4, utc=True)})
    got = di.windows(priced, sack)
    assert list(got["dur"]) == [90.0, 110.0, 100.0, di.MAX_MINUTES]
