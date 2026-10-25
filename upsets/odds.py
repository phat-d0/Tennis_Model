"""Decimal odds -> probabilities, with the bookmaker margin removed."""

from __future__ import annotations

import numpy as np


def overround(odds_a, odds_b):
    """Sum of implied probabilities minus 1 (the book's margin)."""
    return 1.0 / np.asarray(odds_a, float) + 1.0 / np.asarray(odds_b, float) - 1.0


def devig_proportional(odds_a, odds_b):
    """Implied probability of A with the margin spread in proportion to each side."""
    ia, ib = 1.0 / np.asarray(odds_a, float), 1.0 / np.asarray(odds_b, float)
    return ia / (ia + ib)


def devig_power(odds_a, odds_b, iters: int = 60):
    """Implied probability of A from the power method: find k with ia**k + ib**k = 1.

    Puts more of the margin on the longshot than proportional does, matching the
    favourite-longshot bias seen in tennis odds.
    """
    ia, ib = 1.0 / np.asarray(odds_a, float), 1.0 / np.asarray(odds_b, float)
    lo, hi = np.full(ia.shape, 0.2), np.full(ia.shape, 5.0)  # k < 1 if the pair sums under 1
    for _ in range(iters):
        k = (lo + hi) / 2
        too_big = ia ** k + ib ** k > 1.0
        lo = np.where(too_big, k, lo)
        hi = np.where(too_big, hi, k)
    return ia ** ((lo + hi) / 2)
