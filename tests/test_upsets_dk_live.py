"""Live DK/Pinnacle recorder: schedule (hourly + pre-start), floor stop, storage, report.
Fake clock + fake Odds API session; synthetic odds only."""

import pandas as pd
import pytest

from upsets import dk_live
from upsets.odds_api import OddsApi

T0 = pd.Timestamp("2026-10-27 08:00", tz="UTC")
KEY = "tennis_atp_paris_masters"
STARTS = [T0 + pd.Timedelta(hours=3), T0 + pd.Timedelta(hours=5)]


class Resp:
    def __init__(self, body, cost, remaining):
        self._b, self.status_code = body, 200
        self.headers = {"x-requests-last": str(cost), "x-requests-remaining": str(remaining)}

    def json(self):
        return self._b

    def raise_for_status(self):
        pass


def event(i, start, drift=0.0):
    return {"id": f"e{i}", "sport_key": KEY, "commence_time": start.isoformat(), "home_team": f"Fav {i}",
            "away_team": f"Dog {i}", "bookmakers": [
                {"key": "draftkings", "markets": [{"key": "h2h", "outcomes": [
                    {"name": f"Fav {i}", "price": 1.40 - drift}, {"name": f"Dog {i}", "price": 2.85 + drift}]}]},
                {"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
                    {"name": f"Fav {i}", "price": 1.43 - drift}, {"name": f"Dog {i}", "price": 3.05 + drift}]}]}]}


class Session:
    def __init__(self, clock, remaining=100):
        self.clock, self.remaining, self.odds_calls = clock, remaining, []

    def get(self, url, params=None, timeout=None):
        now = self.clock()
        if url.endswith("/sports"):
            return Resp([{"key": KEY, "active": True}, {"key": "soccer_epl", "active": True}], 0, self.remaining)
        if url.endswith("/events"):
            return Resp([{"id": f"e{i}", "commence_time": s.isoformat()} for i, s in enumerate(STARTS)], 0,
                        self.remaining)
        self.remaining -= 1
        self.odds_calls.append(now)
        drift = 0.05 * len(self.odds_calls)
        live = [event(i, s, drift) for i, s in enumerate(STARTS) if s > now]
        return Resp(live, 1, self.remaining)


class Clock:
    def __init__(self):
        self.t = T0

    def __call__(self):
        return self.t


def make(tmp_path, remaining=100, floor=10):
    clock = Clock()
    s = Session(clock, remaining)
    api = OddsApi(floor=floor, key="K", session=s, spend_log=tmp_path / "spend.log")
    rec = dk_live.Recorder(api, tmp_path / "live", tmp_path / "h2h.parquet", clock=clock, log=lambda *_: None)
    return clock, s, api, rec


def advance(clock, rec, minutes):
    for _ in range(minutes):
        if not rec.step():
            return False
        clock.t += pd.Timedelta(minutes=1)
    return True


def test_schedule_hourly_and_pre_start(tmp_path):
    clock, s, api, rec = make(tmp_path)
    advance(clock, rec, 6 * 60)
    mins = [int((t - T0).total_seconds() // 60) for t in s.odds_calls]
    # hourly 0, 60, 120; pre-start 165 (3h - 15 min); hourly 225; 285 = pre-start of the 5h match;
    # after the last start nothing is polled
    assert mins == [0, 60, 120, 165, 225, 285]
    assert len(list((tmp_path / "live" / KEY).glob("*.json.gz"))) == 6
    h2h = pd.read_parquet(tmp_path / "h2h.parquet")
    assert set(h2h["book"]) == {"draftkings", "pinnacle"} and set(h2h["why"]) == {"hourly", "pre-start"}
    assert "K" not in (tmp_path / "spend.log").read_text().split("\t")[1]


def test_stops_cleanly_at_floor(tmp_path):
    clock, s, api, rec = make(tmp_path, remaining=13, floor=10)
    ok = advance(clock, rec, 6 * 60)
    assert not ok and rec.stopped.startswith("floor reached")
    assert len(s.odds_calls) == 3 and s.remaining == 10      # never below the floor


def test_report(tmp_path):
    clock, s, api, rec = make(tmp_path)
    advance(clock, rec, 6 * 60)
    text = dk_live.report(pd.read_parquet(tmp_path / "h2h.parquet"), rec.calls)
    assert "Book margin" in text and "| draftkings | 2 |" in text and "| pinnacle | 2 |" in text
    assert "DK underdog probability minus Pinnacle's" in text
    assert "Price movement into the start" in text
    c = dk_live.closing_rows(pd.read_parquet(tmp_path / "h2h.parquet"))
    dk0 = c[(c["event_id"] == "e0") & (c["book"] == "draftkings")].iloc[0]
    assert dk0["n_snaps"] == 4 and dk0["snapshot_ts"] == T0 + pd.Timedelta(minutes=165)
    assert dk0["odds_1"] == pytest.approx(1.40 - 0.05 * 4)
