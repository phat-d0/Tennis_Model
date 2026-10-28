"""Cash-out study tests (docs/edge_cashout.md) on hand-built synthetic paths (never results)."""

import numpy as np
import pandas as pd
import pytest

from swinglock.backtest.align import align
from swinglock.backtest.cashout import (DOG_CURVE_RULES, RULES, cash_paths, mismatch_positions, mismatch_summary,
                                        price_distribution, ranked_positions, target_bid, unranked_positions, dog_positions, dog_summary,
                                        dogl_walk_forward, fee_vec, fixed_rule_gate, identity_check, main,
                                        match_months, simulate_cashout, summarize, tag_set_split,
                                        walk_forward_cashout)
from swinglock.backtest.walkforward import wf_settings
from swinglock.fees import FeeModel
from swinglock.schema import MATCH_COLUMNS, QUOTE_COLUMNS, conform

from test_backtest import CFG

T0 = pd.Timestamp("2026-01-01 12:00", tz="UTC")
FM = FeeModel(rounding_increment=0.01)


def t(sec, base=T0):
    return base + pd.Timedelta(seconds=sec)


def book(rows, match="M1", base=T0, bsize=np.nan):
    """rows: (sec, ask_a, bid_a, ask_b, bid_b)."""
    recs = [dict(ts=t(s, base), match_id=match, side=side, ask=a, ask_size=np.nan, bid=b, bid_size=bsize,
                 source="candle")
            for s, aa, ba, ab, bb in rows for side, a, b in (("A", aa, ba), ("B", ab, bb))]
    return conform(pd.DataFrame(recs), QUOTE_COLUMNS)


def matches(*ids, winner="B", start=T0 + pd.Timedelta(seconds=100), settle=(np.nan, np.nan)):
    return conform(pd.DataFrame([dict(match_id=m, winner=winner, tier="atp", fee_type="quadratic",
                                      fee_multiplier=1.0, scheduled_start=start, settle_a=settle[0],
                                      settle_b=settle[1]) for m in ids]), MATCH_COLUMNS)


def positions(q, m, slip=0.0, cfg=CFG):
    return simulate_cashout(cash_paths(align(q, m), m, cfg), cfg, slip)


def pick(df, mode="E1", side="A", rule="T=5c"):
    return df[(df["mode"] == mode) & (df["side"] == side) & (df["rule"] == rule)].iloc[0]


# A: entry 0.40 pre-match, bid rises 0.38 -> 0.48 -> 0.49 (pre), then in play 0.55, B wins.
PATH = [(0, 0.40, 0.38, 0.62, 0.60), (60, 0.50, 0.48, 0.52, 0.50), (90, 0.51, 0.49, 0.51, 0.49),
        (200, 0.57, 0.55, 0.45, 0.43)]


def test_fee_vec_matches_fee_model():
    p = np.linspace(0.01, 0.99, 99)
    for n in (1, 10, 37.5, 100):
        assert np.allclose(fee_vec(FM, p, n), [FM.fee(x, n) for x in p])


def test_take_profit_exit_and_delta():
    df = positions(book(PATH), matches("M1"))
    r = pick(df)
    # entry 10 @ 0.40: 4.00 + fee 0.17 = 4.17 (0.417 all-in); T=5c needs net bid >= 0.467:
    # 0.48 -> 0.48 - 0.018 = 0.462 (no); 0.49 -> 0.49 - 0.018 = 0.472 (yes) at t=90
    assert (r["entry_ts"], r["entry_phase"], r["band"]) == (t(0), "pre", "40-60c")
    assert r["locked"] and (r["exit_ts"], r["exit_phase"], r["exit_bid"]) == (t(90), "pre", 0.49)
    assert r["exit_value"] == pytest.approx(4.90 - 0.18) and r["minutes_to_exit"] == pytest.approx(1.5)
    assert r["hold_pnl"] == pytest.approx(-4.17)                        # B wins
    assert r["rule_pnl"] == pytest.approx(4.72 - 4.17) and r["pnl"] == pytest.approx(4.72)
    # T=15c needs >= 0.567: 0.55 -> 0.55 - 0.018 = 0.532, never; delta 0, P&L = hold
    r15 = pick(df, rule="T=15c")
    assert not r15["locked"] and r15["pnl"] == 0 and r15["rule_pnl"] == pytest.approx(-4.17)
    assert len(df) == 2 * 2 * len(RULES)                                 # E1 + E2, both sides, 9 rules


def test_e2_enters_at_first_live_row_and_unknown_start_is_excluded():
    df = positions(book(PATH), matches("M1"))
    r = pick(df, mode="E2", side="A", rule="T=3c")
    assert (r["entry_ts"], r["entry_phase"], r["entry_ask"]) == (t(200), "live", 0.57)
    assert not r["locked"]                                               # no later row
    assert positions(book(PATH), matches("M1", start=None)).empty


def test_no_lookahead_and_settlement_only_in_hold():
    q, m = book(PATH), matches("M1")
    full = pick(positions(q, m))
    cut = pick(positions(q[q["ts"] <= t(90)], m))
    assert (cut["exit_ts"], cut["exit_value"]) == (full["exit_ts"], full["exit_value"])
    assert not pick(positions(q[q["ts"] < t(90)], m))["locked"]           # exit waits for the 0.49 bid
    won = pick(positions(q, matches("M1", winner="A")))
    assert won["exit_ts"] == full["exit_ts"] and won["rule_pnl"] == pytest.approx(full["rule_pnl"])
    assert won["pnl"] == pytest.approx(0.55 - (10 - 4.17))                  # cashing out a winner costs


def test_fair_price_hold_and_slippage():
    df = positions(book(PATH), matches("M1", winner=None, settle=(0.45, 0.55)))
    assert pick(df)["hold_pnl"] == pytest.approx(4.5 - 4.17)
    s = pick(positions(book(PATH), matches("M1"), slip=0.01))
    # entry 0.41: 4.10 + fee 0.17 = 4.27; sale at bid - 1c: 0.48 -> 0.47 - 0.018 = 0.452 < 0.477;
    # 0.49 -> 0.48 - 0.018 = 0.462 < 0.477; in play 0.55 -> 0.54 - fee 0.18 => 0.522 >= 0.477
    assert s["entry_cost"] == pytest.approx(4.27) and s["exit_ts"] == t(200) and s["exit_phase"] == "live"
    assert s["exit_value"] == pytest.approx(5.40 - 0.18)


def test_bid_depth_and_relative_rule():
    shallow = pick(positions(book(PATH, bsize=5.0), matches("M1")))
    assert not shallow["locked"]                                          # 5 < 10 contracts on the bid
    longshot = [(0, 0.10, 0.08, 0.92, 0.90), (60, 0.24, 0.22, 0.78, 0.76), (90, 0.25, 0.23, 0.77, 0.75)]
    r = pick(positions(book(longshot), matches("M1")), rule="k=2")
    # entry 1.00 + fee 0.07 = 1.07 (0.107); k=2 needs >= 0.214: 0.22 -> 0.22 - 0.012 = 0.208 (no);
    # 0.23 -> 0.23 - 0.013 = 0.217 (yes)
    assert r["band"] == "<20c" and r["exit_ts"] == t(90) and r["exit_value"] == pytest.approx(2.30 - 0.13)


def test_identity_check_and_summary():
    rows = [(s, a, round(1 - b_ask, 6), b_ask, round(1 - a, 6))
            for s, a, b_ask in [(0, 0.40, 0.62), (60, 0.50, 0.52), (200, 0.57, 0.45)]]
    al = align(book(rows), matches("M1"))
    ident = identity_check(al)
    assert ident["rows"] == 6 and ident["max_abs_gap"] == pytest.approx(0) and ident["share_within_tol"] == 1
    off = [(0, 0.40, 0.36, 0.62, 0.60), *PATH[1:]]                       # bid(A) 0.36 + ask(B) 0.62 = 0.98
    bad = identity_check(align(book(off), matches("M1")))
    assert bad["max_abs_gap"] == pytest.approx(0.02) and bad["share_within_tol"] == pytest.approx(7 / 8)
    s = summarize(positions(book(PATH), matches("M1")))
    row = s[(s["mode"] == "E1") & (s["rule"] == "T=5c")].iloc[0]
    assert row["entries"] == 2 and row["triggers"] == 1 and row["trigger_rate"] == 0.5
    assert row["delta_trig_pc"] == pytest.approx(0.472)                  # per contract
    assert row["sd_rule_pc"] < row["sd_hold_pc"]


# ---- walk-forward gate and CLI ------------------------------------------------
# A rises to 0.80 then B wins: cashing A out always beats holding it.

RISE = [(0, 0.40, 0.38, 0.62, 0.60), (60, 0.60, 0.58, 0.42, 0.40), (90, 0.82, 0.80, 0.20, 0.18),
        (200, 0.05, 0.03, 0.97, 0.95)]


def monthly(n_per_month=12, n_months=5):
    qs, ms = [], []
    for k in range(n_months):
        for i in range(n_per_month):
            base = pd.Timestamp(f"2026-0{k + 1}-{i + 1:02d} 12:00", tz="UTC")
            qs.append(book(RISE, f"M{k}-{i}", base))
            ms.append(matches(f"M{k}-{i}", start=base + pd.Timedelta(seconds=100)))
    return pd.concat(ms, ignore_index=True), pd.concat(qs, ignore_index=True)


def test_walk_forward_gate_on_delta():
    m, q = monthly()
    paths = cash_paths(align(q, m), m, CFG)
    by_slip = {s: simulate_cashout(paths, CFG, s) for s in (0.0, 0.01)}
    wf = walk_forward_cashout(by_slip, match_months(paths), "E1", CFG)
    assert len(wf.folds) == 4 and wf.passed, wf.reasons
    assert (wf.folds["mode"] == "E1").all() and wf.gate.set_index("slippage").loc[0.01, "oos_trades"] == 48
    e2 = walk_forward_cashout(by_slip, match_months(paths), "E2", CFG)
    assert not e2.passed                                                 # no later row after the live entry


def test_cli_end_to_end(tmp_path):
    m, q = monthly(n_per_month=2)
    data = tmp_path / "data"
    data.mkdir()
    m.to_parquet(data / "matches.parquet")
    q.to_parquet(data / "quotes.parquet")
    out = tmp_path / "out"
    assert main(["--data", str(data), "--out", str(out)]) == 0
    for f in ("cashout_summary.csv", "cashout_bands.csv", "cashout_exit_phase.csv", "cashout_set_split.csv",
              "cashout_dog50.csv", "cashout_dog30_band.csv", "cashout_dog50_gate.csv", "cashout_wf_gate_E1.csv",
              "cashout_wf_folds_E2.csv", "cashout_curve20.csv", "cashout_curve30.csv", "cashout_dogl_gate.csv",
              "cashout_dogl_folds.csv", "cashout_summary.md"):
        assert (out / f).exists()
    assert not (out / "cashout_positions.csv").exists()                  # aggregates only
    md = (out / "cashout_summary.md").read_text()
    assert "Identity check" in md and "Walk-forward gate, E1" in md and "DOG50" in md and "Set end" in md
    assert "exit-level curve" in md and "DOGL gate" in md
    assert main(["--data", str(tmp_path / "none"), "--out", str(out)]) == 0


# ---- amendment 2026-10-28: level rules, set split, DOG50 --------------------------

def test_level_rule_is_take_profit_only():
    df = positions(book(PATH), matches("M1"))
    r = pick(df, rule="L=50c")
    # A all-in 0.417 < 0.50; net >= 0.50 first at the 0.55 live bid: 0.55 - 0.018 = 0.532
    assert r["exit_ts"] == t(200) and r["exit_value"] == pytest.approx(5.50 - 0.18)
    assert not pick(df, rule="L=40c")["locked"]                          # bought above 40c: hold
    assert not pick(df, side="B", rule="L=60c")["locked"]                # B all-in 0.637 >= 0.60: hold
    assert len(RULES) == 12


def test_set_split_tags():
    df = positions(book(PATH, base=T0), matches("M1"))
    sets = pd.DataFrame({"match_id": ["M1"], "set_no": [1], "close_time": [t(200 + 150)]})
    out = tag_set_split(df, sets)
    lv = out[(out["mode"] == "E1") & (out["side"] == "A")].set_index("rule")["set_split"]
    assert lv["T=5c"] == "pre" and lv["L=50c"] == "set_end"             # live exit 150 s before set close
    far = tag_set_split(df, sets.assign(close_time=[t(200 + 400)]))
    assert far.loc[(far["mode"] == "E1") & (far["side"] == "A") & (far["rule"] == "L=50c"), "set_split"].iloc[0] \
        == "mid_set"
    none = tag_set_split(df, sets.assign(match_id=["OTHER"]))
    assert set(none.loc[none["exit_phase"] == "live", "set_split"]) == {"no_set_data"}
    assert set(tag_set_split(df, None).loc[lambda d: d["exit_phase"] == "live", "set_split"]) == {"no_set_data"}
    assert out.loc[~out["locked"], "set_split"].isna().all()


# A dog at 0.10 pre-match rises to a 0.55 bid in play; B wins.
DOG = [(0, 0.10, 0.08, 0.92, 0.90), (60, 0.30, 0.28, 0.72, 0.70), (200, 0.57, 0.55, 0.45, 0.43)]


def test_dog50_positions_and_summary():
    df = positions(book(DOG), matches("M1"))
    dog = dog_positions(df)
    assert list(dog["side"]) == ["A"] and list(dog["dog_band"]) == ["10-20c"] and list(dog["mode"]) == ["E1"]
    s = dog_summary(dog, ("mode",)).iloc[0]
    # entry 1.00 + fee 0.07 = 1.07; sold at 0.55: 5.50 - 0.18 = 5.32; hold = -1.07 (B wins)
    assert s["triggers"] == 1 and s["pnl_pc"] == pytest.approx((5.32 - 1.07) / 10)
    assert s["roi"] == pytest.approx((5.32 - 1.07) / 1.07) and s["delta_pc"] == pytest.approx(0.532)
    assert s["frac_stale_bid"] == 0.0                                     # B's ask moved at the exit row
    assert dog_positions(df, 0.30).equals(dog)                           # B at 0.92 is no dog either way


def test_dog50_fixed_rule_gate():
    qs, ms = [], []
    for k in range(5):
        for i in range(8):
            base = pd.Timestamp(f"2026-0{k + 1}-{i + 1:02d} 12:00", tz="UTC")
            qs.append(book(DOG, f"M{k}-{i}", base))
            ms.append(matches(f"M{k}-{i}", start=base + pd.Timedelta(seconds=100)))
    m, q = pd.concat(ms, ignore_index=True), pd.concat(qs, ignore_index=True)
    paths = cash_paths(align(q, m), m, CFG)
    by = {s: dog_positions(simulate_cashout(paths, CFG, s)) for s in (0.0, 0.01)}
    g = fixed_rule_gate(by, match_months(paths), wf_settings({}))
    assert g.passed, g.reasons
    assert list(g.gate["months"]) == [5, 5] and list(g.gate["triggers"]) == [40, 40]
    lose = {s: d.assign(rule_pnl=-1.0) for s, d in by.items()}
    bad = fixed_rule_gate(lose, match_months(paths), wf_settings({}))
    assert not bad.passed and any("0 of 5 months" in r for r in bad.reasons)
    few = fixed_rule_gate({s: d.iloc[:10] for s, d in by.items()}, match_months(paths), wf_settings({}))
    assert any("triggers; need >= 30" in r for r in few.reasons)


def test_exit_bid_age_from_the_other_sides_ask():
    # B's ask (the source of A's bid) is unchanged from t=60; A exits at t=130 on a 70 s old bid.
    stale = [(0, 0.40, 0.38, 0.62, 0.60), (60, 0.50, 0.48, 0.51, 0.49), (130, 0.51, 0.49, 0.51, 0.49)]
    df = positions(book(stale), matches("M1"))
    r = pick(df)
    assert r["exit_ts"] == t(130) and r["exit_bid_age_s"] == 70.0
    s = summarize(df)
    assert s.loc[(s["mode"] == "E1") & (s["rule"] == "T=5c"), "frac_stale_bid"].iloc[0] == 1.0
    fresh = pick(positions(book(PATH), matches("M1")))
    assert fresh["exit_bid_age_s"] == 0.0                                # B's ask moved at t=90


# ---- addendum 2: dog exit-level curve and DOGL -----------------------------------

def curve(q, m, slip=0.0, cap=0.20):
    return dog_positions(simulate_cashout(cash_paths(align(q, m), m, CFG), CFG, slip, rules=DOG_CURVE_RULES),
                         cap, rule=None)


def test_dog_exit_level_curve():
    c = curve(book(DOG), matches("M1")).set_index("rule")
    assert list(c.index) == [f"L={v}c" for v in (40, 45, 50, 55, 60, 65, 70, 80, 90)] + ["hold"]
    # entry 1.07 (0.107 all-in); bids 0.08, 0.28, 0.55: net 0.28 - 0.015 = 0.265, 0.55 - 0.018 = 0.532
    assert c.loc[["L=40c", "L=45c", "L=50c"], "locked"].all() and not c.loc[["L=55c", "hold"], "locked"].any()
    assert c.loc["L=50c", "rule_pnl"] == pytest.approx(5.32 - 1.07)
    assert c.loc["hold", "rule_pnl"] == pytest.approx(-1.07) and c.loc["hold", "pnl"] == 0     # B wins
    s = dog_summary(c.reset_index(), ("rule",)).set_index("rule")
    assert s.loc["hold", "trigger_rate"] == 0 and s.loc["hold", "sd_pc"] == 0
    assert s.loc["hold", "p10_pc"] == pytest.approx(-0.107)


def dog_months(n_per_month=12, n_months=5):
    qs, ms = [], []
    for k in range(n_months):
        for i in range(n_per_month):
            base = pd.Timestamp(f"2026-0{k + 1}-{i + 1:02d} 12:00", tz="UTC")
            qs.append(book(DOG, f"M{k}-{i}", base))
            ms.append(matches(f"M{k}-{i}", start=base + pd.Timedelta(seconds=100)))
    m, q = pd.concat(ms, ignore_index=True), pd.concat(qs, ignore_index=True)
    paths = cash_paths(align(q, m), m, CFG)
    by = {s: dog_positions(simulate_cashout(paths, CFG, s, rules=DOG_CURVE_RULES), 0.20, rule=None)
          for s in (0.0, 0.01)}
    return by, match_months(paths)


def test_dogl_walk_forward_picks_a_level_on_past_months():
    by, months = dog_months()
    g = dogl_walk_forward(by, months, wf_settings({}))
    assert g.passed, g.reasons
    # L=40c..50c all exit at the 0.55 bid and tie on P&L: the lowest level in the list wins the tie
    assert list(g.folds["rule"]) == ["L=40c"] * 4
    assert list(g.gate["positions"]) == [48, 48] and list(g.gate["triggers"]) == [48, 48]


def test_dogl_hold_is_always_eligible_and_counts_positions():
    by, months = dog_months()
    g = dogl_walk_forward(by, months, {**wf_settings({}), "min_train_trades": 99})
    assert list(g.folds["rule"]) == ["hold"] * 4 and list(g.gate["triggers"]) == [0, 0]
    assert not g.passed and any("0 of 4 folds positive" in r for r in g.reasons)   # B always wins


# ---- addendum 3: MISMATCH50 ---------------------------------------------------------

def ranks(rows):
    return pd.DataFrame(rows, columns=["match_id", "rank_a", "rank_b"])


def test_ranked_positions_keep_the_worse_ranked_side():
    pos = simulate_cashout(cash_paths(align(book(DOG), matches("M1")), matches("M1"), CFG), CFG, 0.0)
    r = ranked_positions(pos, ranks([("M1", 300, 20)]))
    assert set(r["side"]) == {"A"} and set(r["rule"]) == {"L=50c"} and len(r) == 2      # E1 + E2, A only
    assert (r["rank_ratio"] == 15).all() and (r["ratio_bucket"] == ">=8").all() and (r["better_rank"] == 20).all()
    assert set(ranked_positions(pos, ranks([("M1", 20, 50)]))["side"]) == {"B"}
    assert ranked_positions(pos, ranks([("M1", 40, 40)])).empty                          # tie: no worse side
    assert ranked_positions(pos, ranks([("OTHER", 300, 20)])).empty
    assert ranked_positions(pos, None).empty
    assert list(ranked_positions(pos, ranks([("M1", 60, 20)]))["ratio_bucket"]) == ["2-4", "2-4"]
    mm = mismatch_positions(ranked_positions(pos, ranks([("M1", 300, 20)])))
    assert len(mm) == 2
    assert mismatch_positions(ranked_positions(pos, ranks([("M1", 600, 150)]))).empty    # better ranked > 100
    assert mismatch_positions(ranked_positions(pos, ranks([("M1", 70, 20)]))).empty      # ratio 3.5 < 4


def test_target_bid_and_reach_vs_implied():
    # 10 lots: 0.51 nets 0.51 - 0.018 = 0.492 < 0.50; 0.52 nets 0.502
    assert target_bid(FM, 10) == 0.52
    pos = simulate_cashout(cash_paths(align(book(DOG), matches("M1")), matches("M1"), CFG), CFG, 0.0)
    mm = mismatch_positions(ranked_positions(pos, ranks([("M1", 300, 20)]))).assign(slippage=0.0)
    s = mismatch_summary(mm, ("mode",), FM).set_index("mode")
    # E1: A at 0.10 reaches the 0.55 bid -> reach 1; implied 0.10 / 0.52. E2: A at 0.57 is above 50c: not eligible
    assert s.loc["E1", "reach_rate"] == 1 and s.loc["E1", "implied_rate"] == pytest.approx(0.10 / 0.52)
    assert s.loc["E1", "frac_under_20c"] == 1 and s.loc["E1", "roi"] == pytest.approx((5.32 - 1.07) / 1.07)
    assert s.loc["E2", "reach_eligible"] == 0 and s.loc["E2", "frac_under_20c"] == 0


def test_cli_with_ranks(tmp_path):
    m, q = monthly(n_per_month=2)
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    m.to_parquet(data / "matches.parquet")
    q.to_parquet(data / "quotes.parquet")
    ranks([(mid, 300, 20) for mid in m["match_id"]]).to_parquet(tmp_path / "ranks.parquet")
    assert main(["--data", str(data), "--out", str(out), "--ranks", str(tmp_path / "ranks.parquet")]) == 0
    for f in ("cashout_mm50.csv", "cashout_mm50_tier.csv", "cashout_ratio_bucket.csv", "cashout_mm50_gate.csv"):
        assert (out / f).exists()
    assert "MISMATCH50" in (out / "cashout_summary.md").read_text() and "PROXY" in (out / "cashout_summary.md").read_text()
    assert main(["--data", str(data), "--out", str(tmp_path / "o2")]) == 0
    assert not (tmp_path / "o2" / "cashout_mm50.csv").exists()


# ---- addendum 4: MISMATCH50-U (unranked player vs a top-100 player) ---------------------

def test_unranked_positions_and_reasons():
    pos = simulate_cashout(cash_paths(align(book(DOG), matches("M1")), matches("M1"), CFG), CFG, 0.0)
    nan = np.nan
    rk = pd.DataFrame({"match_id": ["M1"], "rank_a": [nan], "rank_b": [20.0], "reason_a": ["few_matches"],
                       "reason_b": [None]})
    u = unranked_positions(pos, rk)
    assert set(u["side"]) == {"A"} and set(u["rule"]) == {"L=50c"} and len(u) == 2
    assert set(u["reason"]) == {"few_matches"} and (u["better_rank"] == 20).all()
    assert ranked_positions(pos, rk).empty                                # MISMATCH50 stays as registered
    assert unranked_positions(pos, rk.assign(rank_b=150.0)).empty         # better player outside the top 100
    assert unranked_positions(pos, rk.assign(rank_b=nan)).empty           # both unranked
    assert unranked_positions(pos, rk.assign(rank_a=500.0)).empty         # both ranked
    no_reason = unranked_positions(pos, rk[["match_id", "rank_a", "rank_b"]])
    assert set(no_reason["reason"]) == {"unknown"}
    flipped = rk.assign(rank_a=30.0, rank_b=nan, reason_b="inactive")
    assert set(unranked_positions(pos, flipped)["side"]) == {"B"}
    pd_ = price_distribution(u, ("reason",)).iloc[0]
    assert pd_["entries"] == 2 and pd_["ask_p50"] == pytest.approx((0.10 + 0.57) / 2)
    assert pd_["frac_under_20c"] == 0.5 and pd_["frac_over_50c"] == 0.5


def test_cli_unranked_section(tmp_path):
    m, q = monthly(n_per_month=2)
    data, out = tmp_path / "data", tmp_path / "out"
    data.mkdir()
    m.to_parquet(data / "matches.parquet")
    q.to_parquet(data / "quotes.parquet")
    pd.DataFrame({"match_id": m["match_id"], "rank_a": np.nan, "rank_b": 20.0, "reason_a": "unmatched",
                  "reason_b": None}).to_parquet(tmp_path / "ranks.parquet")
    assert main(["--data", str(data), "--out", str(out), "--ranks", str(tmp_path / "ranks.parquet")]) == 0
    for f in ("cashout_u50.csv", "cashout_u50_reason.csv", "cashout_u50_price.csv", "cashout_u50_gate.csv"):
        assert (out / f).exists()
    md = (out / "cashout_summary.md").read_text()
    assert "MISMATCH50-U" in md and "ASSUMPTION" in md
    assert pd.read_csv(out / "cashout_mm50.csv").empty                   # no fully ranked matches here
