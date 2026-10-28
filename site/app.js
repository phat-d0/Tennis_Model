// Tennis Odds: a static page over data/odds.json (built every 3 h by GitHub Actions) and
// findings.json. No external requests; every bad state shows a banner and keeps the page usable.
"use strict";

const ODDS_URL = "data/odds.json";
const FINDINGS_URL = "findings.json";
const PORTFOLIO_URL = "data/portfolio.json";
const BACKTEST_URL = "portfolio_backtest.json";
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
const TABS = ["matches", "portfolio", "findings"];
let tab = TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "matches";
let portfolio = null;   // last good data/portfolio.json (paper trades, built every 3 h)
let portfolioErr = "";
let backtest = null;    // portfolio_backtest.json (static aggregates)
let pfStrategy = store.get("tennis-pf-strategy", "model");
let pfView = store.get("tennis-pf-view", "live");
let pfLevel = "home";   // Portfolio tab level: "home" (folders) → "portfolio" → "strategy"
let pfPort = "model";
let pfShown = 20;
let tour = store.get("tennis-tour", "all");
let level = store.get("tennis-level", "tour");      // "tour" (DraftKings/Pinnacle) or "challengers" (Polymarket)
let hideThin = store.get("tennis-hide-thin", false);

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

const objects = (xs) => (Array.isArray(xs) ? xs.filter((x) => x && typeof x === "object") : []);

function segmented(label, items, cur, onPick) {
  return el("div", { class: "segmented", role: "tablist", "aria-label": label },
    items.map(([k, name]) => el("button", {
      class: k === cur ? "on" : "", role: "tab", "aria-selected": String(k === cur), onclick: () => onPick(k),
    }, name)));
}

// ATP / WTA filter with counts; shared by the tour-level and Challenger lists.
function tourFilter(all) {
  const counts = { all: all.length, ATP: 0, WTA: 0 };
  for (const m of all) if (m.tour in counts) counts[m.tour] += 1;
  if (!(tour in counts)) tour = "all";
  const seg = segmented("Tour", ["all", "ATP", "WTA"].map((t) => [t, `${t === "all" ? "All" : t} (${counts[t]})`]), tour,
    (t) => { tour = t; store.set("tennis-tour", t); render(); });
  return [seg, tour === "all" ? all : all.filter((m) => m.tour === tour)];
}

function matchesView() {
  const ch = odds && odds.challengers && typeof odds.challengers === "object" ? odds.challengers : null;
  if (!ch) return tourLevelView([]);
  const nTour = objects(odds.matches).length, nCh = objects(ch.matches).length;
  if (level !== "challengers") level = "tour";
  const levels = segmented("Level", [["tour", `Tour-level (${nTour})`], ["challengers", `Challengers (${nCh})`]], level,
    (k) => { level = k; store.set("tennis-level", k); render(); window.scrollTo(0, 0); });
  levels.classList.add("levels");
  return level === "challengers" ? challengersView(ch, [levels]) : tourLevelView([levels]);
}

function tourLevelView(head) {
  const all = odds ? objects(odds.matches) : [];
  const [seg, shown] = tourFilter(all);
  head = [...head, seg];
  if (!shown.length) {
    const msg = !odds ? "No odds to show yet."
      : all.length ? `No ${tour} matches in the next 36 hours.`
      : "No matches with odds in the next 36 hours.";
    return [...head, el("div", { class: "card empty" }, msg)];
  }
  const out = [...head, ...grouped(shown, matchCard)];
  out.push(el("p", { class: "note" },
    "Decimal odds. Fair chance = the book's implied chance with its margin removed. The model (since 26 Oct 2026) blends a surface-weighted Elo rating with each player's recent serve and return points won. It has not beaten the market in any test, so treat it as context, not a tip."));
  return out;
}

// Group by tournament; tournaments ordered by their first start time, matches by start time.
function grouped(ms, card) {
  const byStart = (a, b) => (parseTs(a.commence_time) ?? Infinity) - (parseTs(b.commence_time) ?? Infinity);
  const groups = new Map();
  for (const m of [...ms].sort(byStart)) {
    const key = m.tournament || m.sport_key || "Other";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(m);
  }
  const out = [];
  for (const [name, list] of groups) {
    out.push(el("h2", { class: "section-title" }, el("span", {}, name),
      el("span", { class: "count" }, `${list.length} match${list.length === 1 ? "" : "es"}`)));
    for (const m of list) out.push(card(m));
  }
  return out;
}

// ---------------------------------------------------------------- challengers (Polymarket)
// Indicative peer order-book prices (dollars per share) from Polymarket international.
// A book is "thin" when a player's spread is over 5c, a best level holds under 20 shares,
// or a side is empty: those prices may not be there for any real size.

const THIN_SPREAD = 0.05;
const THIN_SIZE = 20;
const prob = (x) => (isNum(x) && x >= 0 && x <= 1 ? x : null);
const cents = (x) => (prob(x) === null ? na() : `${Math.round(x * 1000) / 10}¢`);
const shares = (x) => (isNum(x) && x >= 0 ? (x >= 1000 ? `${(x / 1000).toFixed(1)}k` : x.toFixed(0)) : "—");

function side(q) {
  q = q && typeof q === "object" ? q : {};
  const bid = prob(q.bid), ask = prob(q.ask);
  const spread = bid !== null && ask !== null ? ask - bid : null;
  return { bid, ask, spread, bidSize: q.bid_size, askSize: q.ask_size };
}

function thinReasons(a, b) {
  const why = new Set();
  for (const q of [a, b]) {
    if (q.bid === null || q.ask === null) why.add("one side empty");
    else if (q.spread > THIN_SPREAD + 1e-9) why.add(`spread over ${THIN_SPREAD * 100}¢`);
    for (const n of [q.bidSize, q.askSize]) if (q.bid !== null && q.ask !== null && !(isNum(n) && n >= THIN_SIZE)) why.add(`under ${THIN_SIZE} shares at best`);
  }
  return [...why];
}

function challengerCard(m) {
  const a = side(m.p1), b = side(m.p2);
  const thin = thinReasons(a, b);
  const model = prob(m.model_p1);
  const started = (parseTs(m.commence_time) ?? Infinity) <= Date.now();
  const priceCell = (p, n) => el("td", {}, cents(p), el("span", { class: "sub" }, p === null ? "" : `${shares(n)} sh`));
  const row = (name, q) => el("tr", {},
    el("td", {}, name || "?"), priceCell(q.bid, q.bidSize), priceCell(q.ask, q.askSize),
    el("td", { class: q.spread !== null && q.spread > THIN_SPREAD + 1e-9 ? "wide" : "" }, q.spread === null ? na() : cents(q.spread)));
  return el("article", { class: "card match ch" + (thin.length ? " thin" : "") },
    el("div", { class: "match-head" },
      el("span", {}, startText(m.commence_time)),
      el("span", {}, started ? el("span", { class: "tag warn" }, "Started") : null, " ",
        thin.length ? el("span", { class: "tag thin-tag", title: thin.join(", ") }, "Thin book") : null, " ",
        m.tier || m.tour || "")),
    el("table", { class: "odds book" },
      el("thead", {}, el("tr", {}, el("th", {}, "Player"), el("th", {}, "Bid"), el("th", {}, "Ask"), el("th", {}, "Spread"))),
      el("tbody", {}, row(m.player_1, a), row(m.player_2, b))),
    el("div", { class: "card-foot" },
      el("span", {}, "Model ", el("span", { class: "tag" }, "model: not proven"), " ",
        model === null ? "—" : `${pct(model)} / ${pct(1 - model)}`),
      thin.length ? el("span", {}, `Thin: ${thin.join(", ")}`) : null));
}

function challengersView(ch, head) {
  const out = [...head];
  const status = typeof ch.status === "string" ? ch.status : "missing";
  const add = (title, text, bad) => out.push(el("div", { class: "banner" + (bad ? " bad" : ""), role: "status" }, el("b", {}, title), text));
  out.push(el("div", { class: "banner info" }, el("b", {}, "Polymarket (international), indicative: not tradable from the US"),
    `Peer order-book prices per share, ${ageText(ch.fetched_at) ? `fetched ${ageText(ch.fetched_at)}` : "fetch time unknown"}. Size = shares at the best price; books are often only a few shares deep.`));
  if (status !== "ok") add("Challenger prices not updated", status.startsWith("error") ? "The last fetch failed. These are the last saved prices." : `Status "${status}".`, status.startsWith("error"));
  const fh = ageHours(ch.fetched_at);
  if (fh !== null && fh > STALE_ODDS_H) add("Old prices", `These prices were fetched ${ageText(ch.fetched_at)}.`, false);

  const all = objects(ch.matches);
  const [seg, byTour] = tourFilter(all);
  const thinCount = byTour.filter((m) => thinReasons(side(m.p1), side(m.p2)).length).length;
  out.push(seg);
  if (thinCount) {
    out.push(el("button", { class: "chip" + (hideThin ? " on" : ""), "aria-pressed": String(hideThin),
      onclick: () => { hideThin = !hideThin; store.set("tennis-hide-thin", hideThin); render(); } },
    hideThin ? `Showing ${byTour.length - thinCount} with usable books · show all ${byTour.length}` : `Hide ${thinCount} thin book${thinCount === 1 ? "" : "s"}`));
  }
  const shown = hideThin ? byTour.filter((m) => !thinReasons(side(m.p1), side(m.p2)).length) : byTour;
  if (!shown.length) {
    out.push(el("div", { class: "card empty" }, all.length ? "No matches with these filters." : "No Challenger or WTA 125 matches listed right now."));
    return out;
  }
  out.push(...grouped(shown, challengerCard));
  out.push(el("p", { class: "note" },
    "Bid = the best price someone will pay for a share that pays $1 if the player wins; ask = the best price to buy one. The spread is the cost of crossing the book. Polymarket international can't be traded from the US; these are shown only as an indicative line."));
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


// ---------------------------------------------------------------- portfolio tab
// Paper trades, $10 each, opened by upsets/portfolio.py at DraftKings' price. "Expected" is each
// trade's expected value at Pinnacle's fair chance when it was opened; realized minus expected
// is luck (or Pinnacle being wrong). Closing line value compares the entry odds with the fair
// chance at the last build before the start.

const money = (x, dp = 0) => {
  if (!isNum(x)) return "—";
  const s = Math.abs(x).toFixed(Math.abs(x) < 10 && dp === 0 ? 2 : dp);
  return (x < 0 ? "−$" : x > 0 ? "+$" : "$") + s;
};
const signed = (x, dp = 1) => (isNum(x) ? (x > 0 ? "+" : x < 0 ? "−" : "") + Math.abs(x * 100).toFixed(dp) + "%" : "—");
const sgnCls = (x) => (isNum(x) ? (x > 0 ? "pos" : x < 0 ? "neg" : "") : "");
const PF_SHORT = { model: "Elo model", line: "DK vs Pinnacle", dogs: "Underdogs",
  seed: "Seed loses early", seed_q: "Seed loses early (qualifiers)" };

function tile(label, value, sub, cls) {
  return el("div", { class: "tile" }, el("div", { class: "t-label" }, label),
    el("div", { class: "t-value num " + (cls || "") }, value), sub ? el("div", { class: "t-sub" }, sub) : null);
}

// Cumulative realized (solid) and expected (dashed) profit; drag or hover to read a point.
function pfChart(points, unit) {
  // only well-formed points reach the SVG markup (dates must be YYYY-MM-DD, values numbers)
  const ok = Array.isArray(points) ? points.filter((p) => p && /^\d{4}-\d{2}-\d{2}$/.test(p.date) && isNum(p.realized) && isNum(p.expected)) : [];
  if (!ok.length) return null;
  const pts = [{ date: null, realized: 0, expected: 0, n: 0 }, ...ok];
  const W = 340, H = 180, L = 46, R = 12, T = 12, B = 22;
  const ys = pts.flatMap((p) => [p.realized, p.expected]);
  const lo = Math.min(0, ...ys), hi = Math.max(0, ...ys), span = hi - lo || 1;
  const sx = (i) => L + (i / (pts.length - 1 || 1)) * (W - L - R);
  const sy = (v) => T + (1 - (v - lo) / span) * (H - T - B);
  const path = (k) => pts.map((p, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(p[k]).toFixed(1)}`).join(" ");
  const fmt = (v) => (unit === "u" ? `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}u` : money(v));
  const last = pts[pts.length - 1];
  const holder = document.createElement("div");
  // the HTML parser puts <svg> in the SVG namespace (no namespace URL needed)
  holder.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img"
    aria-label="Cumulative profit: realized ${fmt(last.realized)}, expected ${fmt(last.expected)}">
    <line class="c-zero" x1="${L}" x2="${W - R}" y1="${sy(0)}" y2="${sy(0)}"/>
    <text class="c-lab" x="${L - 4}" y="${sy(0) + 3}" text-anchor="end">0</text>
    ${hi > span * 0.15 ? `<text class="c-lab" x="${L - 4}" y="${sy(hi) + 3}" text-anchor="end">${fmt(hi)}</text>` : ""}
    ${lo < -span * 0.15 ? `<text class="c-lab" x="${L - 4}" y="${sy(lo) + 3}" text-anchor="end">${fmt(lo)}</text>` : ""}
    <path class="c-exp" d="${path("expected")}"/>
    <path class="c-real" d="${path("realized")}"/>
    <line class="c-cursor" x1="0" x2="0" y1="${T}" y2="${H - B}" style="display:none"/>
    <circle class="c-dot" r="4" style="display:none"/>
    <text class="c-lab" x="${L}" y="${H - 6}">${pts[1].date || ""}</text>
    <text class="c-lab" x="${W - R}" y="${H - 6}" text-anchor="end">${last.date || ""}</text></svg>`;
  const svg = holder.firstElementChild;
  const readout = el("div", { class: "c-readout", "aria-live": "polite" });
  const show = (i) => {
    const p = pts[i];
    readout.textContent = p.date === null ? "Start: 0"
      : `${p.date}: realized ${fmt(p.realized)}, expected ${fmt(p.expected)} (luck ${fmt(p.realized - p.expected)})`;
    const cur = svg.querySelector(".c-cursor"), dot = svg.querySelector(".c-dot");
    cur.setAttribute("x1", sx(i)); cur.setAttribute("x2", sx(i)); cur.style.display = "";
    dot.setAttribute("cx", sx(i)); dot.setAttribute("cy", sy(p.realized)); dot.style.display = "";
  };
  const at = (ev) => {
    const r = svg.getBoundingClientRect();
    const x = ((ev.clientX - r.left) / (r.width || 1)) * W;
    return Math.max(0, Math.min(pts.length - 1, Math.round(((x - L) / (W - L - R)) * (pts.length - 1))));
  };
  svg.addEventListener("pointermove", (ev) => show(at(ev)));
  svg.addEventListener("pointerdown", (ev) => show(at(ev)));
  const wrap = el("div", { class: "chart", tabindex: "0", role: "slider", "aria-label": "Move along the profit lines",
    "aria-valuemin": "0", "aria-valuemax": String(pts.length - 1) });
  let cur = pts.length - 1;
  wrap.addEventListener("keydown", (ev) => {
    if (ev.key === "ArrowLeft" || ev.key === "ArrowRight") {
      cur = Math.max(0, Math.min(pts.length - 1, cur + (ev.key === "ArrowRight" ? 1 : -1)));
      show(cur); ev.preventDefault();
    }
  });
  wrap.append(svg, el("div", { class: "c-legend" },
    el("span", { class: "k-real" }, "Realized"), el("span", { class: "k-exp" }, "Expected at Pinnacle's fair price")), readout);
  show(pts.length - 1);
  return wrap;
}

function currentOdds(t) {
  const m = (odds?.matches || []).find((x) => x && x.event_id === t.event_id);
  const v = m?.draftkings?.[`odds_${t.side}`];
  return isNum(v) ? v : null;
}

function tradeRow(t) {
  const open = t.status === "open";
  const right = open
    ? el("span", { class: "r-val" }, el("b", {}, `$${(t.stake || 10).toFixed(0)}`), el("small", {}, `to win $${((t.stake || 10) * (t.odds - 1)).toFixed(2)}`))
    : t.status === "void" ? el("span", { class: "r-val" }, el("b", {}, "Void"), el("small", {}, "stake back"))
    : el("span", { class: "r-val" }, el("b", { class: sgnCls(t.profit) }, money(t.profit, 2)), el("small", {}, t.status));
  const now = open ? currentOdds(t) : null;
  const bits = [isNum(t.odds) ? `@ ${t.odds.toFixed(2)}` : "@ —"];
  if (isNum(t.ev)) bits.push(`EV ${signed(t.ev)}`);
  if (open && isNum(now) && now !== t.odds) bits.push(`now ${now.toFixed(2)}`);
  if (isNum(t.clv)) bits.push(`CLV ${signed(t.clv)}${open ? " so far" : ""}`);
  if (t.score) bits.push(t.score);
  return el("div", { class: "trade" },
    el("span", { class: "r-who" }, el("b", {}, t.player || "?"),
      el("span", { class: "meta" }, `v ${t.opponent || "?"} · ${t.tournament || ""} · ${startText(t.commence_time)}`),
      el("span", { class: "meta num" }, bits.join(" · "))),
    right);
}

function liveView(s) {
  const out = [];
  const sum = s.summary || {};
  const trades = Array.isArray(s.trades) ? s.trades.filter((t) => t && typeof t === "object") : [];
  if (!trades.length) {
    const list = (portfolio?.scored_tournaments || []).join(", ");
    out.push(el("div", { class: "card empty" },
      el("p", {}, "No paper trades yet."),
      el("p", { class: "note" }, `Trades open only in tournaments The Odds API reports results for${list ? `: ${list}` : ""}. None of them is running right now; the Backtest view shows how this rule did on past seasons.`)));
    return out;
  }
  const se = isNum(sum.roi_se) ? `± ${(sum.roi_se * 100).toFixed(1)}%` : "per dollar staked";
  out.push(el("div", { class: "tiles" },
    tile("Realized profit", money(sum.profit), isNum(sum.staked) ? `on $${sum.staked.toFixed(0)} staked` : "nothing settled yet", sgnCls(sum.profit)),
    tile("Expected profit", money(sum.expected), "at Pinnacle's fair price", sgnCls(sum.expected)),
    tile("Realized − expected", money(sum.luck), "luck, or Pinnacle wrong", sgnCls(sum.luck)),
    tile("ROI", signed(sum.roi), isNum(sum.expected_roi) ? `expected ${signed(sum.expected_roi)} · ${se}` : se, sgnCls(sum.roi)),
    tile("Closing line value", signed(sum.clv), isNum(sum.beat_close) ? `beat the close ${pct(sum.beat_close)}` : "vs the last price before the start", sgnCls(sum.clv)),
    tile("Win rate", pct(sum.win_rate), isNum(sum.expected_win_rate) ? `expected ${pct(sum.expected_win_rate)}` : ""),
    tile("Trades", String(sum.trades || 0), `${sum.open || 0} open · ${sum.settled || 0} settled${sum.void ? ` · ${sum.void} void` : ""}`),
    tile("Max drawdown", isNum(sum.max_drawdown) ? `$${sum.max_drawdown.toFixed(0)}` : "—", "peak to trough")));
  const chart = pfChart(s.curve, "$");
  if (chart) out.push(el("div", { class: "card" }, chart));
  const open = trades.filter((t) => t.status === "open");
  const done = trades.filter((t) => t.status !== "open");
  if (open.length) {
    out.push(el("h2", { class: "section-title" }, el("span", {}, "Open"), el("span", { class: "count" }, `${open.length}`)));
    out.push(el("div", { class: "card list" }, open.map(tradeRow)));
  }
  if (done.length) {
    out.push(el("h2", { class: "section-title" }, el("span", {}, "Settled"), el("span", { class: "count" }, `${done.length}`)));
    out.push(el("div", { class: "card list" }, done.slice(0, pfShown).map(tradeRow)));
    if (done.length > pfShown) {
      out.push(el("button", { class: "more", onclick: () => { pfShown += 40; render(); } }, `Show more (${done.length - pfShown} left)`));
    }
  }
  out.push(el("p", { class: "note" },
    "EV = DraftKings odds × fair chance − 1 when the trade opened. CLV uses the fair chance at the last build before the start (builds run every 3 h, so a close can be a few hours early). Results come from The Odds API; a match without a result after 4 days is void."));
  return out;
}

function backtestView(id) {
  const b = backtest && typeof backtest === "object" ? backtest.strategies?.[id] : null;
  if (!b) return [el("div", { class: "card empty" }, backtest ? "No backtest for this strategy." : "Backtest unavailable.")];
  const ci = Array.isArray(b.roi_ci) ? `95% CI ${signed(b.roi_ci[0])} to ${signed(b.roi_ci[1])}` : "";
  return [
    el("div", { class: "tiles" },
      tile("Bets", (b.bets || 0).toLocaleString(), b.period || ""),
      tile("Realized ROI", signed(b.roi), ci, sgnCls(b.roi)),
      tile("Expected ROI", signed(b.expected_roi), "at Pinnacle's fair price", sgnCls(b.expected_roi)),
      tile("Realized − expected", isNum(b.luck_units) ? `${b.luck_units > 0 ? "+" : ""}${b.luck_units.toFixed(1)}u` : "—", "units of $10", sgnCls(b.luck_units))),
    el("div", { class: "card" }, pfChart(b.curve, "u") || el("p", { class: "muted" }, "No curve.")),
    el("p", { class: "note" }, backtest.note || ""),
  ];
}

// Portfolio tab: portfolios listed like folders (home) → a portfolio's strategies → one strategy's
// Live paper / Backtest. Tapping the Portfolio tab again returns home.
const PF_FOLDERS = [
  { id: "model", name: "Elo model", about: "The page's Elo + serve/return model sees value at DraftKings.", strategies: ["model"] },
  { id: "line", name: "DK vs Pinnacle", about: "Line shopping: DraftKings pays more than Pinnacle's fair price.", strategies: ["line"] },
  { id: "dogs", name: "Underdogs", about: "The longer DraftKings price in every match; a baseline.", strategies: ["dogs"] },
  { id: "seed", name: "Seed loses early", about: "Rounds 1–2: the unseeded player against a seed.", strategies: ["seed", "seed_q"] },
];
const PF_INNER = { seed: "All seeded matches", seed_q: "Qualifiers and lucky losers" };

function pfStrategies() {
  return portfolio && Array.isArray(portfolio.strategies) ? portfolio.strategies.filter((s) => s && s.id) : [];
}

function pfFolders() {
  // Every strategy in portfolio.json or the backtest stays reachable; an unknown one gets its own folder.
  const ids = [...pfStrategies().map((s) => s.id), ...Object.keys(backtest?.strategies || {})];
  const known = new Set(PF_FOLDERS.flatMap((f) => f.strategies));
  const extra = [...new Set(ids.filter((k) => !known.has(k)))]
    .map((k) => ({ id: k, name: PF_SHORT[k] || k, about: "", strategies: [k] }));
  return [...PF_FOLDERS, ...extra];
}

function goPf(level, port, strat) {
  pfLevel = level;
  if (port) pfPort = port;
  if (strat) { pfStrategy = strat; store.set("tennis-pf-strategy", strat); }
  pfShown = 20;
  render();
  window.scrollTo(0, 0);
}

function btLine(id) {
  const b = backtest?.strategies?.[id];
  return b && isNum(b.roi) ? `Backtest ${signed(b.roi)} ROI on ${(b.bets || 0).toLocaleString()} bets` : "No backtest";
}

function liveVals(list) {
  // Realized profit over the live strategies in `list`; "" when none of them has a trade.
  const sums = list.map((s) => s?.summary || {});
  const trades = sums.reduce((n, x) => n + (x.trades || 0), 0);
  if (!trades) return [el("b", { class: "muted" }, "—"), el("small", {}, portfolio ? "no trades yet" : "no live data")];
  const profit = sums.reduce((n, x) => n + (isNum(x.profit) ? x.profit : 0), 0);
  const open = sums.reduce((n, x) => n + (x.open || 0), 0);
  return [el("b", { class: sgnCls(profit) }, money(profit)), el("small", {}, `${trades} trade${trades === 1 ? "" : "s"}${open ? ` · ${open} open` : ""}`)];
}

function folderRow(attrs, name, meta, bt, vals) {
  return el("button", { class: "row-btn folder", ...attrs },
    el("span", { class: "who" }, el("b", {}, name), " ", el("span", { class: "tag warn" }, "not proven"),
      meta ? el("span", { class: "meta" }, meta) : null, el("span", { class: "bt" }, bt)),
    el("span", { class: "vals" }, ...vals),
    el("span", { class: "chev", "aria-hidden": "true" }, "›"));
}

function crumbs(folder, strat) {
  const kids = [el("button", { class: "crumb", "data-pfnav": "home", onclick: () => goPf("home") }, "‹ Portfolios")];
  if (strat && folder.strategies.length > 1) {
    kids.push(el("span", { class: "crumb-sep" }, "/"),
      el("button", { class: "crumb", "data-pfnav": "portfolio", onclick: () => goPf("portfolio", folder.id) }, folder.name));
  }
  return el("nav", { class: "crumbs", "aria-label": "Portfolio path" }, kids);
}

function pfHome() {
  const live = pfStrategies();
  const rows = pfFolders().map((f) => {
    const ss = f.strategies.map((k) => live.find((s) => s.id === k)).filter(Boolean);
    const n = f.strategies.length;
    return folderRow({ "data-pfid": f.id, onclick: () => (n > 1 ? goPf("portfolio", f.id) : goPf("strategy", f.id, f.strategies[0])) },
      f.name, f.about + (n > 1 ? ` ${n} strategies.` : ""), btLine(f.strategies[0]), liveVals(ss));
  });
  const out = [el("h2", { class: "section-title" }, el("span", {}, "Portfolios"), el("span", { class: "count" }, "hypothetical $10 paper bets")),
    el("div", { class: "card list folders" }, rows)];
  if (!portfolio) out.push(el("p", { class: "note" }, portfolioErr ? `Paper trades unavailable (${portfolioErr}). The first build with the portfolio may not have run yet.` : "Loading paper trades…"));
  out.push(el("p", { class: "note" }, "Every strategy here is a hypothesis being tracked, not a proven edge. Tap one for its live paper trades and its backtest."));
  return out;
}

function pfPortfolio(folder) {
  const live = pfStrategies();
  const rows = folder.strategies.map((k) => {
    const s = live.find((x) => x.id === k);
    const rule = s?.rule || backtest?.strategies?.[k]?.rule || "";
    return folderRow({ "data-pfstrat": k, onclick: () => goPf("strategy", folder.id, k) },
      PF_INNER[k] || PF_SHORT[k] || k, rule, btLine(k), liveVals(s ? [s] : []));
  });
  return [crumbs(folder), el("h1", { class: "pf-title" }, folder.name), el("p", { class: "pf-sub" }, folder.about),
    el("div", { class: "card list folders" }, rows)];
}

function pfStrategyView(folder, id) {
  const s = pfStrategies().find((x) => x.id === id);
  const rule = s?.rule || backtest?.strategies?.[id]?.rule || "";
  const title = folder.strategies.length > 1 ? `${folder.name}: ${PF_INNER[id] || id}` : folder.name;
  const seg = el("div", { class: "segmented", role: "tablist", "aria-label": "View" },
    [["live", "Live paper trades"], ["backtest", "Backtest"]].map(([k, name]) => el("button",
      { class: k === pfView ? "on" : "", role: "tab", "aria-selected": String(k === pfView),
        onclick: () => { pfView = k; store.set("tennis-pf-view", k); render(); } }, name)));
  const out = [crumbs(folder, id), el("h1", { class: "pf-title" }, title)];
  if (s?.name && s.name !== title) out.push(el("p", { class: "pf-sub" }, s.name));
  if (rule) out.push(el("div", { class: "card rule" }, el("span", { class: "tag warn" }, "not proven"), " ", rule));
  out.push(seg);
  if (pfView === "backtest") return [...out, ...backtestView(id)];
  if (!portfolio) {
    out.push(el("div", { class: "card empty" }, portfolioErr ? `Paper trades unavailable (${portfolioErr}). The first build with the portfolio may not have run yet.` : "Loading…"));
    return out;
  }
  return [...out, ...liveView(s || { trades: [] })];
}

function portfolioView() {
  const folders = pfFolders();
  const folder = folders.find((f) => f.id === pfPort) || folders[0];
  if (pfLevel === "strategy" && folder.strategies.includes(pfStrategy)) return pfStrategyView(folder, pfStrategy);
  if (pfLevel !== "home" && folder.strategies.length > 1) return pfPortfolio(folder);
  pfLevel = "home";
  return pfHome();
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
  lines.push(p("Seeds and qualifiers for the \u2018Seed loses early\u2019 strategies: ",
    el("a", { href: "https://en.wikipedia.org", rel: "noopener" }, "Wikipedia"),
    " (", el("a", { href: "https://creativecommons.org/licenses/by-sa/4.0/", rel: "noopener" }, "CC BY-SA"), ")."));
  if (odds && odds.challengers && typeof odds.challengers === "object") {
    lines.push(p("Challenger and WTA 125 prices: Polymarket (international) public order books, indicative only, not tradable from the US."));
  }
  return lines;
}

function render() {
  $("banners").replaceChildren(...banners());
  $("view").replaceChildren(...(tab === "findings" ? findingsView() : tab === "portfolio" ? portfolioView() : matchesView()));
  $("view").dataset.level = tab === "portfolio" ? pfLevel : "";
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
  const [o, f, pf, bt] = await Promise.allSettled([getJson(ODDS_URL, force), getJson(FINDINGS_URL, force),
    getJson(PORTFOLIO_URL, force), getJson(BACKTEST_URL, force)]);
  if (pf.status === "fulfilled" && pf.value && typeof pf.value === "object" && !Array.isArray(pf.value)) { portfolio = pf.value; portfolioErr = ""; }
  else portfolioErr = pf.status === "rejected" ? pf.reason.message : "not an object";
  if (bt.status === "fulfilled" && bt.value && typeof bt.value === "object") backtest = bt.value;
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
    if (b.dataset.tab === "portfolio" && tab === "portfolio") pfLevel = "home";   // tapping it again goes home
    tab = b.dataset.tab;
    history.replaceState(null, "", tab === "matches" ? location.pathname + location.search : `#${tab}`);
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
