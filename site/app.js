// Tennis Odds: a static page over data/odds.json (built every 3 h by GitHub Actions) and
// findings.json. No external requests; every bad state shows a banner and keeps the page usable.
"use strict";

const ODDS_URL = "data/odds.json";
const FINDINGS_URL = "findings.json";
const STALE_ODDS_H = 6;          // banner when odds are older than this
const STALE_BUILD_H = 12;        // banner when the page itself hasn't been rebuilt for this long
const REPORT_BASE = "https://github.com/phat-d0/Tennis_Model/blob/main/";

const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
};

let odds = null;        // last good odds.json
let oddsErr = "";       // why odds.json couldn't be loaded ("" when it could)
let findings = null;    // last good findings.json (array)
let findingsErr = "";
let tab = location.hash === "#findings" ? "findings" : "matches";
let tour = store.get("tennis-tour", "all");

const $ = (id) => document.getElementById(id);

function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else if (k === "style") n.style.cssText = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

// ---------------------------------------------------------------- formatting

const isNum = (x) => typeof x === "number" && Number.isFinite(x);
const na = () => el("span", { class: "na" }, "—");
const dec = (x) => (isNum(x) && x > 1 ? x.toFixed(2) : na());
const pct = (p, dp = 0) => (isNum(p) && p >= 0 && p <= 1 ? (p * 100).toFixed(dp) + "%" : na());

function parseTs(ts) {
  const t = Date.parse(ts || "");
  return Number.isFinite(t) ? t : null;
}
function ageText(ts) {
  const t = parseTs(ts);
  if (t === null) return null;
  const min = Math.round((Date.now() - t) / 60000);
  if (min < -5) return "in the future";
  if (min < 1) return "just now";
  if (min < 90) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.round(h / 24)} days ago`;
}
const ageHours = (ts) => { const t = parseTs(ts); return t === null ? null : (Date.now() - t) / 3.6e6; };

function startText(ts) {
  const t = parseTs(ts);
  if (t === null) return "Time TBC";
  const d = new Date(t);
  const day = new Date(t).setHours(0, 0, 0, 0);
  const today = new Date().setHours(0, 0, 0, 0);
  const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const days = Math.round((day - today) / 864e5);   // round: a DST change makes a day 23 or 25 h
  if (days === 0) return `Today ${time}`;
  if (days === 1) return `Tomorrow ${time}`;
  return `${d.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })} ${time}`;
}

// Short column header for a player: the surname, unless both players share it.
function shortNames(p1, p2) {
  const last = (s) => String(s || "").trim().split(/\s+/).pop() || "?";
  const a = last(p1), b = last(p2);
  return a === b ? [p1 || "?", p2 || "?"] : [a, b];
}

// ---------------------------------------------------------------- banners

const STATUS_TEXT = {
  no_key: ["Odds aren't refreshing", "No API key is set for the build, so these are the last saved odds."],
  cap_reached: ["Monthly odds budget used up", "Odds stop refreshing until next month. These are the last saved odds."],
  below_floor: ["Odds aren't refreshing", "The shared credit balance is at its reserve. These are the last saved odds."],
  paced: ["Odds refresh later today", "Today's share of the monthly budget is used. These are the last saved odds."],
  no_tournaments: ["No tournaments right now", "No ATP or WTA tournament has a match in the next 36 hours."],
};

function banners() {
  const out = [];
  const add = (title, text, bad) => out.push(el("div", { class: "banner" + (bad ? " bad" : ""), role: "status" }, el("b", {}, title), text));
  if (oddsErr) {
    add(odds ? "Can't refresh the odds" : "No odds data yet",
      odds ? `${oddsErr}. Showing the odds loaded earlier.` : `${oddsErr}. The first build may not have run yet.`, true);
  }
  if (!odds) return out;
  const status = typeof odds.status === "string" ? odds.status : "missing";
  if (status !== "ok") {
    if (STATUS_TEXT[status]) add(...STATUS_TEXT[status], false);
    else if (status.startsWith("error")) add("The last update failed", `${status.replace(/^error:?\s*/, "") || "unknown error"}. These are the last saved odds.`, true);
    else add("Unexpected data status", `Status "${status}". The odds below may be out of date.`, true);
  }
  const oh = ageHours(odds.odds_fetched_at);
  if (oh === null) {
    if ((odds.matches || []).length) add("Odds time unknown", "The data doesn't say when these odds were fetched.", false);
  } else if (oh > STALE_ODDS_H) {
    add("Old odds", `These odds were fetched ${ageText(odds.odds_fetched_at)}. Prices move; check the book before acting.`, false);
  }
  const bh = ageHours(odds.generated_at);
  if (bh !== null && bh > STALE_BUILD_H) {
    add("Page not rebuilt lately", `The last build ran ${ageText(odds.generated_at)}; scheduled runs can be late or skipped.`, false);
  }
  return out;
}

// ---------------------------------------------------------------- matches tab

function matchCard(m) {
  const [n1, n2] = shortNames(m.player_1, m.player_2);
  const dk = m.draftkings && typeof m.draftkings === "object" ? m.draftkings : null;
  const pin = m.pinnacle && typeof m.pinnacle === "object" ? m.pinnacle : null;
  const fair = isNum(m.fair_1) && m.fair_1 >= 0 && m.fair_1 <= 1 ? m.fair_1 : null;
  const model = isNum(m.model_p1) && m.model_p1 >= 0 && m.model_p1 <= 1 ? m.model_p1 : null;
  const started = (parseTs(m.commence_time) ?? Infinity) <= Date.now();

  const row = (label, a, b) => el("tr", {}, el("td", {}, label), el("td", {}, a), el("td", {}, b));
  const foot = [];
  if (dk && isNum(dk.margin)) foot.push(`DraftKings margin ${(dk.margin * 100).toFixed(1)}%`);
  if (pin && isNum(pin.margin)) foot.push(`Pinnacle margin ${(pin.margin * 100).toFixed(1)}%`);
  if (fair !== null) foot.push(`Fair chance from ${pin ? "Pinnacle" : "DraftKings"}, margin removed`);
  if (model === null) {
    foot.push(isNum(m.model_n1) && isNum(m.model_n2)
      ? `No model: rated matches ${m.model_n1} / ${m.model_n2} (needs 20 each and matched names)`
      : "No model for this match");
  } else if (isNum(m.model_n1) && isNum(m.model_n2)) {
    foot.push(`Model from ${m.model_n1} / ${m.model_n2} rated matches`);
  }

  return el("article", { class: "card match" },
    el("div", { class: "match-head" },
      el("span", {}, startText(m.commence_time)),
      el("span", {}, started ? el("span", { class: "tag warn" }, "Started: odds were pre-match") : (m.tour || ""))),
    el("div", { class: "players" },
      el("i", { class: "dot1" }), el("span", {}, m.player_1 || "?"),
      el("i", { class: "dot2" }), el("span", {}, m.player_2 || "?")),
    fair !== null && el("div", { class: "probbar", "aria-hidden": "true" },
      el("span", { style: `flex:${fair}` }), el("span", { style: `flex:${1 - fair}` })),
    el("table", { class: "odds" },
      el("thead", {}, el("tr", {}, el("th", {}, ""), el("th", { title: m.player_1 || "" }, n1), el("th", { title: m.player_2 || "" }, n2))),
      el("tbody", {},
        row("DraftKings", dk ? dec(dk.odds_1) : na(), dk ? dec(dk.odds_2) : na()),
        row("Pinnacle", pin ? dec(pin.odds_1) : na(), pin ? dec(pin.odds_2) : na()),
        row("Fair chance", fair === null ? na() : pct(fair), fair === null ? na() : pct(1 - fair)),
        row(el("span", {}, "Model ", el("span", { class: "tag" }, "model: not proven")),
          model === null ? na() : pct(model), model === null ? na() : pct(1 - model)))),
    foot.length && el("div", { class: "card-foot" }, foot.map((f) => el("span", {}, f))));
}

function matchesView() {
  const all = odds && Array.isArray(odds.matches) ? odds.matches.filter((m) => m && typeof m === "object") : [];
  const counts = { all: all.length, ATP: 0, WTA: 0 };
  for (const m of all) if (m.tour in counts) counts[m.tour] += 1;
  if (!(tour in counts)) tour = "all";
  const shown = tour === "all" ? all : all.filter((m) => m.tour === tour);

  const seg = el("div", { class: "segmented", role: "tablist", "aria-label": "Tour" },
    ["all", "ATP", "WTA"].map((t) => el("button", {
      class: t === tour ? "on" : "", role: "tab", "aria-selected": String(t === tour),
      onclick: () => { tour = t; store.set("tennis-tour", t); render(); },
    }, `${t === "all" ? "All" : t} (${counts[t]})`)));

  if (!shown.length) {
    const msg = !odds ? "No odds to show yet."
      : all.length ? `No ${tour} matches in the next 36 hours.`
      : "No matches with odds in the next 36 hours.";
    return [seg, el("div", { class: "card empty" }, msg)];
  }

  // Group by tournament; tournaments ordered by their first start time, matches by start time.
  const byStart = (a, b) => (parseTs(a.commence_time) ?? Infinity) - (parseTs(b.commence_time) ?? Infinity);
  const groups = new Map();
  for (const m of [...shown].sort(byStart)) {
    const key = m.tournament || m.sport_key || "Other";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(m);
  }
  const out = [seg];
  for (const [name, ms] of groups) {
    out.push(el("h2", { class: "section-title" }, el("span", {}, name),
      el("span", { class: "count" }, `${ms.length} match${ms.length === 1 ? "" : "es"}`)));
    for (const m of ms) out.push(matchCard(m));
  }
  out.push(el("p", { class: "note" },
    "Decimal odds. Fair chance = the book's implied chance with its margin removed. The model is a surface-weighted Elo rating that has not beaten the market in any test, so treat it as context, not a tip."));
  return out;
}

// ---------------------------------------------------------------- findings tab

function findingsView() {
  const out = [el("p", { class: "lead" }, "Every test so far: no edge after fees")];
  if (!findings) {
    out.push(el("div", { class: "card empty" }, findingsErr ? `Findings unavailable (${findingsErr}).` : "Loading…"));
    return out;
  }
  if (!findings.length) out.push(el("div", { class: "card empty" }, "No findings yet."));
  for (const f of findings) {
    if (!f || typeof f !== "object") continue;
    const verdict = String(f.verdict || "");
    const report = typeof f.report === "string" && /^reports\/[\w./-]+$/.test(f.report) && !f.report.includes("..") ? f.report : "";
    out.push(el("article", { class: "card finding" },
      el("h3", {}, el("span", {}, f.title || "Untitled"),
        verdict && el("span", { class: "tag verdict " + verdict.toLowerCase().replace(/[^a-z]+/g, "-") }, verdict)),
      el("p", {}, f.summary || ""),
      report && el("a", { href: REPORT_BASE + report, rel: "noopener" }, "Read the report")));
  }
  return out;
}

// ---------------------------------------------------------------- footer + render

function footer() {
  const p = (...kids) => el("p", {}, ...kids);
  const lines = [];
  if (odds) {
    const fetched = ageText(odds.odds_fetched_at);
    const built = ageText(odds.generated_at);
    lines.push(p(`Odds fetched ${fetched || "at an unknown time"}` + (built ? ` · page built ${built}` : "")));
    const c = odds.credits && typeof odds.credits === "object" ? odds.credits : {};
    if (isNum(c.used_this_month) && isNum(c.month_cap)) lines.push(p(`Odds API credits this month: ${c.used_this_month} of ${c.month_cap}`));
    if (odds.ratings_through) lines.push(p(`Elo ratings use results through ${odds.ratings_through}`));
  }
  lines.push(p("Refreshes every 3 h, often late: GitHub delays scheduled runs."));
  lines.push(p("Match results for the Elo model: ",
    el("a", { href: "https://github.com/JeffSackmann", rel: "noopener" }, "Jeff Sackmann / Tennis Abstract"),
    ", licensed ", el("a", { href: "https://creativecommons.org/licenses/by-nc-sa/4.0/", rel: "noopener" }, "CC BY-NC-SA 4.0"),
    ". This page is non-commercial."));
  lines.push(p("Odds from DraftKings Sportsbook and Pinnacle via The Odds API. Not betting advice."));
  return lines;
}

function render() {
  $("banners").replaceChildren(...banners());
  $("view").replaceChildren(...(tab === "findings" ? findingsView() : matchesView()));
  $("footer").replaceChildren(...footer());
  const fetched = odds && ageText(odds.odds_fetched_at);
  $("updated").textContent = odds ? (fetched ? `Odds ${fetched}` : "Odds time unknown") : (oddsErr ? "No data" : "Loading…");
  for (const b of document.querySelectorAll(".tabbar button")) {
    const on = b.dataset.tab === tab;
    b.classList.toggle("active", on);
    if (on) b.setAttribute("aria-current", "page"); else b.removeAttribute("aria-current");
  }
}

async function getJson(url, force) {
  const r = await fetch(url, { cache: force ? "reload" : "no-cache" });
  if (!r.ok) throw new Error(r.status === 404 ? "file not found" : `HTTP ${r.status}`);
  try { return await r.json(); } catch { throw new Error("file is not valid JSON"); }
}

async function load(force = false) {
  const btn = $("refresh");
  btn.classList.add("spin");
  const [o, f] = await Promise.allSettled([getJson(ODDS_URL, force), getJson(FINDINGS_URL, force)]);
  if (o.status === "fulfilled" && o.value && typeof o.value === "object" && !Array.isArray(o.value)) {
    odds = o.value; oddsErr = "";
  } else {
    oddsErr = o.status === "rejected" ? `Couldn't load the odds: ${o.reason.message}` : "Couldn't read the odds file";
  }
  if (f.status === "fulfilled" && Array.isArray(f.value)) { findings = f.value; findingsErr = ""; }
  else findingsErr = f.status === "rejected" ? f.reason.message : "not a list";
  btn.classList.remove("spin");
  render();
}

for (const b of document.querySelectorAll(".tabbar button")) {
  b.addEventListener("click", () => {
    tab = b.dataset.tab;
    history.replaceState(null, "", tab === "findings" ? "#findings" : location.pathname + location.search);
    render();
    window.scrollTo(0, 0);
  });
}
$("refresh").addEventListener("click", () => load(true));
document.addEventListener("visibilitychange", () => { if (!document.hidden) load(); });
setInterval(render, 60000);   // keep ages and banners current while the page stays open
load();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}
