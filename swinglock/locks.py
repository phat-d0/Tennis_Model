"""Core arbitrage / swing-lock math for a two-outcome market.

Conventions
- Prices are in dollars (0.427 == 42.7c). Contract counts may be fractional.
- Side "A" and side "B" are the two mutually exclusive outcomes; exactly one
  pays $1 per contract.
- Costs include fees. Buys happen at the ask (plus slippage), never mid/last.
- Sizing rule: a lock buys enough contracts on the short side to make the
  contract counts equal; locked P&L = matched contracts - total cost.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fees import FeeModel

SIDES = ("A", "B")


def other(side: str) -> str:
    if side not in SIDES:
        raise ValueError(f"side must be 'A' or 'B', got {side!r}")
    return "B" if side == "A" else "A"


def buy_cost(price: float, contracts: float, fees: FeeModel, slippage: float = 0.0) -> float:
    """Dollar cost of buying `contracts` at `price` + slippage, including fees."""
    fill = min(price + slippage, 1.0)
    return contracts * fill + fees.fee(fill, contracts)


# --------------------------------------------------------------------------
# True arbitrage: buy both sides at the same moment
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ArbResult:
    ask_a: float
    ask_b: float
    contracts: float          # matched contracts actually buyable (min depth, capped)
    cost: float               # total dollars incl. fees
    profit: float             # guaranteed profit in dollars
    edge_per_contract: float  # profit / contracts

    @property
    def combined(self) -> float:
        return self.ask_a + self.ask_b

    @property
    def is_arb(self) -> bool:
        return self.contracts > 0 and self.profit > 0


def true_arb(
    ask_a: float,
    ask_b: float,
    fees: FeeModel,
    depth_a: float | None = None,
    depth_b: float | None = None,
    max_contracts: float | None = None,
    slippage: float = 0.0,
) -> ArbResult:
    """Profit from buying N contracts of both A and B at their current asks.

    N = min(depth_a, depth_b, max_contracts). With no depth info, N = 1 (a per-contract check).
    """
    limits = [x for x in (depth_a, depth_b, max_contracts) if x is not None]
    n = min(limits) if limits else 1.0
    n = max(n, 0.0)
    cost = buy_cost(ask_a, n, fees, slippage) + buy_cost(ask_b, n, fees, slippage)
    profit = n - cost
    return ArbResult(ask_a, ask_b, n, cost, profit, profit / n if n else 0.0)


# --------------------------------------------------------------------------
# Positions and swing locks
# --------------------------------------------------------------------------

@dataclass
class Holding:
    """Contracts held on each side and the dollars paid for them (fees included)."""
    contracts_a: float = 0.0
    cost_a: float = 0.0
    contracts_b: float = 0.0
    cost_b: float = 0.0

    @classmethod
    def from_avg(cls, contracts_a=0.0, avg_a=0.0, contracts_b=0.0, avg_b=0.0) -> "Holding":
        """Build from average prices that already include fees (as a broker statement shows)."""
        return cls(contracts_a, contracts_a * avg_a, contracts_b, contracts_b * avg_b)

    @property
    def total_cost(self) -> float:
        return self.cost_a + self.cost_b

    def contracts(self, side: str) -> float:
        return self.contracts_a if side == "A" else self.contracts_b

    def pnl_if(self, winner: str) -> float:
        """Settlement P&L if `winner` wins."""
        return self.contracts(winner) - self.total_cost

    def pnl_settled(self, pay_a: float, pay_b: float) -> float:
        """Settlement P&L when each side pays `pay_a` / `pay_b` per contract (1/0 for a normal
        result; Kalshi's fair prices for a match that never started, which sum to $1)."""
        return self.contracts_a * pay_a + self.contracts_b * pay_b - self.total_cost

    @property
    def locked_pnl(self) -> float:
        """Worst-case settlement P&L (positive => already locked)."""
        return min(self.pnl_if("A"), self.pnl_if("B"))

    @property
    def short_side(self) -> str | None:
        """Side with fewer contracts (the one a lock must buy), or None if balanced."""
        if abs(self.contracts_a - self.contracts_b) < 1e-9:
            return None
        return "A" if self.contracts_a < self.contracts_b else "B"

    def add(self, side: str, contracts: float, cost: float) -> "Holding":
        if side == "A":
            return Holding(self.contracts_a + contracts, self.cost_a + cost, self.contracts_b, self.cost_b)
        return Holding(self.contracts_a, self.cost_a, self.contracts_b + contracts, self.cost_b + cost)


@dataclass(frozen=True)
class LockQuote:
    side_to_buy: str
    contracts_to_buy: float
    ask: float
    cost: float               # dollars to spend now, incl. fees and slippage
    locked_pnl: float         # guaranteed P&L after the lock
    pnl_if_a: float           # unmatched (current) P&L if A wins
    pnl_if_b: float           # unmatched (current) P&L if B wins
    depth_ok: bool            # enough contracts resting at that ask

    @property
    def is_profitable(self) -> bool:
        return self.locked_pnl > 0


def lock_quote(
    holding: Holding,
    ask_a: float,
    ask_b: float,
    fees: FeeModel,
    depth_a: float | None = None,
    depth_b: float | None = None,
    slippage: float = 0.0,
) -> LockQuote | None:
    """What it costs to equalize contract counts by buying the short side now.

    Returns None when the holding is already balanced (nothing to buy).
    """
    side = holding.short_side
    if side is None:
        return None
    need = abs(holding.contracts_a - holding.contracts_b)
    ask = ask_a if side == "A" else ask_b
    depth = depth_a if side == "A" else depth_b
    cost = buy_cost(ask, need, fees, slippage)
    after = holding.add(side, need, cost)
    return LockQuote(
        side_to_buy=side,
        contracts_to_buy=need,
        ask=ask,
        cost=cost,
        locked_pnl=after.locked_pnl,
        pnl_if_a=holding.pnl_if("A"),
        pnl_if_b=holding.pnl_if("B"),
        depth_ok=depth is None or depth >= need - 1e-9,
    )


def max_lock_price(entry_price: float, fees: FeeModel, min_profit_per_contract: float = 0.0) -> float:
    """Highest ask for the other side at which a 1:1 lock against `entry_price` still clears
    `min_profit_per_contract`, using the unrounded per-contract fee. `entry_price` should
    already include its own entry fee. Returns 0.0 when no price works."""
    lo, hi = 0.0, 1.0
    if 1.0 - entry_price - min_profit_per_contract <= 0:
        return 0.0
    for _ in range(60):
        mid = (lo + hi) / 2
        edge = 1.0 - entry_price - mid - fees.per_contract(mid)
        if edge >= min_profit_per_contract:
            lo = mid
        else:
            hi = mid
    return lo
