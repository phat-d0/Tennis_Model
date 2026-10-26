"""Public Tennis Odds page (site/): fixture contract, static-file rules, browser smoke test."""

from __future__ import annotations

import functools
import json
import os
import re
import shutil
import subprocess
import threading
from datetime import UTC, datetime, timedelta
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SITE = ROOT / "site"
SAMPLE = Path(__file__).parent / "test_site_data" / "odds.json"
OWN_FILES = ["index.html", "app.js", "style.css", "manifest.webmanifest", "sw.js", "icons/icon.svg"]

STATUSES = {"ok", "no_key", "cap_reached", "below_floor", "no_tournaments"}
BOOK_KEYS = {"odds_1", "odds_2", "last_update", "margin"}
MATCH_KEYS = {"event_id", "sport_key", "tournament", "tour", "commence_time", "player_1", "player_2",
              "draftkings", "pinnacle", "fair_1", "dk_implied_1", "model_p1", "model_n1", "model_n2"}


def _iso(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _fmt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def sample() -> dict:
    return json.loads(SAMPLE.read_text())


def shifted(data: dict, built_ago: timedelta = timedelta(minutes=5)) -> dict:
    """Move every timestamp so the build happened `built_ago` before now (starts keep their offsets)."""
    delta = datetime.now(UTC) - built_ago - _iso(data["generated_at"])
    out = json.loads(json.dumps(data))
    move = lambda ts: _fmt(_iso(ts) + delta) if ts else ts  # noqa: E731
    out["generated_at"] = move(out["generated_at"])
    out["odds_fetched_at"] = move(out["odds_fetched_at"])
    for m in out["matches"]:
        m["commence_time"] = move(m["commence_time"])
        for b in ("draftkings", "pinnacle"):
            if m[b]:
                m[b]["last_update"] = move(m[b]["last_update"])
    return out


# ---------------------------------------------------------------- fixture

def test_sample_matches_contract():
    d = sample()
    assert set(d) == {"generated_at", "odds_fetched_at", "status", "credits", "ratings_through",
                      "tournaments", "matches"}
    _iso(d["generated_at"]), _iso(d["odds_fetched_at"])
    assert d["status"] in STATUSES or d["status"].startswith("error")
    assert set(d["credits"]) == {"left", "used_this_month", "month_cap"}
    datetime.strptime(d["ratings_through"], "%Y-%m-%d")
    keys = {t["sport_key"] for t in d["tournaments"]}
    for t in d["tournaments"]:
        assert set(t) == {"sport_key", "title", "tour"} and t["tour"] in ("ATP", "WTA")
    for m in d["matches"]:
        assert set(m) == MATCH_KEYS, m["event_id"]
        assert m["sport_key"] in keys and m["tour"] in ("ATP", "WTA")
        _iso(m["commence_time"])
        for b in ("draftkings", "pinnacle"):
            if m[b] is not None:
                assert set(m[b]) == BOOK_KEYS
                assert m[b]["margin"] == pytest.approx(1 / m[b]["odds_1"] + 1 / m[b]["odds_2"] - 1, abs=1e-4)
        ref = m["pinnacle"] or m["draftkings"]
        if ref:
            i1, i2 = 1 / ref["odds_1"], 1 / ref["odds_2"]
            assert m["fair_1"] == pytest.approx(i1 / (i1 + i2), abs=1e-4)
        if m["draftkings"]:
            assert m["dk_implied_1"] == pytest.approx(1 / m["draftkings"]["odds_1"], abs=1e-4)
        else:
            assert m["dk_implied_1"] is None
        if m["model_p1"] is not None:
            assert min(m["model_n1"], m["model_n2"]) >= 20


def test_sample_covers_display_cases():
    ms = sample()["matches"]
    assert any(m["draftkings"] is None for m in ms) and any(m["pinnacle"] is None for m in ms)
    assert any(m["model_p1"] is None for m in ms)
    assert {m["tour"] for m in ms} == {"ATP", "WTA"}
    assert len({m["tournament"] for m in ms}) >= 3


# ---------------------------------------------------------------- static rules

def test_site_is_static_and_self_contained():
    for name in OWN_FILES:
        text = (SITE / name).read_text()
        # nothing loaded from another origin: scripts, styles, images, fetches, imports
        assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", text, re.I), name
        assert not re.search(r"""(fetch|importScripts|import)\s*\(\s*["'`](https?:)?//""", text), name
        assert not re.search(r"@import|url\(\s*[\"']?(https?:)?//", text), name
    js = (SITE / "app.js").read_text()
    # the only absolute URLs in the app are plain links (reports, attribution), never fetched
    for url in re.findall(r"https?://[^\s\"'`)]+", js):
        assert url.startswith(("https://github.com/", "https://creativecommons.org/")), url
    assert set(re.findall(r"""fetch\(\s*([A-Za-z_]+|["'][^"']+["'])""", js)) == {"url"}
    assert re.findall(r'_URL = "([^"]+)"', js) == ["data/odds.json", "findings.json"]
    manifest = json.loads((SITE / "manifest.webmanifest").read_text())
    for icon in manifest["icons"]:
        assert (SITE / icon["src"]).is_file()
    assert (SITE / "icons" / "apple-touch-icon.png").is_file()


def test_no_kalshi_anywhere_in_page_code():
    """Hard rule: the public page carries no Kalshi data (findings.json is the Lead's prose)."""
    for path in [*(SITE / n for n in OWN_FILES), SAMPLE]:
        assert "kalshi" not in path.read_text().lower(), path.name


# ---------------------------------------------------------------- browser

CHECK_JS = r"""
const { chromium } = require("playwright");
const fs = require("fs"), path = require("path");
const [base, outDir, prefix, allowConsole] = process.argv.slice(2);
const VIEWPORTS = { phone: { width: 390, height: 844 }, laptop: { width: 1280, height: 800 } };
(async () => {
  const browser = await chromium.launch();
  const results = [], problems = [];
  for (const [vp, size] of Object.entries(VIEWPORTS)) for (const scheme of ["light", "dark"]) {
    const tag = `${vp}-${scheme}`;
    const ctx = await browser.newContext({ viewport: size, colorScheme: scheme, serviceWorkers: "block" });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => problems.push(`${tag} pageerror: ${e.message}`));
    page.on("console", (m) => {
      if (m.type() === "error" && !(allowConsole && m.text().includes(allowConsole))) problems.push(`${tag} console: ${m.text()}`);
    });
    page.on("request", (r) => { if (!r.url().startsWith(base)) problems.push(`${tag} external request: ${r.url()}`); });
    await page.goto(base, { waitUntil: "networkidle" });
    await page.waitForFunction(() => document.getElementById("updated").textContent !== "Loading…");
    const grab = () => page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth - window.innerWidth,
      banners: [...document.querySelectorAll("#banners .banner b")].map((b) => b.textContent),
      groups: [...document.querySelectorAll("#view h2.section-title > span:first-child")].map((s) => s.textContent),
      cards: document.querySelectorAll("#view article.match").length,
      notProven: [...document.querySelectorAll("#view .tag")].filter((t) => t.textContent === "model: not proven").length,
      empty: document.querySelector("#view .empty")?.textContent || "",
      updated: document.getElementById("updated").textContent,
      footer: document.getElementById("footer").textContent,
      firstPlayer: document.querySelector("#view article.match .players span")?.textContent || "",
      bg: getComputedStyle(document.body).backgroundColor,
    }));
    const info = await grab();
    if (outDir) {
      fs.mkdirSync(outDir, { recursive: true });
      await page.screenshot({ path: path.join(outDir, `${prefix}-matches-${tag}.png`), fullPage: true });
    }
    await page.click('.tabbar button[data-tab="findings"]');
    info.findings = await page.evaluate(() => ({
      lead: document.querySelector("#view .lead")?.textContent || "",
      cards: document.querySelectorAll("#view article.finding").length,
      overflow: document.documentElement.scrollWidth - window.innerWidth,
    }));
    if (outDir && vp === "phone") await page.screenshot({ path: path.join(outDir, `${prefix}-findings-${tag}.png`), fullPage: true });
    await page.click('.tabbar button[data-tab="matches"]');
    if (await page.$("#view .segmented button:nth-child(3)")) {
      await page.click("#view .segmented button:nth-child(3)");   // WTA
      info.wtaCards = await page.evaluate(() => document.querySelectorAll("#view article.match").length);
    }
    for (const o of [info.overflow, info.findings.overflow]) if (o > 0) problems.push(`${tag} horizontal overflow ${o}px`);
    results.push({ tag, ...info });
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify({ results, problems }));
})();
"""


def _node_playwright() -> bool:
    if not shutil.which("node"):
        return False
    return subprocess.run(["node", "-e", "require('playwright')"], capture_output=True).returncode == 0


def _findings() -> list:
    f = SITE / "findings.json"   # the Lead's file; a stand-in until it lands on this branch
    if f.is_file():
        return json.loads(f.read_text())
    return [{"title": "Stand-in finding", "verdict": "No edge", "summary": "Placeholder.", "report": "reports/x.md"},
            {"title": "Another", "verdict": "In progress", "summary": "Placeholder.", "report": ""}]


@pytest.fixture()
def site(tmp_path):
    """Serve a copy of site/ laid out like the published _site/, with the given odds.json."""
    servers = []

    def start(odds: dict | str | None) -> str:
        root = tmp_path / f"site{len(servers)}"
        shutil.copytree(SITE, root)
        (root / "findings.json").write_text(json.dumps(_findings()))
        if odds is not None:
            (root / "data").mkdir()
            (root / "data" / "odds.json").write_text(odds if isinstance(odds, str) else json.dumps(odds))
        handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
        handler.log_message = lambda *a: None
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}/"

    yield start
    for s in servers:
        s.shutdown()
        s.server_close()


def _check(tmp_path, base: str, prefix: str, allow_console: str = "") -> list[dict]:
    script = tmp_path / "check.js"
    script.write_text(CHECK_JS)
    shots = os.environ.get("SITE_SHOTS_DIR", "")
    r = subprocess.run(["node", str(script), base, shots, prefix, allow_console],
                       capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out["problems"] == [], out["problems"]
    assert len(out["results"]) == 4
    return out["results"]


def _common(res: dict) -> None:
    f = res["findings"]
    assert f["lead"] == "Every test so far: no edge after fees"
    assert f["cards"] == len(_findings())
    assert "CC BY-NC-SA" in res["footer"] and "non-commercial" in res["footer"]
    assert "Refreshes every 3 h, often late" in res["footer"]


needs_browser = pytest.mark.skipif(not _node_playwright(), reason="needs node + playwright")


@needs_browser
def test_page_ok(site, tmp_path):
    d = shifted(sample())
    for res in _check(tmp_path, site(d), "site"):
        _common(res)
        assert res["banners"] == []
        assert res["cards"] == len(d["matches"]) == res["notProven"]
        # tournaments ordered by first start time (the Challenger match started 30 min before the build)
        assert res["groups"] == ["ATP Brest Challenger", "ATP Paris Masters", "WTA Finals"]
        assert res["wtaCards"] == 2
        assert res["updated"].startswith("Odds ") and "143 of 600" in res["footer"]
        assert "2026-10-19" in res["footer"]


@needs_browser
def test_page_stale_and_capped(site, tmp_path):
    d = shifted(sample(), built_ago=timedelta(hours=14))
    d["status"] = "cap_reached"
    for res in _check(tmp_path, site(d), "stale"):
        _common(res)
        assert res["banners"] == ["Monthly odds budget used up", "Old odds", "Page not rebuilt lately"]
        assert res["cards"] == len(d["matches"])


@needs_browser
def test_page_error_status_null_books_and_model(site, tmp_path):
    d = shifted(sample())
    d["status"] = "error: Odds API timed out"
    for m in d["matches"]:
        m.update(draftkings=None, pinnacle=None, fair_1=None, dk_implied_1=None, model_p1=None, model_n1=None)
    d["odds_fetched_at"] = None
    d["credits"] = None
    for res in _check(tmp_path, site(d), "error"):
        _common(res)
        assert res["banners"] == ["The last update failed", "Odds time unknown"]
        assert res["cards"] == len(d["matches"])


@needs_browser
def test_page_empty(site, tmp_path):
    d = shifted(sample())
    d.update(status="no_tournaments", matches=[], tournaments=[])
    for res in _check(tmp_path, site(d), "empty"):
        _common(res)
        assert res["banners"] == ["No tournaments right now"]
        assert res["cards"] == 0 and "No matches with odds" in res["empty"]


@needs_browser
@pytest.mark.parametrize("odds", [None, '{"generated_at": "2026-'], ids=["missing", "invalid"])
def test_page_without_usable_data(site, tmp_path, odds):
    allow = "404" if odds is None else ""
    for res in _check(tmp_path, site(odds), "nodata", allow_console=allow):
        _common(res)
        assert res["banners"] == ["No odds data yet"]
        assert res["updated"] == "No data" and res["cards"] == 0
