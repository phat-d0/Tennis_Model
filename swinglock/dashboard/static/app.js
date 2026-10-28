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
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);   // CSP: no inline handlers
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
function fmtDate(ts) {
  const t = parseTs(ts);
  return t === null ? "—" : new Date(t).toLocaleDateString([], { month: "short", day: "numeric" });
}
function fmtDateTime(ts) {
  const t = parseTs(ts);
  if (t === null) return "—";
  return `${fmtDate(ts)} ${new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
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
// An arb counts as open only when its profit per contract clears the scanner's alert threshold
// (state.min_arb_profit_per_contract if the scanner sends it, else config.yaml's default).
// A positive profit below it rounds to about $0.00 at real size: shown as "break-even".
const DEFAULT_MIN_ARB = 0.005;   // config.yaml scanner.min_arb_profit_per_contract
function minArb() {
  const v = state && state.min_arb_profit_per_contract;
  return isNum(v) && v >= 0 ? v : DEFAULT_MIN_ARB;
}
const arbEdge = (m) => (isNum(m.arb_profit) && m.arb_profit > 0 && isNum(m.arb_contracts) && m.arb_contracts > 0
  ? m.arb_profit / m.arb_contracts : null);
const isArb = (m) => { const e = arbEdge(m); return e !== null && e >= minArb() - 1e-12; };
const isBreakEven = (m) => arbEdge(m) !== null && !isArb(m);

// Scanner's `tier` lumps ATP Challenger and WTA 125 together as "challenger"; label from the series.
const SERIES_LABEL = {
  KXATPMATCH: "ATP", KXWTAMATCH: "WTA", KXATPCHALLENGERMATCH: "ATP Challenger",
  KXWTACHALLENGERMATCH: "WTA 125", KXITFMATCH: "ITF Men", KXITFWMATCH: "ITF Women",
};
const tierLabel = (m) => SERIES_LABEL[m.series] || m.tier || m.series || "";

const PHASE_ORDER = { live: 0, pre: 1, unknown: 2 };
const SORTS = {
  cwf: (a, b) => nullLast(a.combined_with_fees, b.combined_with_fees),
  combined: (a, b) => nullLast(a.combined, b.combined),
  arb: (a, b) => nullLast(b.arb_profit, a.arb_profit, true) || nullLast(a.combined_with_fees, b.combined_with_fees),
  tier: (a, b) => tierLabel(a).localeCompare(tierLabel(b)) || nullLast(a.combined_with_fees, b.combined_with_fees),
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
    el("div", { class: "sub" }, m.label ?? tierLabel(m), m.phase !== null && phaseBadge(m.phase), m.badges || []));
}
// Cell content sits in one span so the phone card layout keeps label and value as two flex items.
const td = (label, ...kids) => el("td", { class: "num", "data-label": label }, el("span", {}, ...kids));

const hasBothAsks = (m) => isNum(m.ask_a) && isNum(m.ask_b);

function matchesFilter(m, q, phase) {
  if (phase !== "all" && (m.phase || "unknown") !== phase) return false;
  if (!q) return true;
  const hay = [m.player_a, m.player_b, tierLabel(m), m.tier, m.series, m.match_id].join(" ").toLowerCase();
  return q.split(/\s+/).every((w) => hay.includes(w));
}

// Phase options carry live counts; any phase value outside the contract still gets an option.
function syncPhaseOptions(all) {
  const sel = $("phase");
  const counts = { all: all.length };
  for (const m of all) { const p = m.phase || "unknown"; counts[p] = (counts[p] || 0) + 1; }
  for (const p of Object.keys(counts)) {
    if (![...sel.options].some((o) => o.value === p)) sel.append(el("option", { value: p }, p));
  }
  for (const o of sel.options) {
    o.textContent = `${o.dataset.label || (o.dataset.label = o.textContent)} (${counts[o.value] || 0})`;
  }
}

function renderMarkets(s) {
  const body = $("markets");
  const locks = profitableLocks(s);
  const all = s.matches || [];
  syncPhaseOptions(all);
  const q = $("q").value.trim().toLowerCase();
  const shown = all.filter((m) => matchesFilter(m, q, $("phase").value));
  const rows = shown.filter(hasBothAsks).sort(SORTS[$("sort").value] || SORTS.cwf);
  const noMarket = shown.filter((m) => !hasBothAsks(m))
    .sort((a, b) => `${a.player_a} ${a.player_b}`.localeCompare(`${b.player_a} ${b.player_b}`));

  $("m-count").textContent = shown.length === all.length
    ? `${all.length} matches`
    : `${shown.length} of ${all.length} matches`;

  body.replaceChildren();
  if (!rows.length) {
    const msg = !all.length ? "No markets in state.json."
      : shown.length ? "No match has asks on both sides." : "No markets match the filter.";
    body.append(el("tr", {}, el("td", { colspan: 7, class: "empty" }, msg)));
  }
  for (const m of rows) {
    const arb = isArb(m), even = isBreakEven(m), lock = locks.has(m.match_id);
    const badges = [arb && el("span", { class: "badge arb" }, "arb"),
      even && el("span", { class: "badge", title: `under ${(minArb() * 100).toFixed(1)}¢ per contract after fees` }, "break-even"),
      lock && el("span", { class: "badge lock" }, "lock")];
    const cwf = m.combined_with_fees;
    body.append(el("tr", { class: arb ? "hot-arb" : lock ? "hot-lock" : "" },
      matchCell({ ...m, badges }),
      td("Ask " + (m.player_a || "A"), cents(m.ask_a)),
      td("Ask " + (m.player_b || "B"), cents(m.ask_b)),
      td("Depth A / B", `${qty(m.size_a)} / ${qty(m.size_b)}`),
      td("Combined", cents(m.combined)),
      td("Combined + fees", isNum(cwf) ? el("span", { class: arb ? "pos" : "" }, cents(cwf)) : cents(cwf)),
      td("Arb", arb ? [qty(m.arb_contracts) + " ct · ", money(m.arb_profit)]
        : even ? el("span", { class: "na" }, `${qty(m.arb_contracts)} ct · $${m.arb_profit.toFixed(2)}`)
        : el("span", { class: "na" }, "—"))));
  }

  // Matches missing an ask on a side (often ended, suspended or not yet listed): one collapsed group.
  $("nomarket").hidden = !noMarket.length;
  $("nomarket-sum").textContent = `No market: ${noMarket.length} match${noMarket.length === 1 ? "" : "es"} without an ask on both sides`;
  $("nomarket-list").replaceChildren(...noMarket.map((m) => {
    const missing = !isNum(m.ask_a) && !isNum(m.ask_b) ? "no asks"
      : `no ask on ${(!isNum(m.ask_a) ? m.player_a : m.player_b) || "one side"}`;
    return el("li", {},
      el("span", { class: "players" }, `${m.player_a || "?"} vs ${m.player_b || "?"}`),
      el("span", { class: "why" }, `${tierLabel(m)} · ${m.phase || "unknown"} · ${missing}`));
  }));
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
      matchCell({ player_a: p.player_a, player_b: p.player_b, label: p.match_id,
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

// ---------------------------------------------------------------- paper tab
// Hypothetical trades from the scanner's pre-registered rules (state.paper), plus the nightly
// lookback over recorded order books (/lookback.json). Realized (settled) and locked-but-unsettled
// P&L are always shown apart: a lock is guaranteed only once the match settles.

let view = location.hash === "#paper" ? "paper" : "live";
let lookback = null;          // last good lookback.json
let lookbackErr = "";
let lookbackAt = 0;           // ms of the last lookback fetch
let paperKey = "";            // what the paper view was last drawn from
let pfStatus = "all", pfRule = "all";
const LOOKBACK_EVERY_MS = 5 * 60 * 1000;
const LOOKBACK_STALE_H = 36;  // written nightly at ~04:00 UTC

const objs = (xs) => (Array.isArray(xs) ? xs.filter((x) => x && typeof x === "object") : []);
const pctText = (x) => (isNum(x) ? `${(x * 100).toFixed(0)}%` : "—");
const sideName = (t) => (t.side === "A" ? t.player_a : t.side === "B" ? t.player_b : null) || t.side || "?";
const otherName = (t) => (t.side === "A" ? t.player_b : t.player_a) || "other side";

function ruleText(r) {
  if (!r) return "";
  if (isCash(r)) {
    const exit = isNum(r.level) ? `sell all at the bid when it nets ≥ ${centsText(r.level)}` : "hold to settlement (control)";
    return `buy every side with ask < ${centsText(r.max_ask)} at the first pre-start (E1) and first in-play (E2) look; ${exit}`;
  }
  const phase = r.entry_phase && r.entry_phase !== "any" ? `, ${r.entry_phase} only` : "";
  return `buy ≤ ${centsText(r.x)}, lock when all-in ≤ ${centsText(r.y)}${phase}`;
}

function table(cls, heads, rows) {
  return el("table", { class: "grid " + cls },
    el("thead", {}, el("tr", {}, heads.map(([h, num]) => el("th", { class: num ? "num" : "" }, h)))),
    el("tbody", {}, rows));
}
const cell = (label, ...kids) => el("td", { "data-label": label }, el("span", {}, ...kids));

// Start-up entries: trades opened at a rule's very first poll (entry_ts == that rule's `since`,
// else paper.since for an older scanner) can be on matches already in progress, so the
// pre-registration reads them separately from the headline.
const isCash = (x) => !!x && x.group === "cashout";
function ruleSince(paper, ruleId) {
  const r = objs(paper.rules).find((x) => x.id === ruleId);
  return (r && r.since) || paper.since || null;
}
const isStartup = (paper, t) => { const since = ruleSince(paper, t.rule); return !!since && t.entry_ts === since; };

function agg(ts) {
  const a = { trades: ts.length, open: 0, locked: 0, settled: 0, exited: 0, withLock: 0, realized: 0, lockedUn: 0, contracts: 0, capital: 0 };
  for (const t of ts) {
    if (t.status in a) a[t.status] += 1;
    if (isNum(t.lock_ask) || t.status === "exited") a.withLock += 1;
    if ((t.status === "settled" || t.status === "exited") && isNum(t.pnl)) { a.realized += t.pnl; a.contracts += t.contracts || 0; }
    if (t.status === "locked" && isNum(t.pnl)) { a.lockedUn += t.pnl; a.contracts += t.contracts || 0; }
    a.capital += (isNum(t.entry_cost) ? t.entry_cost : 0) + (isNum(t.lock_cost) ? t.lock_cost : 0);
  }
  a.lockRate = a.trades ? a.withLock / a.trades : null;
  a.perContract = a.contracts > 0 ? (a.realized + a.lockedUn) / a.contracts : null;
  return a;
}

const perCt = (x) => (isNum(x)
  ? el("span", { class: x > 0.0005 ? "pos" : x < -0.0005 ? "neg" : "" }, `${x > 0 ? "+" : x < 0 ? "−" : ""}${Math.abs(x * 100).toFixed(1)}¢`)
  : el("span", { class: "na" }, "—"));

function ruleRow(name, sub, a, cls) {
  return el("tr", { class: cls || "" },
    el("td", { class: "match" }, el("div", { class: "players" }, name), sub ? el("div", { class: "sub" }, sub) : null),
    td("Trades", qty(a.trades)),
    td("Open / locked / settled", `${qty(a.open)} / ${qty(a.locked)} / ${qty(a.settled)}`),
    td("Lock rate", pctText(a.lockRate)),
    td("Settled P&L", money(a.realized)),
    td("Locked, not settled", money(a.lockedUn)),
    td("P&L per contract", perCt(a.perContract)),
    td("Capital", money(a.capital, false)));
}

function paperRules(paper, only) {
  const rules = new Map(objs(paper.rules).map((r) => [r.id, r]));
  const trades = objs(paper.trades);
  const byRule = objs(paper.by_rule).filter((b) => !isCash(b) && !isCash(rules.get(b.rule)) && (!only || b.rule === only));
  const ids = byRule.map((b) => b.rule).filter(Boolean);
  const rows = [], startRows = [], head = [], start = [];
  let truncated = false;
  for (const b of byRule) {
    const ts = trades.filter((t) => t.rule === b.rule);
    if (isNum(b.trades) && b.trades > ts.length) {
      // The trade list is capped (200), so this rule can't be split or priced per contract: show the scanner's totals.
      truncated = true;
      rows.push(ruleRow(b.rule || "?", ruleText(rules.get(b.rule)), {
        trades: b.trades, open: b.open, locked: b.locked, settled: b.settled, lockRate: b.lock_rate,
        realized: b.pnl_settled, lockedUn: b.pnl_locked_unsettled, perContract: null, capital: b.capital }));
      continue;
    }
    const h = ts.filter((t) => !isStartup(paper, t)), s = ts.filter((t) => isStartup(paper, t));
    head.push(...h); start.push(...s);
    rows.push(ruleRow(b.rule || "?", ruleText(rules.get(b.rule)), agg(h)));
    if (s.length) startRows.push(ruleRow(b.rule || "?", "start-up entries (excluded)", agg(s), "startup"));
  }
  if (!rows.length) rows.push(el("tr", {}, el("td", { colspan: 8, class: "empty" }, "No rules in state.json.")));
  else if (!truncated && ids.length > 1) rows.push(ruleRow("All rules", "excluding start-up entries", agg(head), "total"));
  if (startRows.length) {
    rows.push(el("tr", { class: "group" }, el("td", { colspan: 8 },
      `Start-up entries (entered at the price when paper trading began, ${fmtDateTime(ruleSince(paper, byRule[0] && byRule[0].rule))}; excluded)`)));
    rows.push(...startRows);
  }
  const out = [table("paper-rules", [["Rule"], ["Trades", 1], ["Open / locked / settled", 1], ["Lock rate", 1],
    ["Settled P&L", 1], ["Locked, unsettled", 1], ["P&L / contract", 1], ["Capital", 1]], rows)];
  out.push(el("p", { class: "meta-line" },
    "P&L per contract = (settled + locked P&L) ÷ contracts on settled and locked trades; open trades have no P&L yet."
    + (truncated ? " Some rules have more trades than the list carries (200), so their start-up split and per-contract figure aren't shown."
      : trades.length >= 200 ? " The trade list is capped at 200, so the start-up split may be incomplete." : "")));
  return out;
}

// ---- cash-out portfolio (C rules): C1/C2 against the hold-only control C0 on the same entries.
const pairKey = (t) => `${t.match_id}|${t.side}|${t.entry_type}`;
const isFinal = (t) => (t.status === "settled" || t.status === "exited") && isNum(t.pnl);

// Δ per contract vs the control, on entries both rules hold and both have a final P&L.
function deltaVsControl(ts, control) {
  const ctl = new Map(control.filter(isFinal).map((t) => [pairKey(t), t]));
  let d = 0, n = 0, pairs = 0;
  for (const t of ts.filter(isFinal)) {
    const c = ctl.get(pairKey(t));
    if (!c || !(t.contracts > 0)) continue;
    d += t.pnl - c.pnl * (t.contracts / (c.contracts || t.contracts));
    n += t.contracts; pairs += 1;
  }
  return { delta: n > 0 ? d / n : null, pairs };
}

// Spread of outcomes: SD of P&L per contract over a rule's final trades, with the range below it.
function spread(ts) {
  const xs = ts.filter(isFinal).filter((t) => t.contracts > 0).map((t) => t.pnl / t.contracts);
  if (xs.length < 2) return null;
  const m = xs.reduce((a, b) => a + b, 0) / xs.length;
  const sd = Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / (xs.length - 1));
  return { sd, min: Math.min(...xs), max: Math.max(...xs), n: xs.length };
}
const ctText = (x) => `${x > 0.0005 ? "+" : x < -0.0005 ? "−" : ""}${Math.abs(x * 100).toFixed(1)}¢`;

function cashRow(name, sub, a, dv, sp, cls) {
  return el("tr", { class: cls || "" },
    el("td", { class: "match" }, el("div", { class: "players" }, name), sub ? el("div", { class: "sub" }, sub) : null),
    td("Trades", qty(a.trades)),
    td("Open / exited / final", `${qty(a.open)} / ${qty(a.exited)} / ${qty(a.settled + a.exited)}`),
    td("Exit rate", pctText(a.trades ? a.exited / a.trades : null)),
    td("Final P&L (settled + sold)", money(a.realized)),
    td("P&L per contract", perCt(a.perContract)),
    td("Δ vs C0 per contract", dv === "control" ? el("span", { class: "na" }, "control")
      : dv ? [perCt(dv.delta), el("div", { class: "subline" }, `${dv.pairs} paired entr${dv.pairs === 1 ? "y" : "ies"}`)] : el("span", { class: "na" }, "—")),
    td("Spread of outcomes", sp ? [`±${(sp.sd * 100).toFixed(1)}¢`, el("div", { class: "subline" }, `${ctText(sp.min)} to ${ctText(sp.max)}`)]
      : el("span", { class: "na" }, "—")),
    td("Capital", money(a.capital, false)));
}

function cashSection(paper, only) {
  const allRules = objs(paper.rules).filter(isCash);
  if (!allRules.length) return [];
  const rules = only ? allRules.filter((r) => r.id === only) : allRules;
  const trades = objs(paper.trades);
  const control = allRules.find((r) => !isNum(r.level));
  const head = (id) => trades.filter((t) => t.rule === id && !isStartup(paper, t));
  const ctlTrades = control ? head(control.id) : [];
  const rows = [], startRows = [];
  for (const r of rules) {
    const ts = trades.filter((t) => t.rule === r.id);
    const h = ts.filter((t) => !isStartup(paper, t)), st = ts.filter((t) => isStartup(paper, t));
    const dv = r === control ? "control" : control ? deltaVsControl(h, ctlTrades) : null;
    rows.push(cashRow(r.id, ruleText(r), agg(h), dv, spread(h)));
    if (st.length) {
      const sdv = r === control ? "control" : control
        ? deltaVsControl(st, trades.filter((t) => t.rule === control.id && isStartup(paper, t))) : null;
      startRows.push(cashRow(r.id, "start-up entries (excluded)", agg(st), sdv, spread(st), "startup"));
    }
  }
  if (startRows.length) {
    rows.push(el("tr", { class: "group" }, el("td", { colspan: 9 },
      `Start-up entries (entered at the price when the cash-out rules began, ${fmtDateTime(rules[0].since || paper.since)}; excluded)`)));
    rows.push(...startRows);
  }
  const truncated = trades.length >= 200;
  return [
    table("paper-cash", [["Rule"], ["Trades", 1], ["Open / exited / final", 1], ["Exit rate", 1],
      ["Final P&L", 1], ["P&L / contract", 1], ["Δ vs C0 / contract", 1], ["Spread / contract", 1], ["Capital", 1]], rows),
    el("p", { class: "meta-line" },
      "Final P&L counts settled and sold trades. Δ vs C0 pairs each entry with the control's identical entry (same match, side and E1/E2) once both are final;"
      + " C2's 20–30¢ entries have no C0 twin, so only its under-20¢ entries are paired. Spread = standard deviation of P&L per contract over final trades (range below)."
      + (truncated ? " The trade list is capped at 200, so these figures may be incomplete." : "")),
  ];
}

function tradeRow(paper, t) {
  const st = ["open", "locked", "settled", "exited"].includes(t.status) ? t.status : "open";
  const locked = isNum(t.lock_ask);
  const entry = [`${qty(t.contracts)} ${sideName(t)} @ ${centsText(t.entry_ask)}`,
    el("div", { class: "subline" }, `${fmtDateTime(t.entry_ts)} · ${t.entry_phase || "?"} · cost $${isNum(t.entry_cost) ? t.entry_cost.toFixed(2) : "—"}`)];
  const lock = st === "exited"
    ? [`sold @ ${centsText(t.exit_bid)} bid`,
       el("div", { class: "subline" }, `${fmtDateTime(t.exit_ts)} · $${isNum(t.exit_value) ? t.exit_value.toFixed(2) : "—"} after fee`)]
    : isCash(t) ? el("span", { class: "na" }, "held")
    : locked
    ? [`${qty(t.lock_contracts)} ${otherName(t)} @ ${centsText(t.lock_ask)}`,
       el("div", { class: "subline" }, `${fmtDateTime(t.lock_ts)} · cost $${isNum(t.lock_cost) ? t.lock_cost.toFixed(2) : "—"}`)]
    : el("span", { class: "na" }, "not locked");
  let result;
  if (st === "open") {
    result = [el("span", { class: "na" }, `if ${t.player_a || "A"} `), money(t.pnl_if_a),
      el("div", {}, el("span", { class: "na" }, `if ${t.player_b || "B"} `), money(t.pnl_if_b))];
  } else if (st === "locked") {
    result = [money(t.pnl), el("div", { class: "subline" }, "locked, pays at settlement")];
  } else if (st === "exited") {
    result = [money(t.pnl), el("div", { class: "subline" }, "sold at the bid")];
  } else {
    const won = t.settle_a === 1 ? t.player_a : t.settle_b === 1 ? t.player_b : null;
    result = [money(t.pnl), el("div", { class: "subline" },
      won ? `${won} won` : isNum(t.settle_a) ? `fair-price settle ${centsText(t.settle_a)} / ${centsText(t.settle_b)}` : "settled")];
  }
  const badges = [el("span", { class: "badge " + (st === "locked" || st === "exited" ? "lock" : st === "settled" ? "" : "live") }, st)];
  if (t.entry_type) badges.push(el("span", { class: "badge", title: t.entry_type === "E1" ? "first look before the start" : "first look in play" }, t.entry_type));
  if (isStartup(paper, t)) badges.push(el("span", { class: "badge", title: "opened at the first poll; read separately" }, "start-up"));
  return el("tr", { class: st === "locked" ? "hot-lock" : "" },
    matchCell({ player_a: t.player_a, player_b: t.player_b, label: `${tierLabel(t)} · ${t.rule || "?"}`, phase: null, badges }),
    td("Entry", entry), td(isCash(t) ? "Exit" : "Lock", lock), td(st === "open" ? "If each player wins" : "P&L", result));
}

// Trades for one portfolio (group) or one rule; status chips filter within that scope.
function paperTrades(paper, scope) {
  const inScope = (t) => (scope.rule ? t.rule === scope.rule : groupOf(paper, t.rule) === scope.group);
  const all = objs(paper.trades).filter(inScope);
  const counts = { all: all.length, open: 0, locked: 0, settled: 0, exited: 0 };
  for (const t of all) if (t.status in counts) counts[t.status] += 1;
  const ruleIds = [...new Set(all.map((t) => t.rule))].filter(Boolean);
  if (pfRule !== "all" && !ruleIds.includes(pfRule)) pfRule = "all";
  const shown = all.filter((t) => (pfStatus === "all" || t.status === pfStatus) && (scope.rule || pfRule === "all" || t.rule === pfRule));
  // Status chips are view filters only (read-only page).
  const chips = el("div", { class: "chips", role: "group", "aria-label": "Trade status" },
    ["all", "open", "locked", "exited", "settled"]
      .filter((k) => (k !== "exited" || counts.exited || pfStatus === "exited") && (k !== "locked" || scope.group !== "cashout"))
      .map((k) => el("button", {
        class: "chip" + (k === pfStatus ? " on" : ""), "data-filter": k, "aria-pressed": String(k === pfStatus),
        onclick: () => { pfStatus = k; paperKey = ""; renderPaper(); },
      }, `${k === "all" ? "All" : k[0].toUpperCase() + k.slice(1)} ${counts[k]}`)));
  let ruleSel = null;
  if (!scope.rule && ruleIds.length > 1) {
    ruleSel = el("select", { "aria-label": "Rule" }, el("option", { value: "all" }, "All rules"), ruleIds.map((id) => el("option", { value: id }, id)));
    ruleSel.value = pfRule;
    ruleSel.addEventListener("change", () => { pfRule = ruleSel.value; paperKey = ""; renderPaper(); });
  }
  const rows = shown.map((t) => tradeRow(paper, t));
  if (!rows.length) rows.push(el("tr", {}, el("td", { colspan: 4, class: "empty" }, all.length ? "No trades match the filter." : "No paper trades yet.")));
  return [
    el("div", { class: "filters" }, chips, ruleSel && el("label", {}, "Rule ", ruleSel),
      el("span", { class: "hint" }, objs(paper.trades).length >= 200 ? "the scanner sends the newest 200" : "")),
    table("paper-trades", [["Match"], ["Entry", 1], ["Lock / exit", 1], ["P&L", 1]], rows),
  ];
}
// Cumulative P&L per rule by settlement day (0c), as an inline SVG line chart.
function dayChart(days) {
  const NS = "http://www.w3.org/2000/svg";
  const svgEl = (tag, attrs, text) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v));
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const dayList = [...new Set(days.map((d) => d.day).filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d)))].sort();
  const ruleList = [...new Set(days.map((d) => d.rule).filter(Boolean))];
  if (!dayList.length || !ruleList.length) return null;
  const key = new Map(days.map((d) => [`${d.day}|${d.rule}`, d]));
  const series = ruleList.map((r) => {
    let run = 0;
    return dayList.map((day) => { const d = key.get(`${day}|${r}`); if (d && isNum(d.pnl)) run += d.pnl; return run; });
  });
  const W = 640, H = 220, L = 56, R = 12, T = 12, B = 26;
  const ys = series.flat();
  const lo = Math.min(0, ...ys), hi = Math.max(0, ...ys), span = hi - lo || 1;
  const sx = (i) => L + (dayList.length === 1 ? (W - L - R) / 2 : (i / (dayList.length - 1)) * (W - L - R));
  const sy = (v) => T + (1 - (v - lo) / span) * (H - T - B);
  const fmt = (v) => `${v < 0 ? "−" : v > 0 ? "+" : ""}$${Math.abs(v).toFixed(0)}`;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", class: "daychart",
    "aria-label": `Cumulative paper P&L by settlement day, ${dayList[0]} to ${dayList[dayList.length - 1]}` });
  svg.append(svgEl("line", { x1: L, x2: W - R, y1: sy(0), y2: sy(0), class: "c-zero" }));
  for (const v of [hi, 0, lo]) if (v === 0 || Math.abs(v) > span * 0.12) svg.append(svgEl("text", { x: L - 6, y: sy(v) + 4, "text-anchor": "end", class: "c-lab" }, fmt(v)));
  svg.append(svgEl("text", { x: L, y: H - 6, class: "c-lab" }, dayList[0].slice(5)));
  if (dayList.length > 1) svg.append(svgEl("text", { x: W - R, y: H - 6, "text-anchor": "end", class: "c-lab" }, dayList[dayList.length - 1].slice(5)));
  series.forEach((ys2, k) => {
    const cls = `c-s${k % 6}`;
    if (ys2.length === 1) svg.append(svgEl("circle", { cx: sx(0), cy: sy(ys2[0]), r: 4, class: cls + " dot" }));
    else svg.append(svgEl("path", { d: ys2.map((v, i) => `${i ? "L" : "M"}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`).join(" "), class: cls }));
  });
  const legend = el("div", { class: "c-legend" }, ruleList.map((r, k) => {
    const last = series[k][series[k].length - 1];
    return el("span", { class: `k c-s${k % 6}` }, `${r} `, money(last));
  }));
  return el("div", { class: "chart-card" }, svg, legend);
}

// ---- nightly lookback, by portfolio (group) or one rule
function lookbackRows() {
  const rows = new Map();
  for (const b of objs(lookback && lookback.by_rule)) {
    if (!rows.has(b.rule)) rows.set(b.rule, {});
    rows.get(b.rule)[b.slippage === 0 ? "s0" : "s1"] = b;
  }
  return rows;
}
const lbRules = () => new Map(objs(lookback && lookback.rules).map((r) => [r.id, r]));
const lbGroup = (id, rows, rules) => (isCash(rules.get(id)) || isCash((rows.get(id) || {}).s0 || {}) ? "cashout" : "swing");
const lbPerCt = (b) => (b && isNum(b.contracts) && b.contracts > 0 && isNum(b.pnl) ? b.pnl / b.contracts : null);

function lookbackMeta() {
  if (!lookback) {
    return [el("div", { class: "card-note" }, lookbackErr.includes("not found")
      ? "No lookback yet. It runs nightly at about 04:00 UTC over the recorder's order books."
      : lookbackErr ? `Lookback unavailable (${lookbackErr}).` : "Loading…")];
  }
  const L = lookback, out = [];
  const age = parseTs(L.generated_at);
  if (age !== null && Date.now() - age > LOOKBACK_STALE_H * 3.6e6) {
    out.push(el("div", { class: "banner inline" }, `Lookback is ${fmtAge(Date.now() - age)} old; the nightly run may have failed.`));
  }
  out.push(el("p", { class: "meta-line" },
    `Run ${fmtDateTime(L.generated_at)} (${age === null ? "time unknown" : fmtAge(Date.now() - age)}) · data ${fmtDate(L.data_from)} → ${fmtDate(L.data_to)} · `,
    `${qty(L.matches_processed)} of ${qty(L.matches_recorded)} recorded matches processed, ${qty(L.matches_with_trades)} with trades, `,
    `${qty(L.matches_new_this_run)} new this run, ${qty(L.matches_awaiting_result)} awaiting a result`
    + (isNum(L.matches_processed_cashout) ? ` · cash-out: ${qty(L.matches_processed_cashout)} processed` : "")));
  return out;
}

function lookbackSection(scope) {
  const out = [el("div", { class: "sec-head" }, el("h2", {}, scope.rule ? "Backtest: nightly lookback" : "Nightly lookback"),
    el("span", { class: "hint" }, "same rules over recorded order books")), ...lookbackMeta()];
  if (!lookback) return out;
  const L = lookback, rows = lookbackRows(), rules = lbRules();
  const ids = [...rows.keys()].filter((id) => (scope.rule ? id === scope.rule : lbGroup(id, rows, rules) === scope.group));
  if (!ids.length) {
    out.push(el("div", { class: "card-note" }, scope.rule ? `No lookback rows for ${scope.rule} yet.` : "No lookback rows for this portfolio yet."));
    return out;
  }
  if (scope.group === "cashout") {
    const ctlId = [...rows.keys()].find((id) => { const r = rules.get(id); return lbGroup(id, rows, rules) === "cashout" && r && !isNum(r.level); });
    const ctl = ctlId ? rows.get(ctlId) : null;
    const dl = (b, c) => (lbPerCt(b) !== null && lbPerCt(c) !== null ? lbPerCt(b) - lbPerCt(c) : null);
    out.push(table("lookback-cash", [["Rule"], ["Trades", 1], ["Exits", 1], ["P&L 0¢", 1], ["Per ct 0¢", 1], ["P&L 1¢", 1],
      ["Per ct 1¢", 1], ["Δ vs C0 0¢", 1], ["Δ vs C0 1¢", 1], ["Win rate", 1]], ids.map((rule) => {
      const { s0, s1 } = rows.get(rule), isCtl = rule === ctlId;
      return el("tr", {},
        el("td", { class: "match" }, el("div", { class: "players" }, rule || "?"), el("div", { class: "sub" }, ruleText(rules.get(rule)))),
        td("Trades", qty(s0?.trades)),
        td("Exits", s0 ? `${qty(s0.locked)} (${pctText(s0.lock_rate)})` : "—"),
        td("P&L at 0¢", money(s0?.pnl)),
        td("Per contract at 0¢", perCt(lbPerCt(s0))),
        td("P&L at 1¢ slippage", money(s1?.pnl)),
        td("Per contract at 1¢", perCt(lbPerCt(s1))),
        td("Δ vs C0 at 0¢", isCtl ? el("span", { class: "na" }, "control") : perCt(ctl ? dl(s0, ctl.s0) : null)),
        td("Δ vs C0 at 1¢", isCtl ? el("span", { class: "na" }, "control") : perCt(ctl ? dl(s1, ctl.s1) : null)),
        td("Win rate", pctText(s0?.win_rate)));
    })));
    out.push(el("p", { class: "meta-line" }, "Δ here is per-contract P&L minus C0's over each rule's own trades: exact for C1, C3 and C4 (same entries as C0); C2 also holds 20–30¢ entries that C0 doesn't."));
  } else {
    out.push(table("lookback", [["Rule"], ["Trades", 1], ["Locked", 1], ["P&L 0¢", 1], ["Per trade 0¢", 1], ["P&L 1¢", 1],
      ["Per trade 1¢", 1], ["Per ct 0¢", 1], ["Per ct 1¢", 1], ["Win rate", 1], ["Locked / unlocked", 1]], ids.map((rule) => {
      const { s0, s1 } = rows.get(rule);
      return el("tr", {},
        el("td", { class: "match" }, el("div", { class: "players" }, rule || "?"), el("div", { class: "sub" }, ruleText(rules.get(rule)))),
        td("Trades", qty(s0?.trades)),
        td("Locked", s0 ? `${qty(s0.locked)} (${pctText(s0.lock_rate)})` : "—"),
        td("P&L at 0¢", money(s0?.pnl)),
        td("Per trade at 0¢", money(s0?.pnl_per_trade)),
        td("P&L at 1¢ slippage", money(s1?.pnl)),
        td("Per trade at 1¢", money(s1?.pnl_per_trade)),
        td("Per contract at 0¢", perCt(lbPerCt(s0))),
        td("Per contract at 1¢", perCt(lbPerCt(s1))),
        td("Win rate", pctText(s0?.win_rate)),
        td("Locked / unlocked P&L", [money(s0?.pnl_locked), " / ", money(s0?.pnl_unlocked)]));
    })));
    if (objs(L.by_rule).length && !objs(L.by_rule).some((b) => isNum(b.contracts))) {
      out.push(el("p", { class: "meta-line" }, "Per contract needs a `contracts` total in the lookback's by_rule rows (scanner update phat-d0/Tennis_Model#119)."));
    }
  }
  const idSet = new Set(ids);
  const days = objs(L.by_day).filter((d) => idSet.has(d.rule));
  const chart = dayChart(days);
  if (chart) {
    out.push(el("div", { class: "sec-head" }, el("h3", {}, "Cumulative P&L by settlement day"), el("span", { class: "hint" }, "0¢ slippage")));
    out.push(chart);
    // The numbers behind the chart, last 14 days (a compact table even on phones).
    const dayList = [...new Set(days.map((d) => d.day).filter(Boolean))].sort().reverse().slice(0, 14);
    const ruleList = [...new Set(days.map((d) => d.rule).filter(Boolean))];
    const key = new Map(days.map((d) => [`${d.day}|${d.rule}`, d]));
    const short = (r) => String(r).split("-")[0];
    out.push(el("details", { class: "daydetails" }, el("summary", {}, `Daily numbers (last ${dayList.length} days)`),
      el("table", { class: "by-day" },
        el("thead", {}, el("tr", {}, el("th", {}, "Day"), ruleList.map((r) => el("th", { class: "num", title: r }, short(r))))),
        el("tbody", {}, dayList.map((day) => el("tr", {}, el("td", {}, day.slice(5)),
          ruleList.map((r) => {
            const d = key.get(`${day}|${r}`);
            return el("td", { class: "num", title: d ? `${r}: ${qty(d.trades)} trades, ${qty(d.locked)} locked` : r },
              d ? money(d.pnl) : el("span", { class: "na" }, "—"), d ? el("div", { class: "subline" }, `${qty(d.trades)} tr`) : null);
          }))))),
      el("p", { class: "meta-line" }, ruleList.map((r) => `${short(r)} = ${r}`).join(" · "))));
  }
  return out;
}

// ---- folder levels (owner 2026-10-28, the soccer app's Portfolio layout):
// home (portfolios) › portfolio (its strategies) › strategy (Live paper / Backtest).
const PORTFOLIOS = {
  swing: { name: "Swing-lock", pill: "Pre-registered 27 Oct",
    expect: "Expected result (pre-registered): about −3 to −5¢ per contract. A rule clearly above zero over ≥ 30 settled trades would be the surprise.",
    note: "Buy a side cheap, lock later by buying the other side when the pair costs less than $1 after fees. Rules frozen 2026-10-27." },
  cashout: { name: "Cash-out", pill: "Pre-registered 28 Oct",
    expect: "Expected result (pre-registered): Δ (C1 vs C0) about −1 to −3¢ per contract; C1 and C2 negative. A clearly positive Δ over ≥ 30 settled C1 trades would be the surprise.",
    note: "Buy an underdog under 20¢ (C2: 30¢) and sell at the bid once it nets the rule's level; C0 holds the same entries to settlement as the control. C1 is the owner's DOG50." },
};
let pfLevel = "home", pfPort = "swing", pfStrat = "", pfDetail = "live";
const CHEV = () => el("span", { class: "chev", "aria-hidden": "true" }, "›");

function groupOf(paper, ruleId) {
  const r = objs(paper.rules).find((x) => x.id === ruleId);
  return isCash(r) ? "cashout" : "swing";
}
const groupRules = (paper, g) => objs(paper.rules).filter((r) => (g === "cashout" ? isCash(r) : !isCash(r)));
const headTrades = (paper, id) => objs(paper.trades).filter((t) => t.rule === id && !isStartup(paper, t));
// Headline P&L = settled/sold + locked-but-unsettled (start-up entries excluded).
const livePnl = (a) => a.realized + a.lockedUn;

function goPaper(level, port, strat) {
  pfLevel = level;
  if (port) pfPort = port;
  if (strat !== undefined) pfStrat = strat;
  pfStatus = "all"; pfRule = "all"; paperKey = "";
  renderPaper();
  window.scrollTo(0, 0);
}

function folderRow(attrs, name, pill, meta, bt, right, small) {
  return el("button", { class: "row-btn folder", type: "button", ...attrs },
    el("span", { class: "who" }, el("b", {}, name), pill ? el("span", { class: "pill" }, pill) : null,
      meta ? el("span", { class: "meta" }, meta) : null, bt ? el("span", { class: "bt" }, bt) : null),
    el("span", { class: "vals" }, right, el("small", {}, small)), CHEV());
}

function crumbs(level) {
  const steps = [el("button", { class: "crumb", type: "button", "data-pfnav": "home", onclick: () => goPaper("home") },
    level === "strategy" ? "Paper" : "‹ Paper")];
  if (level === "strategy") {
    steps.push(el("span", { class: "crumb-sep", "aria-hidden": "true" }, "›"),
      el("button", { class: "crumb", type: "button", "data-pfnav": "portfolio", onclick: () => goPaper("portfolio") }, PORTFOLIOS[pfPort].name));
  }
  return el("nav", { class: "crumbs", "aria-label": "Back to" },
    level === "strategy" ? el("span", { class: "crumb-back", "aria-hidden": "true" }, "‹") : null, steps);
}

function hypoNote(g) {
  return el("div", { class: "paper-note", role: "note" },
    el("span", { class: "badge hypo" }, "Hypothetical, no orders"), " ",
    el("b", {}, PORTFOLIOS[g].expect + " "),
    "Fills assume the whole size at the displayed ask (sales at the bid) plus fees, so results are optimistic about fills.");
}

function paperHome(paper) {
  const rows = [];
  for (const g of ["swing", "cashout"]) {
    const rules = groupRules(paper, g);
    if (!rules.length) continue;
    const a = agg(rules.flatMap((r) => headTrades(paper, r.id)));
    const names = rules.map((r) => (g === "cashout" && !isNum(r.level) ? `${r.id} (control)` : r.id));
    rows.push(folderRow({ "data-pfid": g, onclick: () => goPaper("portfolio", g) },
      PORTFOLIOS[g].name, PORTFOLIOS[g].pill, `${rules.length} strategies: ${names.join(", ")}`, null,
      a.contracts ? el("b", { class: livePnl(a) > 0 ? "pos" : livePnl(a) < 0 ? "neg" : "" }, money(livePnl(a)).textContent || money(livePnl(a)))
        : el("b", { class: "na" }, "–"),
      `${qty(a.settled + a.exited + a.locked)} final or locked · ${qty(a.open)} open`));
  }
  return [
    el("div", { class: "sec-head" }, el("h2", {}, "Portfolios"), el("span", { class: "hint" }, paper.since ? `paper trading since ${fmtDateTime(paper.since)}` : "")),
    el("div", { class: "card list folders" }, rows),
    el("p", { class: "meta-line" },
      el("span", { class: "badge hypo" }, "Hypothetical, no orders"),
      " Each portfolio holds pre-registered paper rules. Its figure is its rules together (settled, sold and locked P&L), start-up entries left out. Open one for its strategies, trades and nightly lookback."),
    el("div", { class: "sec-head" }, el("h3", {}, "Nightly lookback"), el("span", { class: "hint" }, "inside each portfolio")),
    ...lookbackMeta(),
  ];
}

function strategyFolders(paper, g) {
  const rules = groupRules(paper, g);
  const trades = objs(paper.trades);
  const control = g === "cashout" ? rules.find((r) => !isNum(r.level)) : null;
  const lbRowsMap = lookbackRows();
  return el("div", { class: "card list folders" }, rules.map((r) => {
    const h = headTrades(paper, r.id), a = agg(h);
    const lb = lbRowsMap.get(r.id)?.s0;
    const bt = lookback ? (lb ? ["Lookback: ", money(lb.pnl), ` · ${lbPerCt(lb) !== null ? ctText(lbPerCt(lb)) + "/ct · " : ""}${qty(lb.trades)} trades`] : "Lookback: no rows yet") : null;
    let small = `${a.perContract !== null ? ctText(a.perContract) + "/ct · " : ""}${qty(a.trades)} trades`;
    if (control) {
      if (r === control) small = `control · ${qty(a.trades)} trades`;
      else {
        const dv = deltaVsControl(h, headTrades(paper, control.id));
        small = `Δ vs C0 ${dv.delta !== null ? ctText(dv.delta) : "—"} · ${qty(a.trades)} trades`;
      }
    }
    const startN = trades.filter((t) => t.rule === r.id && isStartup(paper, t)).length;
    return folderRow({ "data-pfstrat": r.id, onclick: () => goPaper("strategy", g, r.id) },
      r.id, null, ruleText(r) + (startN ? ` · ${startN} start-up entr${startN === 1 ? "y" : "ies"} apart` : ""), bt,
      a.contracts ? el("b", { class: livePnl(a) > 0 ? "pos" : livePnl(a) < 0 ? "neg" : "" }, money(livePnl(a)).textContent || money(livePnl(a)))
        : el("b", { class: "na" }, "–"),
      small);
  }));
}

function paperPortfolio(paper) {
  const g = pfPort, P = PORTFOLIOS[g];
  const rules = groupRules(paper, g);
  const since = rules[0] && (rules[0].since || paper.since);
  return [
    crumbs("portfolio"),
    el("h2", { class: "pf-title" }, P.name, " ", el("span", { class: "pill" }, P.pill)),
    el("div", { class: "pf-sub" }, P.note + (since ? ` Since ${fmtDateTime(since)}.` : "")),
    hypoNote(g),
    el("div", { class: "sec-head" }, el("h2", {}, "Strategies"), el("span", { class: "hint" }, "open one for its trades and lookback")),
    strategyFolders(paper, g),
    el("div", { class: "sec-head" }, el("h2", {}, g === "cashout" ? "Cash-out portfolio (pre-registered 2026-10-28)" : "Swing-lock rules: P&L by rule"),
      el("span", { class: "hint" }, "start-up entries apart")),
    ...(g === "cashout" ? cashSection(paper) : paperRules(paper)),
    el("div", { class: "sec-head" }, el("h2", {}, "Trades"), el("span", { class: "hint" }, "open and locked first")),
    ...paperTrades(paper, { group: g }),
    ...lookbackSection({ group: g }),
  ];
}

function paperStrategy(paper) {
  const g = pfPort, r = groupRules(paper, g).find((x) => x.id === pfStrat);
  if (!r) { pfLevel = "portfolio"; return paperPortfolio(paper); }
  const toggle = el("div", { class: "segmented", role: "group", "aria-label": "Which view" },
    [["live", "Live paper"], ["backtest", "Backtest"]].map(([k, label]) => el("button", {
      type: "button", class: k === pfDetail ? "on" : "", "data-pf": k, "aria-pressed": String(k === pfDetail),
      onclick: () => { pfDetail = k; paperKey = ""; renderPaper(); },
    }, label)));
  const head = [crumbs("strategy"), el("h2", { class: "pf-title" }, r.id),
    el("div", { class: "pf-sub" }, ruleText(r) + (r.since ? ` · since ${fmtDateTime(r.since)}` : "")), toggle];
  if (pfDetail === "backtest") return [...head, ...lookbackSection({ group: g, rule: r.id })];
  return [...head,
    ...(g === "cashout" ? cashSection(paper, r.id) : paperRules(paper, r.id)),
    el("div", { class: "sec-head" }, el("h2", {}, "Trades"), el("span", { class: "hint" }, "this rule only")),
    ...paperTrades(paper, { group: g, rule: r.id })];
}

function renderPaper() {
  const box = $("view-paper");
  const paper = state && state.paper && typeof state.paper === "object" ? state.paper : null;
  const key = JSON.stringify([!!state, paper, lookback && lookback.generated_at, lookbackErr, pfStatus, pfRule, pfLevel, pfPort, pfStrat, pfDetail]);
  if (key === paperKey) return;   // unchanged: don't rebuild (keeps an open filter select usable)
  paperKey = key;
  let out;
  if (!paper) {
    out = [el("div", { class: "card-note" }, state ? "The scanner isn't paper trading (no `paper` in state.json; it may run with --no-paper)." : "Loading…"), ...lookbackMeta()];
  } else {
    if (!groupRules(paper, pfPort).length) pfLevel = "home";
    out = pfLevel === "strategy" ? paperStrategy(paper) : pfLevel === "portfolio" ? paperPortfolio(paper) : paperHome(paper);
  }
  box.dataset.level = paper ? pfLevel : "none";
  box.replaceChildren(el("section", {}, out));
}

async function loadLookback(force = false) {
  if (!force && Date.now() - lookbackAt < LOOKBACK_EVERY_MS) return;
  lookbackAt = Date.now();
  try {
    const r = await fetch("lookback.json", { cache: "no-store" });
    if (r.status === 204) throw new Error("not found");   // no nightly run yet
    if (!r.ok) {
      let detail = "HTTP " + r.status;
      try { const j = await r.json(); if (j && j.error) detail = j.error; } catch (_) { /* keep status */ }
      throw new Error(detail);
    }
    const j = await r.json();
    if (!j || typeof j !== "object" || Array.isArray(j)) throw new Error("not an object");
    lookback = j; lookbackErr = "";
  } catch (e) {
    lookbackErr = e && e.message ? e.message : "network error";
  }
  renderPaper();
}

function showView(v) {
  view = v === "paper" ? "paper" : "live";
  $("view-live").hidden = view !== "live";
  $("view-paper").hidden = view !== "paper";
  for (const b of document.querySelectorAll(".views button")) b.setAttribute("aria-selected", String(b.dataset.view === view));
  history.replaceState(null, "", view === "paper" ? "#paper" : location.pathname + location.search);
  if (view === "paper") loadLookback();
}

function render() {
  if (state) {
    $("venue").textContent = state.venue ? "· " + state.venue + " tennis" : "";
    renderSummary(state);
    renderAlerts(state);
    renderMarkets(state);
    renderPositions(state);
  }
  renderPaper();
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
for (const b of document.querySelectorAll(".views button")) {
  b.addEventListener("click", () => {
    if (b.dataset.view === "paper" && view === "paper" && pfLevel !== "home") goPaper("home");   // tap again: back to the portfolios
    showView(b.dataset.view);
  });
}
showView(view);
loadLookback(true);
setInterval(() => loadLookback(), LOOKBACK_EVERY_MS);
$("phase").addEventListener("change", () => {
  render();
  try { localStorage.setItem("swinglock-phase", $("phase").value); } catch (_) { /* ignore */ }
});
$("q").addEventListener("input", render);
try {
  const p = localStorage.getItem("swinglock-phase");
  if (p && [...$("phase").options].some((o) => o.value === p)) $("phase").value = p;
} catch (_) { /* storage blocked */ }
setInterval(renderStatus, 1000);   // keep the age and stale warning ticking between polls
document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
poll();
