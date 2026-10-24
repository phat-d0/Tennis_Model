// Read-only dashboard: polls /state.json (written by the scanner) and renders it.
// No venue API calls and no order placement from the browser.
"use strict";

const STALE_FACTOR = 3;          // stale when older than 3 x poll_seconds
const DEFAULT_POLL_S = 5;
const MAX_POLL_S = 30;

let state = null;                // last good state
let lastFetchOk = false;
let lastError = "";
let timer = null;

const $ = (id) => document.getElementById(id);

function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") n.className = v;
    else n.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    n.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return n;
}

const isNum = (x) => typeof x === "number" && Number.isFinite(x);

// 0.427 -> "42.7¢"; dollars stay dollars in the data, cents only on screen.
function centsText(p) {
  if (!isNum(p)) return "—";
  const c = p * 100;
  return (Math.abs(c - Math.round(c)) < 1e-9 ? c.toFixed(0) : c.toFixed(1)) + "¢";
}
const cents = (p) => (isNum(p) ? centsText(p) : el("span", { class: "na" }, "—"));
function money(x, signed = true) {
  if (!isNum(x)) return el("span", { class: "na" }, "—");
  const s = "$" + Math.abs(x).toFixed(2);
  if (!signed) return s;
  const txt = (x > 0.004 ? "+" : x < -0.004 ? "−" : "") + s;
  return el("span", { class: x > 0.004 ? "pos" : x < -0.004 ? "neg" : "" }, txt);
}
function qty(x) {
  if (!isNum(x)) return "—";
  return Number.isInteger(x) ? String(x) : x.toFixed(2).replace(/\.?0+$/, "");
}
function parseTs(ts) {
  const t = Date.parse(ts || "");
  return Number.isFinite(t) ? t : null;
}
function fmtTime(ts) {
  const t = parseTs(ts);
  if (t === null) return "—";
  return new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}
function fmtAge(ms) {
  if (ms < -5000) return "in the future";
  const s = Math.max(0, Math.round(ms / 1000));   // small clock skew reads as "0s ago"
  if (s < 90) return s + "s ago";
  const m = Math.round(s / 60);
  if (m < 90) return m + "m ago";
  const h = Math.round(m / 60);
  if (h < 48) return h + "h ago";
  return Math.round(h / 24) + "d ago";
}
function pollSeconds() {
  const p = state && state.poll_seconds;
  return isNum(p) && p > 0 ? p : DEFAULT_POLL_S;
}

// ---------------------------------------------------------------- status

function renderStatus() {
  const pill = $("status"), banner = $("banner"), stamp = $("stamp");
  const gen = state ? parseTs(state.generated_at) : null;
  const age = gen === null ? null : Date.now() - gen;
  const limitMs = STALE_FACTOR * pollSeconds() * 1000;
  // A time well in the future means a clock is wrong, so the age can't be trusted either.
  const future = age !== null && age < -limitMs;
  const stale = state !== null && (age === null || age > limitMs || future);

  stamp.textContent = gen === null
    ? (state ? "Data time missing" : "No data yet")
    : `Data ${fmtTime(state.generated_at)} · ${fmtAge(age)}`;
  if (gen !== null) stamp.title = new Date(gen).toISOString();

  let cls = "ok", label = "Live", msg = "";
  if (!lastFetchOk) {
    cls = "down"; label = "Offline";
    msg = state
      ? `Can't load state.json (${lastError}). Showing the last data received.`
      : `Can't load state.json (${lastError}).`;
  } else if (stale) {
    cls = "stale"; label = "Stale";
    msg = age === null
      ? "Stale data: state.json has no valid generated_at time."
      : future
      ? `Data time ${new Date(gen).toISOString()} is in the future: check the scanner's and this device's clocks.`
      : `Stale data: last update ${fmtAge(age)}, expected every ${pollSeconds()}s. Is the scanner running? Prices below may be out of date.`;
  }
  pill.className = "pill " + cls;
  pill.textContent = label;
  banner.hidden = !msg;
  banner.className = "banner" + (cls === "down" ? " down" : "");
  banner.textContent = msg;
  document.body.dataset.status = cls;
}

// ---------------------------------------------------------------- tables

function profitableLocks(s) {
  const ids = new Set();
  for (const p of s.positions || []) {
    if (p.lock && isNum(p.lock.locked_pnl) && p.lock.locked_pnl > 0) ids.add(p.match_id);
  }
  return ids;
}
const isArb = (m) => isNum(m.arb_profit) && m.arb_profit > 0;

const PHASE_ORDER = { live: 0, pre: 1, unknown: 2 };
const SORTS = {
  cwf: (a, b) => nullLast(a.combined_with_fees, b.combined_with_fees),
  combined: (a, b) => nullLast(a.combined, b.combined),
  arb: (a, b) => nullLast(b.arb_profit, a.arb_profit, true) || nullLast(a.combined_with_fees, b.combined_with_fees),
  tier: (a, b) => String(a.tier || "").localeCompare(String(b.tier || "")) || nullLast(a.combined_with_fees, b.combined_with_fees),
  phase: (a, b) => (PHASE_ORDER[a.phase] ?? 3) - (PHASE_ORDER[b.phase] ?? 3) || nullLast(a.combined_with_fees, b.combined_with_fees),
};
function nullLast(x, y, swapped = false) {
  const nx = !isNum(x), ny = !isNum(y);
  if (nx && ny) return 0;
  if (nx) return swapped ? -1 : 1;
  if (ny) return swapped ? 1 : -1;
  return x - y;
}

function phaseBadge(phase) {
  const p = phase || "unknown";
  return el("span", { class: "badge" + (p === "live" ? " live" : "") }, p);
}
function matchCell(m) {
  return el("td", { class: "match" },
    el("div", { class: "players" }, `${m.player_a || "?"} vs ${m.player_b || "?"}`),
    el("div", { class: "sub" }, m.tier || m.series || "", m.phase !== null && phaseBadge(m.phase), m.badges || []));
}
// Cell content sits in one span so the phone card layout keeps label and value as two flex items.
const td = (label, ...kids) => el("td", { class: "num", "data-label": label }, el("span", {}, ...kids));

function renderMarkets(s) {
  const body = $("markets");
  const locks = profitableLocks(s);
  const rows = [...(s.matches || [])].sort(SORTS[$("sort").value] || SORTS.cwf);
  body.replaceChildren();
  if (!rows.length) {
    body.append(el("tr", {}, el("td", { colspan: 7, class: "empty" }, "No markets in state.json.")));
    return;
  }
  for (const m of rows) {
    const arb = isArb(m), lock = locks.has(m.match_id);
    const badges = [arb && el("span", { class: "badge arb" }, "arb"), lock && el("span", { class: "badge lock" }, "lock")];
    const cwf = m.combined_with_fees;
    body.append(el("tr", { class: arb ? "hot-arb" : lock ? "hot-lock" : "" },
      matchCell({ ...m, badges }),
      td("Ask " + (m.player_a || "A"), cents(m.ask_a)),
      td("Ask " + (m.player_b || "B"), cents(m.ask_b)),
      td("Depth A / B", `${qty(m.size_a)} / ${qty(m.size_b)}`),
      td("Combined", cents(m.combined)),
      td("Combined + fees", isNum(cwf) ? el("span", { class: cwf < 1 ? "pos" : "" }, cents(cwf)) : cents(cwf)),
      td("Arb", arb ? [qty(m.arb_contracts) + " ct · ", money(m.arb_profit)] : el("span", { class: "na" }, "—"))));
  }
}

function held(c, avg) {
  return isNum(c) && c > 0 ? `${qty(c)} @ ${centsText(avg)}` : el("span", { class: "na" }, "—");
}

function renderPositions(s) {
  const body = $("positions");
  const byId = new Map((s.matches || []).map((m) => [m.match_id, m]));
  const rows = [...(s.positions || [])].sort((a, b) =>
    nullLast(b.lock ? b.lock.locked_pnl : null, a.lock ? a.lock.locked_pnl : null, true));
  body.replaceChildren();
  if (!rows.length) {
    body.append(el("tr", {}, el("td", { colspan: 8, class: "empty" }, "No positions.")));
    return;
  }
  for (const p of rows) {
    const L = p.lock;
    const hot = L && isNum(L.locked_pnl) && L.locked_pnl > 0;
    const sideName = L ? (L.side_to_buy === "A" ? p.player_a : p.player_b) || L.side_to_buy : "";
    const buy = L
      ? [`${qty(L.contracts_to_buy)} ${sideName} @ ${centsText(L.ask)}`,
         L.depth_ok === false ? el("div", { class: "flag" }, "not enough depth") : null]
      : el("span", { class: "na" }, "balanced");
    body.append(el("tr", { class: hot ? "hot-lock" : "" },
      matchCell({ player_a: p.player_a, player_b: p.player_b, tier: p.match_id,
                  phase: (byId.get(p.match_id) || {}).phase ?? null,
                  badges: hot ? [el("span", { class: "badge lock" }, "lock")] : [] }),
      td("Held " + (p.player_a || "A"), held(p.contracts_a, p.avg_a)),
      td("Held " + (p.player_b || "B"), held(p.contracts_b, p.avg_b)),
      td("P&L if " + (p.player_a || "A") + " wins", money(p.pnl_if_a)),
      td("P&L if " + (p.player_b || "B") + " wins", money(p.pnl_if_b)),
      td("Contracts to buy", buy),
      td("Cost", L ? money(L.cost, false) : el("span", { class: "na" }, "—")),
      td("Locked P&L", L ? money(L.locked_pnl) : el("span", { class: "na" }, "—"))));
  }
}

function renderAlerts(s) {
  const list = $("alerts");
  const rows = [...(s.alerts || [])].sort((a, b) => (parseTs(b.ts) ?? 0) - (parseTs(a.ts) ?? 0));
  list.replaceChildren();
  if (!rows.length) {
    list.append(el("li", { class: "empty" }, "No alerts."));
    return;
  }
  for (const a of rows) {
    const type = ["arb", "lock", "cross_venue"].includes(a.type) ? a.type : "";
    list.append(el("li", {},
      el("div", { class: "a-top" },
        el("span", { class: "badge " + type }, (a.type || "alert").replace("_", " ")),
        el("time", { datetime: a.ts || "" }, fmtTime(a.ts)),
        el("span", {}, a.match_id || "")),
      el("div", { class: "a-msg" }, a.message || ""),
      el("div", { class: "a-nums" },
        `${qty(a.contracts)} contracts · cost `, money(a.cost, false), " · locked ", money(a.locked_pnl))));
  }
}

function renderSummary(s) {
  const arbs = (s.matches || []).filter(isArb).length;
  const locks = profitableLocks(s).size;
  const live = (s.matches || []).filter((m) => m.phase === "live").length;
  const tile = (k, v, hot) => el("div", { class: "tile" + (hot ? " hot" : "") },
    el("div", { class: "k" }, k), el("div", { class: "v" }, String(v)));
  $("summary").replaceChildren(
    tile("Markets", `${(s.matches || []).length}`),
    tile("Live now", live),
    tile("Arbs open", arbs, arbs > 0),
    tile("Locks available", locks, locks > 0));
}

function render() {
  if (state) {
    $("venue").textContent = state.venue ? "· " + state.venue + " tennis" : "";
    renderSummary(state);
    renderAlerts(state);
    renderMarkets(state);
    renderPositions(state);
  }
  renderStatus();
}

// ---------------------------------------------------------------- polling

async function poll() {
  try {
    const r = await fetch("state.json", { cache: "no-store" });
    if (!r.ok) {
      let detail = "HTTP " + r.status;
      try { const j = await r.json(); if (j && j.error) detail = j.error; } catch (_) { /* keep status */ }
      throw new Error(detail);
    }
    const s = await r.json();
    if (!s || typeof s !== "object" || Array.isArray(s)) throw new Error("not a state object");
    state = s;
    lastFetchOk = true;
  } catch (e) {
    lastFetchOk = false;
    lastError = e && e.message ? e.message : "network error";
  }
  render();
  clearTimeout(timer);
  timer = setTimeout(poll, Math.min(pollSeconds(), MAX_POLL_S) * 1000);
}

// ---------------------------------------------------------------- theme

function applyTheme(v) {
  if (v === "light" || v === "dark") document.documentElement.dataset.theme = v;
  else delete document.documentElement.dataset.theme;
}
(function initTheme() {
  let v = "auto";
  try { v = localStorage.getItem("swinglock-theme") || "auto"; } catch (_) { /* storage blocked */ }
  $("theme").value = v;
  applyTheme(v);
  $("theme").addEventListener("change", (e) => {
    applyTheme(e.target.value);
    try { localStorage.setItem("swinglock-theme", e.target.value); } catch (_) { /* ignore */ }
  });
})();

$("sort").addEventListener("change", render);
setInterval(renderStatus, 1000);   // keep the age and stale warning ticking between polls
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
poll();
