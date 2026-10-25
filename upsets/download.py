"""Download tennis-data.co.uk yearly result + closing-odds files (ATP and WTA).

    python -m upsets.download [--from 2013] [--to 2026] [--out data/raw/tennis_data]

Files: http://www.tennis-data.co.uk/<year>/<year>.xlsx (ATP) and .../<year>w/<year>.xlsx (WTA).
Years before 2013 are .xls (needs xlrd), so the default starts at 2013. Already-downloaded
years are skipped, except the current year, which is refreshed. One request every 2 s.
"""

from __future__ import annotations

import argparse
import datetime as dt
import time
from pathlib import Path

import requests

BASE = "http://www.tennis-data.co.uk"


def url(tour: str, year: int) -> str:
    ext = "xlsx" if year >= 2013 else "xls"
    return f"{BASE}/{year}{'w' if tour == 'wta' else ''}/{year}.{ext}"


def download(out_dir: str | Path, years: range, tours=("atp", "wta"), session=None, pause: float = 2.0) -> list[Path]:
    session = session or requests.Session()
    this_year = dt.date.today().year
    saved = []
    for tour in tours:
        Path(out_dir, tour).mkdir(parents=True, exist_ok=True)
        for y in years:
            u = url(tour, y)
            path = Path(out_dir, tour, u.rsplit("/", 1)[1])
            if path.exists() and y != this_year:
                continue
            r = session.get(u, timeout=60)
            if r.status_code == 404:
                print(f"{tour} {y}: not published")
                continue
            r.raise_for_status()
            path.write_bytes(r.content)
            saved.append(path)
            print(f"{tour} {y}: {len(r.content):,} bytes -> {path}")
            time.sleep(pause)
    return saved


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="start", type=int, default=2013)
    ap.add_argument("--to", dest="end", type=int, default=dt.date.today().year)
    ap.add_argument("--out", default="data/raw/tennis_data")
    args = ap.parse_args(argv)
    download(args.out, range(args.start, args.end + 1))


if __name__ == "__main__":
    main()
