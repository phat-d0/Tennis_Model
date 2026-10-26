import json
from pathlib import Path

import pandas as pd

from swinglock.collectors import kalshi_sets as ks

FIX = json.loads((Path(__file__).parent / "fixtures/kalshi/set_winner_events_trimmed_2026-10-26.json").read_text())


class FakeClient:
    def __init__(self):
        self.calls = []

    def events(self, series, status=None):
        self.calls.append(("events", series, status))
        return iter(FIX["events"] if series == "KXATPSETWINNER" else [])

    def historical_markets(self, series):
        self.calls.append(("historical_markets", series))
        return iter(FIX["historical_markets"] if series == "KXATPSETWINNER" else [])


def _matches(*ids):
    rows = []
    for mid, a, b in ids:
        rows.append({"match_id": mid, "instrument_a": f"{mid}-{a}", "instrument_b": f"{mid}-{b}"})
    return pd.DataFrame(rows)


def test_parse_set_event():
    assert ks.parse_set_event("KXATPSETWINNER-26OCT24FARBRU-2") == ("KXATPMATCH-26OCT24FARBRU", 2)
    assert ks.parse_set_event("KXWTASETWINNER-26OCT25RYBFER-1") == ("KXWTAMATCH-26OCT25RYBFER", 1)
    assert ks.parse_set_event("KXATPMATCH-26OCT24FARBRU") is None
    assert ks.parse_set_event("KXATPTOTALSETS-26OCT24FARBRU-2") is None


def test_set_row_decided_side_from_code_order():
    ev = FIX["events"][0]  # set 2 of Faria vs Brunold, Brunold won it
    r = ks.set_row(ev["event_ticker"], ev["markets"])
    assert r["match_id"] == "KXATPMATCH-26OCT24FARBRU" and r["set_no"] == 2
    assert r["status"] == "decided" and r["winner_side"] == "B"  # FAR listed first -> A
    assert r["close_time"] == pd.Timestamp("2026-10-24T13:42:33Z")
    assert r["settlement_ts"] == pd.Timestamp("2026-10-24T13:48:32.395816Z")


def test_set_row_uses_match_sides_when_given():
    ev = FIX["events"][0]
    r = ks.set_row(ev["event_ticker"], ev["markets"], {"BRU": "A", "FAR": "B"})
    assert r["winner_side"] == "A"


def test_set_row_fair_price_has_no_winner():
    ev = FIX["events"][2]
    r = ks.set_row(ev["event_ticker"], ev["markets"])
    assert r["status"] == "fair_price" and r["winner_side"] is None


def test_collect_joins_historical_and_filters_to_matches():
    matches = _matches(("KXATPMATCH-26OCT24FARBRU", "FAR", "BRU"),
                       ("KXATPMATCH-26AUG18ZHEMUS", "ZHE", "MUS"))
    client = FakeClient()
    stats = {}
    df = ks.collect(client, matches, stats=stats)
    assert list(df.columns) == ks.SET_COLUMNS
    assert set(df["match_id"]) == {"KXATPMATCH-26OCT24FARBRU", "KXATPMATCH-26AUG18ZHEMUS"}  # STRBUB not in matches
    far = df[df["match_id"] == "KXATPMATCH-26OCT24FARBRU"]
    assert far["set_no"].tolist() == [1, 2] and far["winner_side"].tolist() == ["B", "B"]
    hist = df[df["match_id"] == "KXATPMATCH-26AUG18ZHEMUS"].iloc[0]  # pre-cutoff: from /historical/markets
    assert hist["status"] == "decided" and hist["winner_side"] == "B"
    assert stats["historical_events"]["KXATPSETWINNER"] == 1
    assert ("historical_markets", "KXATPSETWINNER") in client.calls
    assert str(df["close_time"].dtype) == "datetime64[ns, UTC]"


def test_collect_without_matches_keeps_everything():
    df = ks.collect(FakeClient(), None)
    assert len(df) == 4
    assert df["status"].value_counts().to_dict() == {"decided": 3, "fair_price": 1}
