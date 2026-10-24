"""Venue-agnostic data contract between collectors, backtest and scanner.

Collectors (swinglock/collectors/*) turn raw venue responses into two tables,
stored as parquet under data/processed/<venue>/:

matches.parquet  - one row per match (a two-outcome market pair)
quotes.parquet   - one row per (timestamp, match, side) top-of-book observation

Side "A"/"B" is fixed per match in matches (player_a/player_b). For Kalshi, where a
match event has one market per player, the best way to *buy* side A is the cheaper
of YES on A's market and NO on B's market; collectors must resolve that and store
the effective best ask for the side, plus which instrument it came from.
"""

from __future__ import annotations

import pandas as pd

MATCH_COLUMNS = {
    "match_id": "string",          # venue event id, e.g. Kalshi event_ticker
    "venue": "string",             # "kalshi" | "polymarket" | "draftkings"
    "series": "string",            # e.g. KXATPMATCH
    "tier": "string",              # "atp" | "wta" | "challenger" | "itf" | "other"
    "tournament": "string",        # best-effort name, may be empty
    "player_a": "string",
    "player_b": "string",
    "instrument_a": "string",      # market ticker / token id that pays on A
    "instrument_b": "string",
    "scheduled_start": "datetime64[ns, UTC]",  # match start if known (pre vs live split)
    "open_time": "datetime64[ns, UTC]",
    "close_time": "datetime64[ns, UTC]",
    "winner": "string",            # "A" | "B" | <NA> if unsettled/void
    "fee_type": "string",
    "fee_multiplier": "float64",
}

QUOTE_COLUMNS = {
    "ts": "datetime64[ns, UTC]",
    "match_id": "string",
    "venue": "string",
    "side": "string",              # "A" | "B"
    "ask": "float64",              # dollars; best price to BUY this side (NaN if none)
    "ask_size": "float64",         # contracts at that ask (NaN if unknown, e.g. candles)
    "bid": "float64",              # dollars; best price to SELL this side
    "bid_size": "float64",
    "ask_source": "string",        # e.g. "yes:<ticker>" or "no:<ticker>"
    "source": "string",            # "orderbook" | "candle" | "ticker" | "manual"
}


def empty(columns: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype=t) for c, t in columns.items()})


def conform(df: pd.DataFrame, columns: dict[str, str]) -> pd.DataFrame:
    """Add missing columns, drop extras, coerce dtypes. Raises on unparseable values."""
    out = df.copy()
    for c, t in columns.items():
        if c not in out:
            out[c] = pd.Series(dtype=t, index=out.index)
        if t.startswith("datetime64"):
            out[c] = pd.to_datetime(out[c], utc=True)
        else:
            out[c] = out[c].astype(t)
    return out[list(columns)]


def validate_quotes(df: pd.DataFrame) -> None:
    bad_side = ~df["side"].isin(["A", "B"])
    if bad_side.any():
        raise ValueError(f"quotes.side must be A/B; got {df.loc[bad_side, 'side'].unique()[:5]}")
    for col in ("ask", "bid"):
        v = df[col].dropna()
        if ((v < 0) | (v > 1)).any():
            raise ValueError(f"quotes.{col} must be dollars in [0, 1]")
