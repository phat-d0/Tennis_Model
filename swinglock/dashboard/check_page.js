// Browser check + screenshots for the dashboard (Playwright, Node).
//   node swinglock/dashboard/check_page.js <base_url> [out_dir]
// Loads the page at phone (390x844) and laptop (1280x800) sizes in light and dark mode,
// fails on any page error / console error or horizontal overflow, and saves screenshots.
"use strict";
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const base = process.argv[2];
const outDir = process.argv[3] || "";
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
        markets: document.querySelectorAll("#markets tr").length,
        firstMarket: document.querySelector("#markets tr .players")?.textContent || "",
        arbRows: document.querySelectorAll("#markets tr.hot-arb").length,
        lockRows: document.querySelectorAll("#positions tr.hot-lock").length,
        alerts: document.querySelectorAll("#alerts li").length,
        bg: getComputedStyle(document.body).backgroundColor,
      }));
      if (info.overflow > 0) problems.push(`${tag} horizontal overflow ${info.overflow}px`);
      results.push({ tag, ...info });
      if (outDir) {
        fs.mkdirSync(outDir, { recursive: true });
        await page.screenshot({ path: path.join(outDir, `dashboard-${tag}.png`), fullPage: true });
      }
      await ctx.close();
    }
  }
  await browser.close();
  console.log(JSON.stringify({ results, problems }, null, 2));
  process.exit(problems.length ? 1 : 0);
})();
