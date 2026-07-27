// Hermes MD Manager — SPA entry. Vanilla ES modules, no build step.
//
// Architecture: a single `state` object, a tiny reactive render() that
// diffs by an `el._renderKey` set on each container, and a `route()` that
// dispatches on `state.screen`. No framework — keeps the audit surface small.

import { renderLedger } from "/static/js/screens/ledger.js";
import { renderValidate } from "/static/js/screens/validate.js";
import { renderBudget } from "/static/js/screens/budget.js";
import { renderEditor } from "/static/js/screens/editor.js";
import { renderDetail } from "/static/js/screens/detail.js";
import { renderMemory } from "/static/js/screens/memory.js";
import { renderCreate } from "/static/js/screens/create.js";

// ── boot meta (token + version + read-only flag) ───────────────────────────
const bootEl = document.getElementById("boot-meta");
const boot = bootEl ? JSON.parse(bootEl.textContent) : { token: "", read_only: false, version: "?", reasons: [] };

if (boot.read_only) {
  console.warn("source-parity check tripped:", boot.reasons);
}

const TOKEN = boot.token;
function authHeaders() {
  return TOKEN ? { "X-Auth-Token": TOKEN } : {};
}

// ── state ──────────────────────────────────────────────────────────────────
const state = {
  screen: "ledger",
  tree: [],                 // GET /api/tree response
  budget: null,             // GET /api/budget
  findings: [],             // GET /api/validate
  selected: null,           // path
  baseline: null,           // last-seen sha256 for selected file (conflict baseline)
  dirty: false,
  toast: null,
};

// ── fetch helpers ──────────────────────────────────────────────────────────
async function api(method, url, body) {
  const opts = { method, headers: { "Content-Type": "application/json", ...authHeaders() } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(url, opts);
  if (!r.ok) {
    let msg;
    try { msg = (await r.json()).detail || (await r.text()); }
    catch { msg = r.statusText; }
    throw new Error(`${r.status} ${msg}`);
  }
  return r.json();
}

// ── navigation ─────────────────────────────────────────────────────────────
const SCREENS = [
  { id: "ledger",  title: "Browse",    key: "b", subtitle: "Tree ledger" },
  { id: "validate",title: "Validate",  key: "v", subtitle: "Whole-tree lint" },
  { id: "budget",  title: "Budget",    key: "u", subtitle: "Always-loaded tokens" },
  { id: "editor",  title: "Edit",      key: "e", subtitle: "File editor" },
  { id: "detail",  title: "Detail",    key: "d", subtitle: "File detail / resolution / locks" },
  { id: "memory",  title: "Memory",    key: "m", subtitle: "Persona & memory" },
  { id: "create",  title: "Create",    key: "c", subtitle: "New file / import / export" },
];

function navigate(screen, params = {}) {
  state.screen = screen;
  Object.assign(state, params);
  render();
}

// ── top-level render ───────────────────────────────────────────────────────
function render() {
  const root = document.getElementById("app");
  root.innerHTML = layout();
  // re-attach event listeners after innerHTML wipe
  attachNavListeners();
  attachGlobalKeyListeners();
  // render the active screen
  const main = document.getElementById("main");
  let html = "";
  switch (state.screen) {
    case "ledger":   html = renderLedger(state); break;
    case "validate": html = renderValidate(state); break;
    case "budget":   html = renderBudget(state); break;
    case "editor":   html = renderEditor(state); break;
    case "detail":   html = renderDetail(state); break;
    case "memory":   html = renderMemory(state); break;
    case "create":   html = renderCreate(state); break;
    default:         html = `<div class="section-h">Unknown screen</div>`;
  }
  main.innerHTML = html;
  attachScreenListeners();
  // global toast
  const toast = document.getElementById("toast");
  if (state.toast) {
    toast.textContent = state.toast.text;
    toast.className = "toast" + (state.toast.kind === "danger" ? " danger" : "");
    toast.style.display = "block";
    setTimeout(() => { state.toast = null; if (document.getElementById("toast")) document.getElementById("toast").style.display = "none"; }, 4000);
  } else {
    toast.style.display = "none";
  }
}

function layout() {
  const nav = SCREENS.map(s => `
    <a href="#${s.id}" data-screen="${s.id}" class="${state.screen === s.id ? "active" : ""}">
      <span>${s.title}</span>
      <span class="key">${s.key}</span>
    </a>
  `).join("");
  const sectionMarkers = `
    <div class="nav-section">Tree</div>
    <div class="nav-section">Lifecycle</div>
    <div class="nav-section">Maintenance</div>
  ``;
  return `
    <header>
      <h1>Hermes <span class="accent">MD</span> Manager</h1>
      <span class="dim mono">v${boot.version} · ${boot.read_only ? "READ-ONLY" : "armed"} · HERMES_HOME ${(boot.hermes_home || "").split("/").slice(-2).join("/")}</span>
      <span class="boot-meta">token …${TOKEN.slice(-6)}</span>
    </header>
    <nav>
      <div class="nav-section">Tree</div>
      ${SCREENS.slice(0, 3).map(s => `<a href="#${s.id}" data-screen="${s.id}" class="${state.screen === s.id ? "active" : ""}"><span>${s.title}</span><span class="key">${s.key}</span></a>`).join("")}
      <div class="nav-section">Edit</div>
      <a href="#editor" data-screen="editor" class="${state.screen === "editor" ? "active" : ""}"><span>Edit</span><span class="key">e</span></a>
      <a href="#detail" data-screen="detail" class="${state.screen === "detail" ? "active" : ""}"><span>Detail / Resolution / Locks</span><span class="key">d</span></a>
      <a href="#memory" data-screen="memory" class="${state.screen === "memory" ? "active" : ""}"><span>Memory &amp; Persona</span><span class="key">m</span></a>
      <div class="nav-section">Maintenance</div>
      <a href="#create" data-screen="create" class="${state.screen === "create" ? "active" : ""}"><span>Create / Import-Export</span><span class="key">c</span></a>
    </nav>
    <main id="main"></main>
    <footer>
      <span>j/k move</span><span class="sep">·</span>
      <span>/ search</span><span class="sep">·</span>
      <span>Enter open</span><span class="sep">·</span>
      <span>v validate</span><span class="sep">·</span>
      <span>u budget</span><span class="sep">·</span>
      <span>1-7 jump</span>
    </footer>
    <div id="toast" class="toast" style="display:none;"></div>
  `;
}

// ── data loading (per-screen) ──────────────────────────────────────────────
async function loadTree()  { state.tree = (await api("GET", "/api/tree")).files; }
async function loadBudget(){ state.budget = await api("GET", "/api/budget"); }
async function loadValidate(){ const r = await api("POST", "/api/validate"); state.findings = r.findings; state.counts = r.counts; }

async function ensureTree()    { if (!state.tree.length) await loadTree(); }
async function ensureBudget()  { if (!state.budget) await loadBudget(); }
async function ensureValidate(){ if (!state.findings.length && !state.counts) await loadValidate(); }

// ── navigation event handlers ──────────────────────────────────────────────
function attachNavListeners() {
  document.querySelectorAll("nav a").forEach(a => {
    a.addEventListener("click", e => {
      e.preventDefault();
      navigate(a.dataset.screen);
      if (a.dataset.screen === "tree")    loadTree().then(render);
      if (a.dataset.screen === "budget")  loadBudget().then(render);
      if (a.dataset.screen === "validate")loadValidate().then(render);
    });
  });
}

function attachGlobalKeyListeners() {
  document.onkeydown = (ev) => {
    if (ev.target && (ev.target.tagName === "TEXTAREA" || ev.target.tagName === "INPUT")) return;
    if (ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const key = ev.key.toLowerCase();
    // 1-7 → jump to screen
    const idx = "1234567".indexOf(key);
    if (idx >= 0 && idx < SCREENS.length) {
      ev.preventDefault();
      const s = SCREENS[idx].id;
      navigate(s);
      if (s === "ledger")  loadTree().then(render);
      if (s === "budget")  loadBudget().then(render);
      if (s === "validate")loadValidate().then(render);
      return;
    }
    if (key === "/") {
      ev.preventDefault();
      const q = prompt("search:");
      if (q) doSearch(q);
    }
    if (key === "g") {
      // g then letter — defer
      state._gPending = true;
      setTimeout(() => state._gPending = false, 800);
      return;
    }
    if (state._gPending) {
      state._gPending = false;
      const s = SCREENS.find(s => s.key === key);
      if (s) navigate(s.id);
    }
  };
}

async function doSearch(q) {
  const r = await api("GET", `/api/search?q=${encodeURIComponent(q)}`);
  state.screen = "ledger";
  state.searchHits = r.hits;
  render();
  state.toast = { text: `${r.hits.length} hits for "${q}"`, kind: "ok" };
  render();
}

function attachScreenListeners() {
  const main = document.getElementById("main");
  if (!main) return;
  main.onclick = (ev) => {
    const t = ev.target.closest("[data-act]");
    if (t) handleAct(t.dataset.act, t.dataset, ev);
  };
  main.onchange = (ev) => {
    const t = ev.target.closest("[data-bind]");
    if (t) handleBind(t.dataset.bind, t.value || "", ev);
  };
  main.oninput = (ev) => {
    const t = ev.target.closest("[data-bind-input]");
    if (t) handleBindInput(t.dataset.bindInput, t, ev);
  };
  main.onsubmit = (ev) => {
    const t = ev.target.closest("[data-form]");
    if (t) { ev.preventDefault(); handleForm(t.dataset.form, t, ev); }
  };
}

function handleAct(act, data, ev) {
  const fn = actions[act];
  if (fn) fn(data, ev);
}
function handleBind(name, value, ev) { /* could be wired per screen */ }
function handleBindInput(name, el, ev) { /* could be wired per screen */ }
function handleForm(name, form, ev) { /* could be wired per screen */ }

// ── shared actions registry (screens register handlers by name) ─────────────
const actions = {};
export function registerAction(name, fn) { actions[name] = fn; }

export function toast(text, kind = "ok") {
  state.toast = { text, kind };
  render();
}

// ── boot ───────────────────────────────────────────────────────────────────
(async () => {
  try {
    await loadTree();
    render();
  } catch (exc) {
    document.getElementById("app").innerHTML = `<pre style="color: var(--danger); padding: 14px;">${exc.message}</pre>`;
  }
})();

window.__hermes_md = { state, api, navigate, registerAction, toast, render };