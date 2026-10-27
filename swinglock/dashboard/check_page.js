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
      // Paper tab: rules, trades (all, then settled only), lookback.
      await page.click('.views button[data-view="paper"]');
      await page.waitForFunction(() => !document.getElementById("view-paper").hidden);
      await page.waitForFunction(() => !document.getElementById("view-paper").textContent.includes("Loading…"));
      const paperGrab = () => page.evaluate(() => {
        const box = document.getElementById("view-paper");
        return {
          rules: box.querySelectorAll("table.paper-rules tbody tr:not(:has(td.empty))").length,
          trades: box.querySelectorAll("table.paper-trades tbody tr:not(:has(td.empty))").length,
          locked: box.querySelectorAll("table.paper-trades tr.hot-lock").length,
          lookbackRows: box.querySelectorAll("table.lookback tbody tr:not(:has(td.empty))").length,
          days: box.querySelectorAll("table.by-day tbody tr").length,
          height: document.documentElement.scrollHeight,
          notes: [...box.querySelectorAll(".card-note, .banner.inline")].map((n) => n.textContent),
          overflow: document.documentElement.scrollWidth - window.innerWidth,
          liveHidden: document.getElementById("view-live").hidden,
        };
      });
      info.paper = await paperGrab();
      if (info.paper.overflow > 0) problems.push(`${tag} paper overflow ${info.paper.overflow}px`);
      if (outDir) await page.screenshot({ path: path.join(outDir, `dashboard-paper-${tag}.png`), fullPage: true });
      if (await page.$("#view-paper select[aria-label='Trade status']")) {
        await page.selectOption("#view-paper select[aria-label='Trade status']", "settled");
        info.paperSettled = (await paperGrab()).trades;
        await page.selectOption("#view-paper select[aria-label='Trade status']", "all");
      }
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
  console.log(JSON.stringify({ results, problems }, null, 2));
  process.exit(problems.length ? 1 : 0);
})();
