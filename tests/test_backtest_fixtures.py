"""True-arb sanity check on real Kalshi fixtures (Faria vs Brunold order books, 2026-10-24).

Orderbooks return bids only (ascending; best = last). YES ask = 1 - best NO bid, NO ask =
1 - best YES bid, and ask(A) = min(YES ask on A, NO ask on B) (see CLAUDE.md Key facts).
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from swinglock.backtest.align import align
from swinglock.backtest.arb import scan_arb
from swinglock.config import kalshi_fees
from swinglock.locks import true_arb
from swinglock.schema import MATCH_COLUMNS, QUOTE_COLUMNS, conform

from test_backtest import CFG

FIX = Path(__file__).parent / "fixtures" / "kalshi"
TS = pd.Timestamp("2026-10-24 09:00", tz="UTC")


def book(leg: str) -> dict[str, tuple[float, float]]:
    """Best bid (price, size) per side for one market leg."""
    ob = json.loads((FIX / f"orderbook_atp_faria_brunold_{leg}_depth10_2026-10-24.json").read_text())["orderbook_fp"]
    return {s: tuple(map(float, ob[f"{s}_dollars"][-1])) for s in ("yes", "no")}


def asks(own: str, opp: str) -> tuple[float, float, str]:
    """(effective ask, size, source) for the player whose market is `own`."""
    yes = (round(1 - book(own)["no"][0], 4), book(own)["no"][1], "yes")
    no = (round(1 - book(opp)["yes"][0], 4), book(opp)["yes"][1], "no")
    return min(yes, no)


def series_fees():
    s = json.loads((FIX / "series_KXATPMATCH_2026-10-24.json").read_text())
    s = s.get("series", s)
    return s["fee_type"], float(s["fee_multiplier"])


def test_fixture_books_combined_prices():
    far, bru = book("FAR"), book("BRU")
    yes_yes = (1 - far["no"][0]) + (1 - bru["no"][0])
    no_no = (1 - far["yes"][0]) + (1 - bru["yes"][0])
    assert yes_yes == pytest.approx(1.02) and no_no == pytest.approx(1.00)
    a, b = asks("FAR", "BRU"), asks("BRU", "FAR")
    assert a == (0.53, 1538.02, "no") and b == (0.47, 664.85, "no")   # both legs come from NO asks


def test_fixture_no_arb_after_fees():
    ft, mult = series_fees()
    assert (ft, mult) == ("quadratic_with_maker_fees", 1.0)
    fees = kalshi_fees(CFG, ft, mult)
    (aa, sa, _), (ab, sb, _) = asks("FAR", "BRU"), asks("BRU", "FAR")

    r = true_arb(aa, ab, fees, sa, sb, max_contracts=100)
    assert r.combined == pytest.approx(1.00) and r.contracts == 100
    assert r.profit == pytest.approx(-(1.75 + 1.75))          # fee(0.53, 100) = fee(0.47, 100) = 1.7437 -> 1.75
    assert not r.is_arb
    assert true_arb(aa, ab, fees).profit == pytest.approx(-0.04)  # 1 contract: each fee rounds up to 2c

    q = conform(pd.DataFrame([dict(ts=TS, match_id="FAR-BRU", side="A", ask=aa, ask_size=sa, source="orderbook"),
                              dict(ts=TS, match_id="FAR-BRU", side="B", ask=ab, ask_size=sb, source="orderbook")]),
                QUOTE_COLUMNS)
    m = conform(pd.DataFrame([dict(match_id="FAR-BRU", fee_type=ft, fee_multiplier=mult)]), MATCH_COLUMNS)
    eps, summ = scan_arb(align(q, m), m, CFG)
    assert eps.empty
    assert summ.iloc[0]["n_obs"] == 1 and summ.iloc[0]["n_arb"] == 0
    assert summ.iloc[0]["min_combined"] == pytest.approx(1.00)
