"""Player-name matching shared by the upsets studies and the public odds page (no venue data here).

- norm_name: accent/punctuation-insensitive, word order kept, ALIASES applied.
- name_key: norm_name with its words sorted, for equality joins across sources whose name order
  differs (Odds API "Bu Yunchaokete" vs Kalshi "Yunchaokete Bu").
- match_names: names -> Sackmann player ids per tour: exact, then word order, then surname + first
  initial, then a close spelling, each only when unique.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

import pandas as pd

# Same player, different spellings across Sackmann / Kalshi / The Odds API. Keys and values are
# norm_name() forms; keys are token-sorted so either name order hits; values are the Sackmann spelling.
ALIASES = {
    "camila maria osorio serrano": "camila osorio",
    "abdelaziz ahmed mayar sherif": "mayar sherif",
}


def _sorted_key(key: str) -> str:
    return " ".join(sorted(key.split()))


def norm_name(name) -> str:
    """'Félix Auger-Aliassime' -> 'felix auger aliassime' (word order kept; aliases applied)."""
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", s)).strip()
    return ALIASES.get(_sorted_key(s), s)


def name_key(name) -> str:
    """Order-insensitive key for equality joins: 'Bu Yunchaokete' and 'Yunchaokete Bu' ->
    'bu yunchaokete'; 'Liang En-shuo' and 'En-Shuo Liang' -> 'en liang shuo'."""
    return _sorted_key(norm_name(name))


def _initial_keys(key: str) -> set[str]:
    """Every 'surname initial' reading of a full name ('alex de minaur' -> {'de minaur a',
    'minaur a'})."""
    p = key.split()
    return {f"{' '.join(p[k:])} {p[0][0]}" for k in range(1, len(p))} if len(p) > 1 else {key}


def player_table(sack: pd.DataFrame) -> pd.DataFrame:
    """tour, id, name, key, last (date of the player's last match)."""
    long = pd.concat([
        sack[["tour", "winner_id", "winner", "date"]].set_axis(["tour", "id", "name", "date"], axis=1),
        sack[["tour", "loser_id", "loser", "date"]].set_axis(["tour", "id", "name", "date"], axis=1)])
    t = long.sort_values("date").groupby(["tour", "id"], as_index=False).agg(
        name=("name", "last"), last=("date", "max"))
    t["key"] = t["name"].map(norm_name)
    return t


def _index(pool: pd.DataFrame) -> dict:
    """Lookup tables for one tour's player pool: key/word-order/initial -> set of ids."""
    idx = {"exact": {}, "order": {}, "initial": {}, "keys": {}}
    for pid, key in zip(pool["id"], pool["key"]):
        idx["exact"].setdefault(key, set()).add(pid)
        idx["order"].setdefault(_sorted_key(key), set()).add(pid)
        for k in _initial_keys(key):
            idx["initial"].setdefault(k, set()).add(pid)
        idx["keys"].setdefault(key, set()).add(pid)
    idx["key_list"] = list(idx["keys"])
    return idx


def _lookup(key: str, idx: dict):
    """-> (id or None, how, ambiguous?) within one pool."""
    for how, wants in (("exact", [key]), ("order", [_sorted_key(key)]),
                       ("initial", sorted(_initial_keys(key)))):
        ids = set().union(*(idx[how].get(w, set()) for w in wants))
        if len(ids) == 1:
            return next(iter(ids)), how, False
        if len(ids) > 1:
            return None, "ambiguous", True
    close = difflib.get_close_matches(key, idx["key_list"], n=2, cutoff=0.88)
    if close:
        r0 = difflib.SequenceMatcher(None, key, close[0]).ratio()
        r1 = difflib.SequenceMatcher(None, key, close[1]).ratio() if len(close) > 1 else 0.0
        ids = idx["keys"][close[0]]
        if len(ids) == 1 and r0 - r1 >= 0.03:
            return next(iter(ids)), "fuzzy", False
        return None, "ambiguous", True
    return None, "none", False


def match_names(names: pd.Series, tours: pd.Series, players: pd.DataFrame,
                active_since: pd.Timestamp | None = None) -> pd.DataFrame:
    """Kalshi names -> Sackmann ids. Returns id (NA if none or ambiguous) and how
    (exact | order | initial | fuzzy | ambiguous | none). Players active since `active_since`
    are tried first; everyone else only when the active pool has no candidate at all."""
    pools: dict = {}

    def pools_for(tour):
        if tour not in pools:
            p = players[players["tour"] == tour]
            ps = [_index(p[p["last"] >= active_since])] if active_since is not None else []
            pools[tour] = ps + [_index(p)]
        return pools[tour]

    cache: dict = {}
    out = []
    for name, tour in zip(names, tours):
        k = (norm_name(name), tour)
        if k not in cache:
            res = (pd.NA, "none")
            if k[0]:
                for idx in pools_for(tour):
                    pid, how, amb = _lookup(k[0], idx)
                    if pid is not None or amb:
                        res = (pid if pid is not None else pd.NA, how)
                        break
            cache[k] = res
        out.append(cache[k])
    return pd.DataFrame(out, columns=["id", "how"], index=names.index)
