"""Moved-start flagging for the DK close data-quality check (upsets/dk_close_check.py), synthetic frames."""

import pandas as pd

from upsets import dk_close_check as cc


def test_moved_not_moved_and_unknown():
    ids = pd.DataFrame({"sack_row": [0, 1, 2, 3], "key": "k", "event_id": ["a", "b", "c", "d"],
                        "commence": pd.to_datetime(["2024-01-15 10:00", "2024-01-15 10:00",
                                                    "2022-01-15 10:00", "2024-01-15 10:00"])})
    finals = pd.DataFrame({"key": "k", "event_id": ["a", "b", "c"],
                           "final_start": pd.to_datetime(["2024-01-16 15:00", "2024-01-15 10:40",
                                                          "2022-01-16 15:00"]),
                           "last_seen": pd.to_datetime(["2024-01-16 16:00"] * 3)})
    season = pd.Series([2024, 2024, 2022, 2024])
    d = cc.flag(ids, finals, season=season).set_index("sack_row")
    assert d.loc[0, "status"] == "moved" and d.loc[0, "move_min"] == 29 * 60
    assert d.loc[1, "status"] == "not_moved"                  # 40 min: within MOVED_MIN
    assert d.loc[2, "status"] == "unknown"                    # before the in-play cache's seasons
    assert d.loc[3, "status"] == "not_moved" and pd.isna(d.loc[3, "move_min"])   # never seen later
