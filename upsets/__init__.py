"""Early-round upset research: can a model beat bookmaker odds on underdogs (ATP + WTA)?

Pipeline: load (tennis-data.co.uk results + closing odds) -> elo (pre-match ratings) ->
features (favourite/underdog framing, de-vigged market prob) -> model (logistic) ->
backtest (season walk-forward, bets at a real book's price) -> run (report).
DraftKings odds come only through The Odds API (odds_api.py). Research only: no bet placement.
"""
