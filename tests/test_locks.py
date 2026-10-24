import pytest

from swinglock.fees import ZERO_FEES, FeeModel, kalshi_fee_model
from swinglock.locks import Holding, lock_quote, max_lock_price, true_arb

KALSHI = FeeModel(taker_rate=0.07, rounding_increment=0.01)


# ---- fees ----------------------------------------------------------------

def test_fee_peaks_at_50c():
    assert KALSHI.fee(0.50, 100) == pytest.approx(1.75)
    assert KALSHI.fee(0.50, 1) == pytest.approx(0.02)          # 0.0175 rounds up to 2c
    assert KALSHI.fee(0.10, 100) == pytest.approx(0.63)


def test_fee_rounding_no_float_noise():
    # 0.07 * 10 * 0.5 * 0.5 = 0.175 -> 0.18; exact-cent results must not bump up
    assert KALSHI.fee(0.50, 10) == pytest.approx(0.18)
    assert FeeModel(0.07, rounding_increment=0.01).fee(0.5, 400 / 7) == pytest.approx(1.0)


def test_series_fee_types():
    assert kalshi_fee_model("quadratic").maker_rate == 0.0
    assert kalshi_fee_model("quadratic_with_maker_fees").maker_rate == 0.0175
    assert kalshi_fee_model("quadratic", 0.5).fee(0.5, 100) == pytest.approx(0.88)
    with pytest.raises(ValueError):
        kalshi_fee_model("flat")


# ---- worked example from the project brief --------------------------------
# Krueger 11.44 @ 42.7c ($4.88), Li 27.62 @ 54.3c ($15.00). Prices treated as
# all-in (fees already inside the avg price), so the lock uses zero extra fees.

def _example():
    return Holding.from_avg(contracts_a=11.44, avg_a=0.427, contracts_b=27.62, avg_b=0.543)


def test_worked_example_unmatched_pnl():
    h = _example()
    assert h.cost_a == pytest.approx(4.88, abs=0.01)
    assert h.cost_b == pytest.approx(15.00, abs=0.01)
    assert h.pnl_if("B") == pytest.approx(7.74, abs=0.01)    # Li wins
    assert h.pnl_if("A") == pytest.approx(-8.44, abs=0.01)   # Krueger wins


def test_worked_example_lock():
    q = lock_quote(_example(), ask_a=0.427, ask_b=0.60, fees=ZERO_FEES)
    assert q.side_to_buy == "A"
    assert q.contracts_to_buy == pytest.approx(27.62 - 11.44)
    # Brief: matching 27.62 Krueger in total locks ~ +$0.84 (27.62 * 3c = 0.83 before rounding)
    assert q.locked_pnl == pytest.approx(0.83, abs=0.015)
    assert q.is_profitable


def test_lock_with_fees_can_flip_to_loss():
    q = lock_quote(_example(), ask_a=0.427, ask_b=0.60, fees=KALSHI)
    # fee on 16.18 @ 42.7c = 0.07*16.18*.427*.573 = 0.277 -> 0.28
    assert q.cost == pytest.approx(16.18 * 0.427 + 0.28, abs=1e-6)
    assert q.locked_pnl == pytest.approx(0.83 - 0.28, abs=0.015)


def test_balanced_holding_needs_no_lock():
    assert lock_quote(Holding.from_avg(5, 0.4, 5, 0.5), 0.4, 0.5, KALSHI) is None


def test_depth_flag():
    q = lock_quote(_example(), 0.427, 0.6, ZERO_FEES, depth_a=10)
    assert not q.depth_ok


# ---- true arb -------------------------------------------------------------

def test_true_arb_after_fees():
    r = true_arb(0.45, 0.50, KALSHI, depth_a=50, depth_b=30)
    assert r.contracts == 30
    fee_a = KALSHI.fee(0.45, 30)
    fee_b = KALSHI.fee(0.50, 30)
    assert r.profit == pytest.approx(30 * 0.05 - fee_a - fee_b)
    assert r.is_arb


def test_combined_below_1_but_fees_kill_it():
    r = true_arb(0.49, 0.50, KALSHI, depth_a=10, depth_b=10)
    assert r.combined < 1
    assert not r.is_arb


def test_slippage_reduces_profit():
    a = true_arb(0.45, 0.50, KALSHI, 10, 10)
    b = true_arb(0.45, 0.50, KALSHI, 10, 10, slippage=0.01)
    assert b.profit < a.profit


def test_max_lock_price():
    p = max_lock_price(0.427, KALSHI)
    edge = 1 - 0.427 - p - KALSHI.per_contract(p)
    assert edge == pytest.approx(0.0, abs=1e-6)
    assert 0.55 < p < 0.573
    assert max_lock_price(1.0, KALSHI) == 0.0
