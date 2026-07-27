// Browse — the dense ledger over the whole tree.
// Columns: type · path · name · category · bytes · tokens · badge · findings
// Click a row to open Detail/Edit.

import { navigate } from "/static/js/app.js";

export function renderLedger(state) {
  if (state.searchHits) {
    return renderSearchHits(state);
  }
  const rows = state.tree
    .filter(f => f.kind !== "persona")   // persona shown on memory screen
    .map(f => {
      const findings = (f.findings || []).length;
      const rel = f.path.includes("/.hermes/")
        ? f.path.split("/.hermes/")[1]
        : f.path;
      const tokens = Math.ceil((f.bytes || 0) / 4);
      return `<tr data-act="open" data-path="${escape(f.path)}" class="${f.badge === "red" ? "row-danger" : ""}">
        <td><span class="badge ${f.badge}">${f.badge.toUpperCase()}</span></td>
        <td>${f.kind}</td>
        <td class="path"><span class="rel">${escape(rel.split("/").slice(0, -1).join("/"))}/</span><b>${escape(rel.split("/").slice(-1)[0])}</b></td>
        <td>${escape(f.name || "")}</td>
        <td>${escape(f.category || "")}</td>
        <td class="num">${formatBytes(f.bytes)}</td>
        <td class="num">${tokens}</td>
        <td class="num">${findings || ""}</td>
      </tr>`;
    }).join("");
  const persona = state.tree.find(f => f.kind === "persona");
  const totals = {
    n: state.tree.length,
    bytes: state.tree.reduce((a, b) => a + b.bytes, 0),
    red: state.tree.filter(f => f.badge === "red").length,
    amber: state.tree.filter(f => f.badge === "amber").length,
  };
  return `
    <div class="section-h">Browse — the tree ledger</div>
    <div class="kpi-strip">
      <div class="kpi"><span class="v">${totals.n}</span><span class="l">files</span></div>
      <div class="kpi"><span class="v">${formatBytes(totals.bytes)}</span><span class="l">total bytes</span></div>
      <div class="kpi"><span class="v ${totals.red ? "danger" : ""}">${totals.red}</span><span class="l">red (would reject)</span></div>
      <div class="kpi"><span class="v" style="color:var(--warn);">${totals.amber}</span><span class="l">amber (silent)</span></div>
      <div class="kpi"><span class="v accent">${persona ? formatBytes(persona.bytes) : "—"}</span><span class="l">persona (SOUL.md)</span></div>
    </div>
    <div class="search-bar">
      <input type="text" placeholder="press / to search · type:skill platform:linux state:stale locked:true badge:red" />
      <span class="hint">keyboard: <kbd>j</kbd>/<kbd>k</kbd> navigate · <kbd>Enter</kbd> open · <kbd>d</kbd> detail · <kbd>v</kbd> validate</span>
    </div>
    <table class="ledger">
      <thead>
        <tr>
          <th>badge</th><th>type</th><th>path</th><th>name</th>
          <th>category</th><th class="num">bytes</th><th class="num">tokens</th><th class="num">findings</th>
        </tr>
      </thead>
      <tbody>${rows || `<tr><td colspan="8" class="dim">no files</td></tr>`}</tbody>
    </table>
    <script type="module">
      import { registerAction } from "/static/js/app.js";
      registerAction("open", (d) => { navigate("editor", { selected: d.path }); });
    </script>
  `;
}

function renderSearchHits(state) {
  const rows = state.searchHits.map(h =>
    `<tr data-act="open" data-path="${escape(h.path)}">
       <td class="path mono">${escape(h.path)}</td>
       <td>${h.kind}</td>
       <td>${h.snip || ""}</td>
     </tr>`
  ).join("");
  return `
    <div class="section-h">Search results</div>
    <table class="ledger">
      <thead><tr><th>path</th><th>kind</th><th>match</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <script type="module">
      import { registerAction } from "/static/js/app.js";
      registerAction("open", (d) => { navigate("editor", { selected: d.path }); });
    </script>
  `;
}

function formatBytes(n) {
  if (!n && n !== 0) return "";
  if (n < 1024) return String(n);
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + "K";
  return (n / 1024 / 1024).toFixed(1) + "M";
}
function escape(s) { return String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }