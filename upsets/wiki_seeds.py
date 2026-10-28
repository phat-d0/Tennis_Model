"""Seeds (and qualifiers) for live events from Wikipedia's draw articles, for the Portfolio's
"Seed loses early" strategy (reports/upsets_seed_portfolio.md). Wikipedia text is CC BY-SA; the page credits it.

One MediaWiki API call per title tried (`action=parse&prop=wikitext`, with a descriptive User-Agent),
at most two titles per event and build, and a parsed event is cached for good (seeds don't change).

Parsing is strict, so a wrong seed list is never used:
- seeds: the numbered list (`# ... [[Player]] ...`) under the "Seeds" heading. The list must hold
  4, 8, 16 or 32 players, each with one player link.
- qualifiers: the draw templates' `|RD1-seedNN=Q` (or LL) entries, paired with `|RD1-teamNN=` on the
  same slot.
Anything else (no article, no Seeds section, an odd count) returns None: the event is skipped and logged,
never guessed. The article titles below follow Wikipedia's usual naming; a title that turns out wrong
also just means "skipped".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .names import name_key

API = "https://en.wikipedia.org/w/api.php"
HEADERS = {"User-Agent": "tennis-odds-page/1.0 (https://github.com/phat-d0/Tennis_Model; research, read-only)"}
SEED_COUNTS = {4, 8, 16, 32}
MAX_TITLES = 2

# Odds API key suffix -> Wikipedia event name. Titles tried: "{year} {name} – Men's singles" (or Women's), then
# "{year} {name} – Singles" for single-gender events. Only keys The Odds API scores matter (portfolio.SCORED_KEYS).
EVENTS = {
    "us_open": "US Open", "canadian_open": "Canadian Open", "cincinnati_open": "Cincinnati Open",
    "china_open": "China Open", "japan_open": "Japan Open", "shanghai_masters": "Shanghai Masters",
    "washington_open": "Washington Open", "wuhan_open": "Wuhan Open", "guadalajara_open": "Guadalajara Open",
    "monterrey_open": "Monterrey Open", "singapore_open": "Singapore Tennis Open",
}


def titles(sport_key: str, year: int) -> list[str]:
    m = re.match(r"tennis_(atp|wta)_(.+)$", sport_key)
    if not m or m.group(2) not in EVENTS:
        return []
    name, gender = EVENTS[m.group(2)], "Men's" if m.group(1) == "atp" else "Women's"
    return [f"{year} {name} – {gender} singles", f"{year} {name} – Singles"][:MAX_TITLES]


def _link_name(text: str) -> str | None:
    for target in re.findall(r"\[\[([^\]]+)\]\]", text):
        if re.match(r"(?i)(file|image|category):", target):
            continue
        shown = target.split("|", 1)[-1]
        return re.sub(r"\s*\((tennis|tennis player)\)$", "", shown).strip()
    return None


def parse(wikitext: str) -> dict | None:
    """{"seeds": {name_key: seed}, "qualifiers": [name_key, ...]} or None if the seed list isn't clean."""
    if not isinstance(wikitext, str):
        return None
    sec = re.search(r"(?ims)^(=+)\s*seeds\s*\1\s*$(.*?)(?=^=+[^=\n]+=+\s*$|\Z)", wikitext)
    if not sec:
        return None
    seeds = {}
    for n, line in enumerate(re.findall(r"(?m)^#(?![#*:])\s*(.*)$", sec.group(2)), start=1):
        name = _link_name(line)
        if not name:
            return None
        seeds[name_key(name)] = n
    if len(seeds) not in SEED_COUNTS:
        return None
    teams = dict(re.findall(r"\|\s*RD1-team(\d+)\s*=\s*(.*)", wikitext))   # the first link after "=" is the player
    quals = []
    for slot, kind in re.findall(r"\|\s*RD1-seed(\d+)\s*=\s*(Q|LL)\b", wikitext):
        name = _link_name(teams.get(slot, ""))
        if name:
            quals.append(name_key(name))
    return {"seeds": seeds, "qualifiers": sorted(set(quals))}


def fetch(session, title: str) -> str | None:
    """The article's wikitext, or None when there is no such article. Other errors raise."""
    r = session.get(API, params={"action": "parse", "page": title, "prop": "wikitext", "redirects": 1,
                                 "format": "json", "formatversion": 2}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        return None
    return (d.get("parse") or {}).get("wikitext")


def seeds_for(session, cache: Path, sport_key: str, year: int) -> tuple[dict | None, str]:
    """Cached seeds of one event, fetching once if needed. -> (seeds or None, log note)."""
    path = cache / "wiki_seeds.json"
    known = json.loads(path.read_text()) if path.exists() else {}
    k = f"{sport_key}:{year}"
    if k in known:
        return known[k], "cached"
    for title in titles(sport_key, year):
        try:
            text = fetch(session, title)
        except Exception as e:   # never str(e)
            code = getattr(getattr(e, "response", None), "status_code", None)
            return None, f"fetch failed ({type(e).__name__}{f' {code}' if code else ''})"
        if text is None:
            continue
        got = parse(text)
        if got is None:
            return None, f"'{title}' has no clean seed list"
        known[k] = got
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(known, indent=1))
        return got, f"parsed '{title}' ({len(got['seeds'])} seeds, {len(got['qualifiers'])} qualifiers)"
    return None, "no article" if titles(sport_key, year) else "no title known"
