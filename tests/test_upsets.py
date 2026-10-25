"""Upset study: synthetic tennis-data sheets with known skills and known odds errors."""

import numpy as np
import pandas as pd
import pytest

from upsets import backtest, elo, features, load, odds, odds_api


def synth_sheet(seasons=range(2010, 2018), n_players=120, per_season=1500, margin=0.05,
                dog_bias=0.0, tour="atp", seed=1):
    """tennis-data-shaped rows. Bet365 prices = true prob (+ dog_bias on the underdog) with a
    proportional margin; Pinnacle = true prob with a 2% margin. Rounds 1-5 cycle."""
    rng = np.random.default_rng(seed)
    skill = rng.normal(0, 1.0, n_players)
    names = [f"Player{i} {chr(65 + i % 26)}." for i in range(n_players)]
    rank_of = {i: r + 1 for r, i in enumerate(np.argsort(-skill))}
    rows = []
    for y in seasons:
        for k in range(per_season):
            a, b = rng.choice(n_players, 2, replace=False)
            p_a = 1 / (1 + np.exp(-(skill[a] - skill[b])))
            a_wins = rng.random() < p_a
            w, l = (a, b) if a_wins else (b, a)
            p_w = p_a if a_wins else 1 - p_a
            # book view of the winner's probability, with the underdog's chance shaded by dog_bias
            q_w = p_w + (dog_bias if p_w < 0.5 else -dog_bias)
            q_w = float(np.clip(q_w, 0.02, 0.98))
            rows.append({
                "ATP": 1, "Location": "X", "Tournament": f"T{k // 31}", "Series": "ATP250",
                "Date": pd.Timestamp(f"{y}-01-01") + pd.Timedelta(days=int(k * 360 / per_season)),
                "Court": "Outdoor", "Surface": ["Hard", "Clay", "Grass"][k % 3],
                "Round": ["1st Round", "2nd Round", "3rd Round", "Quarterfinals", "Semifinals"][k % 5],
                "Best of": 3, "Winner": names[w], "Loser": names[l],
                "WRank": rank_of[w], "LRank": rank_of[l], "WPts": 1000, "LPts": 900,
                "W1": 6, "L1": 3, "Comment": "Completed",
                "B365W": 1 / (q_w * (1 + margin)), "B365L": 1 / ((1 - q_w) * (1 + margin)),
                "PSW": 1 / (p_w * 1.02), "PSL": 1 / ((1 - p_w) * 1.02),
            })
    return load.normalize(pd.DataFrame(rows), tour)


def frame_of(sheet):
    return features.build(elo.add_elo(sheet))


RULE = backtest.Rule(fav_rank_max=None, min_history=5, max_odds=20.0, min_select_bets=20)


def test_normalize_columns_and_void_rule():
    raw = pd.DataFrame({
        "WTA": [1, 1, 1], "Date": ["2024-01-02"] * 3, "Tier": ["WTA250"] * 3, "Surface": ["Hard"] * 3,
        "Round": ["1st Round"] * 3, "Best of": [3] * 3, "Winner": ["A X.", "B Y.", "C Z."],
        "Loser": ["D.", "E.", "F."], "WRank": [10, "NR", 3], "LRank": [50, 20, 4],
        "W1": [6, 3, np.nan], "L1": [2, 1, np.nan], "Comment": ["Completed", "Retired", "Walkover"],
        "B365W": [1.5, 1.01, 1.0], "B365L": [2.6, 15.0, 1.0],
    })
    m = load.normalize(raw, "wta")
    assert m["tier"].tolist() == ["WTA250"] * 3
    assert np.isnan(m.loc[1, "w_rank"])
    assert np.isnan(m.loc[2, "odds_b365_w"])          # 1.0 odds are data errors
    assert np.isnan(m.loc[0, "odds_ps_w"])            # book missing from file
    assert load.void_mask(m).tolist() == [False, True, True]  # retired at 3-1 in set 1, walkover


def test_first_set_complete():
    w = pd.Series([6, 7, 6, 5, 4])
    l = pd.Series([4, 6, 5, 3, 6])
    assert load.first_set_complete(w, l).tolist() == [True, True, False, False, True]


def test_devig():
    assert odds.devig_proportional(2.0, 2.0) == pytest.approx(0.5)
    p = odds.devig_power(np.array([1.25]), np.array([4.0]))     # 0.8 + 0.25 = 1.05
    assert 0.8 / 1.05 < p[0] < 0.8                               # between proportional and raw
    # power puts more margin on the longshot than proportional does
    assert 1 - p[0] < 1 - odds.devig_proportional(1.25, 4.0)
    assert odds.overround(2.0, 2.0) == pytest.approx(0.0)


def test_elo_is_pre_match():
    sheet = synth_sheet(seasons=[2010], per_season=300)
    a = elo.add_elo(sheet)
    flipped = sheet.copy()
    i = 150
    flipped.loc[i, ["winner", "loser"]] = flipped.loc[i, ["loser", "winner"]].to_numpy()
    b = elo.add_elo(flipped)
    # match i's own pre-match ratings don't depend on its result; later ones do
    assert a.loc[i, "w_elo"] == b.loc[i, "l_elo"] and a.loc[i, "l_elo"] == b.loc[i, "w_elo"]
    assert not np.allclose(a.loc[i + 1:, ["w_elo", "l_elo"]].to_numpy(), b.loc[i + 1:, ["w_elo", "l_elo"]].to_numpy())


def test_orientation_uses_odds_not_result():
    f = frame_of(synth_sheet(seasons=[2010], per_season=400))
    assert (f["odds_dog_ps"] >= f["odds_fav_ps"]).all()
    assert 0.2 < f["upset"].mean() < 0.45
    assert (f["p_mkt"] <= 0.5 + 1e-9).all()


def test_efficient_market_has_no_edge():
    f = frame_of(synth_sheet(margin=0.05))
    oos = backtest.walk_forward(f, [2014, 2015, 2016, 2017], RULE)
    every = backtest.summarize(oos)
    assert every["roi"] < 0                               # betting every dog pays the margin
    g = backtest.gate({0.0: oos})
    assert not g["pass"]


def test_planted_mispricing_is_found():
    # Bet365 shades underdogs 6 points too low -> dogs are overpriced; Pinnacle is right.
    f = frame_of(synth_sheet(margin=0.04, dog_bias=-0.06, seed=3))
    oos = backtest.walk_forward(f, [2014, 2015, 2016, 2017], RULE)
    s = backtest.summarize(oos[oos["bet_model"]])
    assert s["bets"] > 200 and s["roi"] > 0.03


def test_walk_forward_never_trains_on_test_season():
    f = frame_of(synth_sheet(seasons=range(2010, 2016), per_season=800))
    a = backtest.walk_forward(f, [2014, 2015], RULE)
    g = f.copy()
    g.loc[g["season"] == 2015, "upset"] = 1 - g.loc[g["season"] == 2015, "upset"]  # scramble results
    b = backtest.walk_forward(g, [2014, 2015], RULE)
    for col in ("p_model", "p_mktonly"):
        np.testing.assert_allclose(a.loc[a["test_season"] == 2015, col], b.loc[b["test_season"] == 2015, col])
        np.testing.assert_allclose(a.loc[a["test_season"] == 2014, col], b.loc[b["test_season"] == 2014, col])


def test_settle_void_and_haircut():
    bets = pd.DataFrame({"upset": [1, 0, 1], "void": [False, False, True], "odds_bet": [3.0, 2.5, 4.0],
                         "date": pd.to_datetime(["2020-01-01"] * 3)})
    assert backtest.settle(bets).tolist() == [2.0, -1.0, 0.0]
    assert backtest.payout_odds(pd.Series([3.0]), 0.1).iloc[0] == pytest.approx(2.8)
    s = backtest.summarize(bets)
    assert s["staked"] == 2 and s["pnl"] == 1.0 and s["voids"] == 1


class FakeResp:
    def __init__(self, body, headers):
        self._body, self.headers, self.status_code = body, headers, 200

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class FakeSession:
    def __init__(self, remaining):
        self.remaining, self.calls = remaining, []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params)))
        cost = 0 if url.endswith("/sports") else (10 if "/historical/" in url else 1)
        self.remaining -= cost
        body = [{"key": "tennis_atp_paris_masters", "active": True}, {"key": "soccer_epl", "active": True}] \
            if url.endswith("/sports") else []
        return FakeResp(body, {"x-requests-remaining": str(self.remaining), "x-requests-last": str(cost)})


def test_odds_api_budget_floor_and_spend_log(tmp_path):
    s = FakeSession(remaining=25)
    api = odds_api.OddsApi(floor=10, key="SECRET", session=s, spend_log=tmp_path / "spend.log")
    assert api.tennis_keys() == ["tennis_atp_paris_masters"]
    api.historical_odds("tennis_atp_paris_masters", "2025-10-28T12:00:00Z")   # 25 -> 15
    with pytest.raises(odds_api.BudgetError):
        api.historical_odds("tennis_atp_paris_masters", "2025-10-29T12:00:00Z")  # would hit 5 < 10
    log = (tmp_path / "spend.log").read_text()
    assert "SECRET" not in log and log.count("\n") == 1 and "\t10\t15" in log
    assert s.calls[-1][1]["bookmakers"] == "draftkings,pinnacle"


def test_parse_h2h_and_names():
    ev = [{"id": "e1", "sport_key": "tennis_atp_us_open", "commence_time": "2025-08-25T15:00:00Z",
           "home_team": "Alex de Minaur", "away_team": "Félix Auger-Aliassime",
           "bookmakers": [{"key": "draftkings", "last_update": "2025-08-25T14:59:00Z",
                           "markets": [{"key": "h2h", "outcomes": [
                               {"name": "Alex de Minaur", "price": 1.8},
                               {"name": "Félix Auger-Aliassime", "price": 2.05}]}]}]}]
    df = odds_api.parse_h2h(ev)
    assert df.loc[0, ["book", "odds_1", "odds_2"]].tolist() == ["draftkings", 1.8, 2.05]
    assert odds_api.td_key("De Minaur A.") in odds_api.full_name_keys("Alex de Minaur")
    assert odds_api.td_key("Auger-Aliassime F.") in odds_api.full_name_keys("Félix Auger-Aliassime")
