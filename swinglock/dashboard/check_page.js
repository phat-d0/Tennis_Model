// Browser check + screenshots for the dashboard (Playwright, Node).
//   node swinglock/dashboard/check_page.js <base_url> [out_dir] [search_term]
// Loads the page at phone (390x844) and laptop (1280x800) sizes in light and dark mode,
// fails on any page error / console error or horizontal overflow, and saves screenshots.
"use strict";
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const base = process.argv[2];
const outDir = process.argv[3] || "";
const search = process.argv[4] || "";   // optional search term to exercise the filter
const VIEWPORTS = { phone: { width: 390, height: 844 }, laptop: { width: 1280, height: 800 } };

(async () => {
  const browser = await chromium.launch();
  const problems = [];
  const results = [];
  for (const [vpName, vp] of Object.entries(VIEWPORTS)) {
    for (const scheme of ["light", "dark"]) {
      const ctx = await browser.newContext({ viewport: vp, colorScheme: scheme, deviceScaleFactor: 1 });
      const page = await ctx.newPage();
      const tag = `${vpName}-${scheme}`;
      page.on("pageerror", (e) => problems.push(`${tag} pageerror: ${e.message}`));
      page.on("console", (m) => { if (m.type() === "error") problems.push(`${tag} console: ${m.text()}`); });
      page.on("request", (r) => { if (!r.url().startsWith(base)) problems.push(`${tag} external request: ${r.url()}`); });
      await page.goto(base, { waitUntil: "networkidle" });
      await page.waitForFunction(() => document.body.dataset.status);
      const info = await page.evaluate(() => ({
        overflow: document.documentElement.scrollWidth - window.innerWidth,
        status: document.body.dataset.status,
        banner: document.getElementById("banner").hidden ? "" : document.getElementById("banner").textContent,
        markets: document.querySelectorAll("#markets tr:not(:has(td.empty))").length,
        noMarket: document.getElementById("nomarket").hidden ? 0 : document.querySelectorAll("#nomarket-list li").length,
        firstMarket: document.querySelector("#markets tr .players")?.textContent || "",
        arbRows: document.querySelectorAll("#markets tr.hot-arb").length,
        breakEven: [...document.querySelectorAll("#markets .badge")].filter((b) => b.textContent === "break-even").length,
        arbTile: [...document.querySelectorAll("#summary .tile")].find((t) => t.textContent.startsWith("Arbs open"))?.querySelector(".v")?.textContent || "",
        tierLabels: [...new Set([...document.querySelectorAll("#markets td.match .sub")].map((d) => d.firstChild?.textContent || ""))].sort(),
        lockRows: document.querySelectorAll("#positions tr.hot-lock").length,
        alerts: document.querySelectorAll("#alerts li").length,
        bg: getComputedStyle(document.body).backgroundColor,
      }));
      if (info.overflow > 0) problems.push(`${tag} horizontal overflow ${info.overflow}px`);
      if (outDir) {
        fs.mkdirSync(outDir, { recursive: true });
        await page.screenshot({ path: path.join(outDir, `dashboard-${tag}.png`), fullPage: true });
      }
      // Paper tab, three levels (home › portfolio › strategy). Readings from both portfolios are
      // combined under the keys the tests used before the folder layout, plus per-level keys.
      await page.click('.views button[data-view="paper"]');
      await page.waitForFunction(() => !document.getElementById("view-paper").hidden);
      await page.waitForFunction(() => !document.getElementById("view-paper").textContent.includes("Loading…"));
      const grab = () => page.evaluate(() => {
        const box = document.getElementById("view-paper");
        const txt = (sel, n) => [...box.querySelectorAll(sel)].map((x) => x.textContent);
        return {
          level: box.dataset.level,
          folders: txt(".card.list.folders > .row-btn .who b"),
          folderVals: txt(".card.list.folders > .row-btn .vals b"),
          crumbs: txt(".crumbs .crumb"),
          title: box.querySelector(".pf-title")?.textContent || "",
          rules: box.querySelectorAll("table.paper-rules tbody tr:not(.total):not(.group):not(.startup):not(:has(td.empty))").length,
          startup: box.querySelectorAll("table.paper-rules tr.startup").length,
          total: box.querySelector("table.paper-rules tr.total td:nth-child(7)")?.textContent || "",
          perContract: txt("table.paper-rules tbody tr:not(.total):not(.group):not(.startup) td:nth-child(7)"),
          trades: box.querySelectorAll("table.paper-trades tbody tr:not(:has(td.empty))").length,
          locked: box.querySelectorAll("table.paper-trades tr.hot-lock").length,
          startupBadges: [...box.querySelectorAll("table.paper-trades .badge")].filter((b) => b.textContent === "start-up").length,
          sold: [...box.querySelectorAll("table.paper-trades td")].filter((td) => td.textContent.startsWith("sold @")).length,
          lookbackRows: box.querySelectorAll("table.lookback tbody tr:not(:has(td.empty))").length,
          lbPerCt: txt("table.lookback tbody tr td:nth-child(8)"),
          lbCashRows: box.querySelectorAll("table.lookback-cash tbody tr").length,
          lbCashDelta: txt("table.lookback-cash tbody tr td:nth-child(8)"),
          days: box.querySelectorAll("table.by-day tbody tr").length,
          chart: !!box.querySelector("svg.daychart"),
          charts: box.querySelectorAll("svg.daychart").length,
          chartLines: box.querySelectorAll("svg.daychart path, svg.daychart circle").length,
          notes: txt(".card-note, .banner.inline"),
          metaLines: txt(".meta-line"),
          hypo: box.querySelector(".badge.hypo")?.textContent || "",
          intro: box.querySelector(".paper-note b")?.textContent || "",
          cashRules: box.querySelectorAll("table.paper-cash tbody tr:not(.group):not(.startup)").length,
          cashStartup: box.querySelectorAll("table.paper-cash tr.startup").length,
          cashPerCt: txt("table.paper-cash tbody tr:not(.group):not(.startup) td:nth-child(6)"),
          cashDelta: txt("table.paper-cash tbody tr:not(.group):not(.startup) td:nth-child(7)"),
          cashSpread: txt("table.paper-cash tbody tr:not(.group):not(.startup) td:nth-child(8)"),
          cashHead: txt("h2:not(.pf-title)").find((t) => t.startsWith("Cash-out")) || "",
          toggle: txt(".segmented button"),
          overflow: document.documentElement.scrollWidth - window.innerWidth,
          liveHidden: document.getElementById("view-live").hidden,
        };
      });
      const chipCount = async (k) => {
        if (!(await page.$(`#view-paper .chip[data-filter='${k}']`))) return 0;
        await page.click(`#view-paper .chip[data-filter='${k}']`);
        const n = (await grab()).trades;
        await page.click("#view-paper .chip[data-filter='all']");
        return n;
      };
      const shot = async (name) => { if (outDir) await page.screenshot({ path: path.join(outDir, `dashboard-paper-${name}-${tag}.png`), fullPage: true }); };
      const levels = {};
      levels.home = await grab();
      await shot("home");
      const ports = {};
      for (const g of ["swing", "cashout"]) {
        if (!(await page.$(`#view-paper [data-pfid='${g}']`))) continue;
        await page.click(`#view-paper [data-pfid='${g}']`);
        ports[g] = await grab();
        ports[g].settled = await chipCount("settled");
        ports[g].exited = await chipCount("exited");
        await shot(g === "swing" ? "portfolio" : "cashout");
        // first strategy: Live paper, then Backtest; then back up via the crumbs
        await page.click("#view-paper [data-pfstrat]");
        ports[g].strategyLive = await grab();
        await page.click("#view-paper .segmented button[data-pf='backtest']");
        ports[g].strategyBacktest = await grab();
        if (g === "cashout") await shot("strategy");
        await page.click("#view-paper .segmented button[data-pf='live']");
        await page.click("#view-paper .crumbs [data-pfnav='portfolio']");
        ports[g].backToPortfolio = (await grab()).level;
        await page.click("#view-paper .crumbs [data-pfnav='home']");
      }
      // tapping the Paper tab again from a deeper level returns home
      if (await page.$("#view-paper [data-pfid='swing']")) {
        await page.click("#view-paper [data-pfid='swing']");
        await page.click('.views button[data-view="paper"]');
        levels.tapAgain = (await grab()).level;
      }
      const sw = ports.swing || levels.home, ca = ports.cashout || {};
      const sum = (k) => (ports.swing ? ports.swing[k] : 0) + (ca[k] || 0);
      info.paper = {
        ...sw,
        trades: ports.swing ? sum("trades") : 0, locked: sum("locked"), sold: sum("sold"), startupBadges: sum("startupBadges"),
        charts: sum("charts"), chartLines: sum("chartLines"),
        notes: ports.swing ? sw.notes : levels.home.notes, metaLines: [...(sw.metaLines || []), ...(ca.metaLines || [])],
        cashRules: ca.cashRules || 0, cashStartup: ca.cashStartup || 0, cashPerCt: ca.cashPerCt || [], cashDelta: ca.cashDelta || [],
        cashSpread: ca.cashSpread || [], cashHead: ca.cashHead || "", lbCashRows: ca.lbCashRows || 0, lbCashDelta: ca.lbCashDelta || [],
        overflow: Math.max(levels.home.overflow, ...Object.values(ports).flatMap((x) => [x.overflow, x.strategyLive.overflow, x.strategyBacktest.overflow])),
      };
      info.paperLevels = { home: levels.home, tapAgain: levels.tapAgain, ...ports };
      if (ports.swing) info.paperSettled = sum("settled");
      if (ca.exited !== undefined) info.paperExited = ca.exited;
      if (info.paper.overflow > 0) problems.push(`${tag} paper overflow ${info.paper.overflow}px`);
      await page.click('.views button[data-view="live"]');

      // Filters: row counts after a search, after a phase filter, and with both cleared.
      const count = () => page.evaluate(() => ({
        rows: document.querySelectorAll("#markets tr:not(:has(td.empty))").length,
        noMarket: document.getElementById("nomarket").hidden ? 0 : document.querySelectorAll("#nomarket-list li").length,
        label: document.getElementById("m-count").textContent,
      }));
      info.filters = {};
      if (search) {
        await page.fill("#q", search);
        info.filters.search = await count();
        await page.fill("#q", "");
      }
      await page.selectOption("#phase", "pre");
      info.filters.pre = await count();
      await page.selectOption("#phase", "all");
      info.filters.all = await count();
      results.push({ tag, ...info });
      await ctx.close();
    }
  }
  await browser.close();
  // write, then exit once flushed: a large result piped to Python would otherwise be cut off at 64 KB
  process.stdout.write(JSON.stringify({ results, problems }, null, 2) + "\n", () => process.exit(problems.length ? 1 : 0));
})();
