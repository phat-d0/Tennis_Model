"""Exchange fee models.

Kalshi's published general formula (see docs/research/kalshi_api.md for the
verified version and sources):

    fee = round_up(M * rate * C * P * (1 - P))

    P    = contract price in dollars (0.43 for 43c)
    C    = number of contracts in the fill/order
    rate = 0.07 for taker fills, 0.0175 for maker fills on series that charge makers
    M    = per-series multiplier (default 1)

Rounding is up to `rounding_increment` ($0.01 for normal retail accounts).
All values here come from config so they can be corrected without code changes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Guards against float noise turning 0.0700000000001 into an extra cent.
_EPS = 1e-9


def round_up(value: float, increment: float) -> float:
    if increment <= 0:
        return value
    return math.ceil(value / increment - _EPS) * increment


@dataclass(frozen=True)
class FeeModel:
    taker_rate: float = 0.07
    maker_rate: float = 0.0
    multiplier: float = 1.0
    rounding_increment: float = 0.01

    def fee(self, price: float, contracts: float, maker: bool = False) -> float:
        """Fee in dollars for one order of `contracts` at `price` (dollars)."""
        if contracts <= 0:
            return 0.0
        if not 0.0 <= price <= 1.0:
            raise ValueError(f"price must be in dollars between 0 and 1, got {price}")
        rate = self.maker_rate if maker else self.taker_rate
        raw = self.multiplier * rate * contracts * price * (1.0 - price)
        return round(round_up(raw, self.rounding_increment), 10)

    def per_contract(self, price: float, maker: bool = False) -> float:
        """Unrounded marginal fee per contract; useful for quick screening."""
        rate = self.maker_rate if maker else self.taker_rate
        return self.multiplier * rate * price * (1.0 - price)


ZERO_FEES = FeeModel(taker_rate=0.0, maker_rate=0.0)


def kalshi_fee_model(
    fee_type: str,
    fee_multiplier: float = 1.0,
    taker_rate: float = 0.07,
    maker_rate: float = 0.0175,
    rounding_increment: float = 0.01,
) -> FeeModel:
    """Fee model for a Kalshi series from its `fee_type` / `fee_multiplier` fields.

    Observed fee_type values (GET /series, Oct 2026): "quadratic" (taker only) and
    "quadratic_with_maker_fees" (taker + maker). Unknown types raise so a fee
    change can't go unnoticed.
    """
    if fee_type == "quadratic":
        return FeeModel(taker_rate, 0.0, fee_multiplier, rounding_increment)
    if fee_type == "quadratic_with_maker_fees":
        return FeeModel(taker_rate, maker_rate, fee_multiplier, rounding_increment)
    raise ValueError(f"unknown Kalshi fee_type {fee_type!r}; update swinglock/fees.py")
