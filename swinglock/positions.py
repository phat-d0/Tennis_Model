"""Read the user's manually entered holdings (JSON or CSV).

Each row: market (an id for the match: a Kalshi event ticker), side ("A"/"B" or a
market ticker / player name the scanner maps to a side), contracts, avg_price
(dollars, fees included if you know them).

JSON example (positions.json):
[
  {"market": "KXATPMATCH-26OCT24KRULI", "side": "KXATPMATCH-26OCT24KRULI-KRU", "contracts": 11.44, "avg_price": 0.427},
  {"market": "KXATPMATCH-26OCT24KRULI", "side": "KXATPMATCH-26OCT24KRULI-LI",  "contracts": 27.62, "avg_price": 0.543}
]
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PositionRow:
    market: str
    side: str
    contracts: float
    avg_price: float


def load_positions(path: str | Path) -> list[PositionRow]:
    path = Path(path)
    if not path.exists():
        return []
    if path.suffix.lower() == ".csv":
        with open(path, newline="") as f:
            rows = list(csv.DictReader(f))
    else:
        rows = json.loads(path.read_text() or "[]")
    out = []
    for r in rows:
        p = PositionRow(str(r["market"]).strip(), str(r["side"]).strip(), float(r["contracts"]), float(r["avg_price"]))
        if p.contracts < 0 or not 0 <= p.avg_price <= 1:
            raise ValueError(f"bad position row {r}: contracts must be >= 0 and avg_price in dollars (0-1)")
        out.append(p)
    return out
