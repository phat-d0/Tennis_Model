"""Fallen-favourite study tests (docs/edge_favdip.md) on hand-built synthetic paths (never results)."""

import numpy as np
import pandas as pd

from swinglock.backtest.align import align
from swinglock.backtest.cashout import cash_paths, match_months
from swinglock.backtest.favdip import (band_gate, dip_minutes, dip_share, fav_band, favourite, favourites, main,
                                       paired, simulate_favdip, summarize, tag_set1)
from swinglock.backtest.walkforward import wf_settings

from test_backtest import CFG
from test_backtest_cashout import T0, book, matches, t

START = T0 + pd.Timedelta(seconds=100)
# A is the favourite at the last formed pre row (0.75). Row 0 is a listing placeholder (combined 1.90),
# row 180 a live placeholder (A ask 0.45 but combined 1.42, so not a dip). DIP50 at 200, DIP45 at 260, DIP40 at 300.
FALL = [(0, 0.95, 0.05, 0.95, 0.05), (30, 0.72, 0.70, 0.30, 0.28), (60, 0.75, 0.73, 0.27, 0.25),
        (150, 0.55, 0.53, 0.47, 0.45), (180, 0.45, 0.02, 0.97, 0.02), (200, 0.49, 0.47, 0.53, 0.51),
        (260, 0.43, 0.41, 0.59, 0.57), (300, 0.38, 0.36, 0.64, 0.62)]


def sim(q, m, slip=0.0):
    paths = cash_paths(align(q, m), m, CFG)
    return simulate_favdip(paths, CFG, slip, {r.match_id: r.scheduled_start for r in m.itertuples()}), paths


def row(df, rule, match="M1"):
    return df[(df["rule"] == rule) & (df["match_id"] == match)].iloc[0]


def test_bands():
    assert fav_band(0.50) == "50-60" and fav_band(0.5999) == "50-60" and fav_band(0.60) == "60-80"
    assert fav_band(0.80) == "80-97" and fav_band(0.97) == "80-97"
    assert fav_band(0.49) is None and fav_band(0.975) is None


def test_favourite_start_and_dips_skip_placeholder_books():
    pos, paths = sim(book(FALL), matches("M1", winner="A"))
    assert favourite(paths[0]) == (2, "A")
    assert set(pos["rule"]) == {"START", "DIP50", "DIP45", "DIP40"} and (pos["band"] == "60-80").all()
    s, d50, d45, d40 = (row(pos, r) for r in ("START", "DIP50", "DIP45", "DIP40"))
    assert s["entry_ask"] == 0.75 and s["entry_ts"] == t(60) and s["minutes_from_start"] == -40 / 60
    assert d50["entry_ask"] == 0.49 and d50["entry_ts"] == t(200)          # 180 is a placeholder, skipped
    assert d45["entry_ts"] == t(260) and d40["entry_ts"] == t(300)
    assert d50["minutes_from_start"] == 100 / 60
    for r in (s, d50):
        assert r["contracts"] == 10 and r["entry_cost"] > 10 * r["entry_ask"]       # taker fee
        assert np.isclose(r["rule_pnl"], 10 * 1.0 - r["entry_cost"])
    lost, _ = sim(book(FALL), matches("M1", winner="B"))                    # settlement only moves P&L
    for rule in ("START", "DIP50"):
        a, b = row(pos, rule), row(lost, rule)
        assert a["entry_ts"] == b["entry_ts"] and a["entry_cost"] == b["entry_cost"]
        assert np.isclose(b["rule_pnl"], -b["entry_cost"])


def test_slippage_fair_price_and_no_dip():
    pos, _ = sim(book(FALL), matches("M1", winner="A"), slip=0.01)
    s0, _ = sim(book(FALL), matches("M1", winner="A"))
    assert row(pos, "START")["entry_ask"] == 0.75
    diff = row(pos, "START")["entry_cost"] - row(s0, "START")["entry_cost"]
    assert 0.08 < diff < 0.10                                           # +1c x 10, fee 0.7 x 0.25 -> 0.76 x 0.24
    fair, _ = sim(book(FALL), matches("M1", winner=None, settle=(0.6, 0.4)))
    assert np.isclose(row(fair, "DIP50")["rule_pnl"], 10 * 0.6 - row(fair, "DIP50")["entry_cost"])
    flat = [r for r in FALL if r[0] < 150] + [(200, 0.70, 0.68, 0.32, 0.30)]
    pos, _ = sim(book(flat), matches("M1", winner="A"))
    assert list(pos["rule"]) == ["START"]


def test_exclusions_tie_high_and_no_formed_pre():
    tie = [(30, 0.50, 0.48, 0.50, 0.48), (200, 0.45, 0.43, 0.57, 0.55)]
    high = [(30, 0.98, 0.96, 0.03, 0.01), (200, 0.45, 0.43, 0.57, 0.55)]
    none = [(0, 0.95, 0.05, 0.95, 0.05), (200, 0.45, 0.43, 0.57, 0.55)]
    q = pd.concat([book(tie, "T"), book(high, "H"), book(none, "N")], ignore_index=True)
    pos, paths = sim(q, matches("T", "H", "N", winner="A"))
    assert pos.empty and favourites(paths).empty


def test_depth_caps_size_and_zero_depth_moves_to_next_dip_row():
    rows = FALL[:6] + [(230, 0.48, 0.46, 0.54, 0.52)] + FALL[6:]
    q = book(rows)
    a = q["side"] == "A"
    q.loc[a & (q["ts"] == t(60)), "ask_size"] = 4.0
    q.loc[a & (q["ts"] == t(200)), "ask_size"] = 0.0
    pos, _ = sim(q, matches("M1", winner="A"))
    assert row(pos, "START")["contracts"] == 4.0
    assert row(pos, "DIP50")["entry_ts"] == t(230)


def two_matches():
    stay = [(30, 0.82, 0.80, 0.20, 0.18), (60, 0.85, 0.83, 0.17, 0.15), (200, 0.90, 0.88, 0.12, 0.10)]
    q = pd.concat([book(FALL, "M1"), book(stay, "M2")], ignore_index=True)
    return sim(q, matches("M1", "M2", winner="A"))


def test_dip_share_paired_summary_and_minutes():
    pos, paths = two_matches()
    favs = favourites(paths)
    assert set(zip(favs["match_id"], favs["band"])) == {("M1", "60-80"), ("M2", "80-97")}
    sh = dip_share(favs, pos).set_index("band")
    assert sh.loc["60-80", "share_dip50"] == 1.0 and sh.loc["80-97", "share_dip50"] == 0.0
    assert sh.loc["60-80", "favourites"] == 1
    pr = paired(pos, ("band", "slippage"))
    assert len(pr) == 1 and pr.iloc[0]["band"] == "60-80" and pr.iloc[0]["matches"] == 1
    assert pr.iloc[0]["diff_pc"] > 0                                     # A won: the cheaper entry wins more
    sm = summarize(pos, ("band", "rule")).set_index(["band", "rule"])
    assert sm.loc[("60-80", "START"), "win_rate"] == 1.0
    assert np.isclose(sm.loc[("80-97", "START"), "mean_ask"], 0.85)
    assert sm.loc[("80-97", "START"), "mean_all_in"] > 0.85
    mn = dip_minutes(pos.assign(tier="atp"))
    assert len(mn) == 1 and np.isclose(mn.iloc[0]["min_p50"], 100 / 60)


def test_set1_split():
    pos, _ = two_matches()
    sets = pd.DataFrame(dict(match_id=["M1", "M1"], set_no=[1, 2], close_time=[t(250), t(400)]))
    tagged = tag_set1(pos, sets)
    d = tagged.set_index(["match_id", "rule"])["set1"]
    assert d[("M1", "DIP50")] == "before" and d[("M1", "DIP45")] == "after" and d[("M2", "START")] == "no_set1_data"
    assert (tag_set1(pos, None)["set1"] == "no_set1_data").all()


def monthly(n_per_month=8, n_months=5, winner="A"):
    qs, ms = [], []
    for k in range(n_months):
        for i in range(n_per_month):
            base = pd.Timestamp(f"2026-0{k + 1}-{i + 1:02d} 12:00", tz="UTC")
            qs.append(book(FALL, f"M{k}-{i}", base))
            ms.append(matches(f"M{k}-{i}", winner=winner, start=base + pd.Timedelta(seconds=100)))
    return pd.concat(ms, ignore_index=True), pd.concat(qs, ignore_index=True)


def test_band_gate():
    m, q = monthly()
    paths = cash_paths(align(q, m), m, CFG)
    by_slip = {s: simulate_favdip(paths, CFG, s) for s in (0.0, 0.01)}
    st = wf_settings(CFG)
    g = band_gate(by_slip, match_months(paths), "60-80", st)
    assert g.passed, g.reasons
    assert g.gate.set_index("slippage").loc[0.01, "entries"] == 40 and len(g.folds) == 5
    empty = band_gate(by_slip, match_months(paths), "80-97", st)
    assert not empty.passed and any("entries; need" in r for r in empty.reasons)
    m, q = monthly(winner="B")
    paths = cash_paths(align(q, m), m, CFG)
    lose = band_gate({s: simulate_favdip(paths, CFG, s) for s in (0.0, 0.01)}, match_months(paths), "60-80", st)
    assert not lose.passed and any("not positive" in r for r in lose.reasons)


def test_cli_end_to_end(tmp_path):
    m, q = monthly(n_per_month=2)
    data = tmp_path / "data"
    data.mkdir()
    m.to_parquet(data / "matches.parquet")
    q.to_parquet(data / "quotes.parquet")
    pd.DataFrame(dict(match_id=["M0-0"], set_no=[1], close_time=[pd.Timestamp("2026-01-01 12:04", tz="UTC")])
                 ).to_parquet(data / "sets.parquet")
    out = tmp_path / "out"
    assert main(["--data", str(data), "--out", str(out)]) == 0
    for f in ("favdip_summary.csv", "favdip_dip_share.csv", "favdip_paired.csv", "favdip_dip_minutes.csv",
              "favdip_set1.csv", "favdip_gate_60-80.csv", "favdip_months_80-97.csv", "favdip_summary.md"):
        assert (out / f).exists()
    assert not any("position" in p.name for p in out.iterdir())          # aggregates only
    md = (out / "favdip_summary.md").read_text()
    assert "DIP50, band 60-80" in md and "selects START's bad matches" in md and "set 1" in md
    s1 = pd.read_csv(out / "favdip_set1.csv")
    assert set(s1["set1"]) == {"before", "no_set1_data"}
    assert main(["--data", str(tmp_path / "none"), "--out", str(out)]) == 0
