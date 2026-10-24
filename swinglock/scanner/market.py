"""Match discovery and effective quotes for Kalshi tennis match events.

A match event has one market per player (YES on `...-FAR` = Faria wins). Holding side A can
be bought two ways: YES on A's market or NO on B's market, so

    ask(A) = min(YES ask on A, NO ask on B)      bid(A) = max(YES bid on A, NO bid on B)

The orderbook returns bids only, ascending (best = last): YES ask = 1 − best NO bid with the
size of that NO bid, NO ask = 1 − best YES bid. See docs/research/kalshi_api.md §7.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

TIERS = {
    "KXATPMATCH": "atp",
    "KXWTAMATCH": "wta",
    "KXATPCHALLENGERMATCH": "challenger",
    "KXWTACHALLENGERMATCH": "challenger",
    "KXITFMATCH": "itf",
    "KXITFWMATCH": "itf",
}


@dataclass(frozen=True)
class MatchPair:
    match_id: str             # event ticker
    series: str
    tier: str
    tournament: str
    player_a: str
    player_b: str
    ticker_a: str             # market whose YES = A wins
    ticker_b: str
    scheduled_start: datetime | None = None

    def phase(self, now: datetime) -> str:
        if self.scheduled_start is None:
            return "unknown"
        return "pre" if now < self.scheduled_start else "live"


@dataclass(frozen=True)
class SideQuote:
    ask: float | None
    ask_size: float | None
    ask_source: str | None    # "yes:<ticker>" or "no:<ticker>"
    bid: float | None
    bid_size: float | None


@dataclass(frozen=True)
class MatchQuote:
    a: SideQuote
    b: SideQuote


def parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def pairs_from_events(events: list[dict], milestones: list[dict] | None = None) -> list[MatchPair]:
    """Two-market, mutually exclusive, active events → A/B pairs (A = first ticker, sorted)."""
    starts: dict[str, datetime] = {}
    for m in milestones or []:
        start = parse_ts(m.get("start_date"))
        if start is None:
            continue
        for t in m.get("primary_event_tickers") or []:
            starts.setdefault(t, start)
    out = []
    for ev in events:
        markets = sorted((m for m in ev.get("markets") or [] if m.get("status", "active") == "active"),
                         key=lambda m: m["ticker"])
        if len(markets) != 2 or not ev.get("mutually_exclusive", False):
            continue
        a, b = markets
        series = ev.get("series_ticker", "")
        out.append(MatchPair(
            match_id=ev["event_ticker"],
            series=series,
            tier=TIERS.get(series, "other"),
            tournament=(ev.get("product_metadata") or {}).get("competition", ""),
            player_a=a.get("yes_sub_title") or a["ticker"],
            player_b=b.get("yes_sub_title") or b["ticker"],
            ticker_a=a["ticker"],
            ticker_b=b["ticker"],
            scheduled_start=starts.get(ev["event_ticker"]),
        ))
    return out


def _levels(book: dict, key: str) -> list[tuple[float, float]]:
    """Bid levels best-first as (price, size) floats."""
    return [(float(p), float(s)) for p, s in reversed(book.get(key) or []) if float(s) > 0]


def _best(levels: list[tuple[float, float]]) -> tuple[float, float] | None:
    return levels[0] if levels else None


def side_quote(own_book: dict, other_book: dict, own_ticker: str, other_ticker: str) -> SideQuote:
    """Effective quote for "this player wins": YES on own market or NO on the other market."""
    yes_bid = _best(_levels(own_book, "yes_dollars"))
    no_bid_own = _best(_levels(own_book, "no_dollars"))       # -> YES ask on own market
    yes_bid_other = _best(_levels(other_book, "yes_dollars"))  # -> NO ask on other market
    no_bid_other = _best(_levels(other_book, "no_dollars"))

    asks = []
    if no_bid_own:
        asks.append((round(1 - no_bid_own[0], 4), -no_bid_own[1], f"yes:{own_ticker}"))
    if yes_bid_other:
        asks.append((round(1 - yes_bid_other[0], 4), -yes_bid_other[1], f"no:{other_ticker}"))
    ask, neg_size, source = min(asks) if asks else (None, None, None)   # tie -> deeper leg

    bids = [x for x in (yes_bid, no_bid_other) if x]
    bid = max(bids) if bids else None
    return SideQuote(ask, -neg_size if neg_size is not None else None, source,
                     bid[0] if bid else None, bid[1] if bid else None)


def match_quote(pair: MatchPair, books: dict[str, dict]) -> MatchQuote | None:
    """None when either leg's book is missing from the snapshot."""
    if pair.ticker_a not in books or pair.ticker_b not in books:
        return None
    ba, bb = books[pair.ticker_a], books[pair.ticker_b]
    return MatchQuote(side_quote(ba, bb, pair.ticker_a, pair.ticker_b),
                      side_quote(bb, ba, pair.ticker_b, pair.ticker_a))
