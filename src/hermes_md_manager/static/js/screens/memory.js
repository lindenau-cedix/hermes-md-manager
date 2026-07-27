// Memory & Persona — SOUL.md (prose) + MEMORY.md/USER.md (§-delimited).
// Memory editor hard-blocks any save that would fail Hermes' drift guard.

import { api, toast, registerAction } from "/static/js/app.js";

export async function renderMemory(state) {
  const soul = await api("GET", "/api/file?path=" + encodeURIComponent(expandHome("SOUL.md")));
  const mem = await api("GET", "/api/file?path=" + encodeURIComponent(expandHome("memories/MEMORY.md")));
  const user = await api("GET", "/api/file?path=" + encodeURIComponent(expandHome("memories/USER.md")));
  return `
    <div class="section-h">Memory &amp; Persona</div>
    <div class="editor-shell">
      <div class="editor-pane">
        <h2>SOUL.md — persona (raw prose, no schema)</h2>
        <textarea rows="10" data-bind-input="soul">${escape(soul.report.body || "")}</textarea>
        <div class="dim mono">persona is injected whole into the system prompt (identity slot #1) every session. No schema — byte-fidelity only.</div>
        <div class="toolbar">
          <button data-act="save_soul" class="primary">save SOUL.md</button>
          <span class="dim mono" id="soul-bytes"></span>
        </div>
      </div>
      <div class="editor-pane">
        <h2>Memory files — MEMORY.md / USER.md</h2>
        <div class="memory-grid">
          <div class="memory-entries">
            <h3 style="font-family:var(--grotesk);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-mute);margin:8px 0 4px 0;">MEMORY.md entries</h3>
            ${renderEntries(mem.report)}
            <textarea rows="3" placeholder="add a new entry…" data-bind-input="new_mem"></textarea>
            <div class="toolbar">
              <button data-act="add_mem" class="primary">add to MEMORY.md</button>
            </div>
            <h3 style="font-family:var(--grotesk);font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-mute);margin:14px 0 4px 0;">USER.md entries</h3>
            ${renderEntries(user.report)}
            <textarea rows="3" placeholder="add a new entry…" data-bind-input="new_user"></textarea>
            <div class="toolbar">
              <button data-act="add_user" class="primary">add to USER.md</button>
            </div>
          </div>
          <div>
            <div class="dim mono" style="padding: 8px 12px;">budget</div>
            <div class="kpi">
              <span class="l">MEMORY.md</span>
              <span class="v">${(mem.report.bytes || 0).toLocaleString()} <span class="dim mono" style="font-size:11px;">/ 2200</span></span>
              <div class="bar"><div class="fill ${mem.report.bytes > 2200 ? "danger" : mem.report.bytes > 1760 ? "warn" : ""}" style="right:${100 - Math.min(100, mem.report.bytes / 2200 * 100)}%"></div></div>
            </div>
            <div class="kpi" style="margin-top:14px;">
              <span class="l">USER.md</span>
              <span class="v">${(user.report.bytes || 0).toLocaleString()} <span class="dim mono" style="font-size:11px;">/ 1375</span></span>
              <div class="bar"><div class="fill ${user.report.bytes > 1375 ? "danger" : user.report.bytes > 1100 ? "warn" : ""}" style="right:${100 - Math.min(100, user.report.bytes / 1375 * 100)}%"></div></div>
            </div>
          </div>
        </div>
        <div class="dim mono" style="padding: 8px 12px;">
          drift guard: raw.strip() == \\n§\\n-joined roundtrip AND no entry exceeds the store char-limit.
          saves that would fail are BLOCKED.
        </div>
      </div>
    </div>
    <script type="module">
      import { api, toast } from "/static/js/app.js";
      const home = "${escape(bootMeta().hermes_home || "")}";
      registerAction("save_soul", async () => {
        const content = document.querySelector('textarea[data-bind-input="soul"]').value;
        const r = await api("POST", "/api/write", {
          path: home + "/SOUL.md",
          content,
          baseline_sha256: "${escape(soul.report.sha256)}",
          approved: true,
        });
        toast(r.ok ? "saved SOUL.md" : (r.error || "failed"), r.ok ? "ok" : "danger");
        render();
      });
      registerAction("add_mem", async () => {
        const v = document.querySelector('textarea[data-bind-input="new_mem"]').value.trim();
        if (!v) return;
        const r = await api("POST", "/api/create", { kind: "memory_entry", file: "MEMORY.md", content: v });
        toast(r.ok ? "added to MEMORY.md" : (r.error || "failed"), r.ok ? "ok" : "danger");
        render();
      });
      registerAction("add_user", async () => {
        const v = document.querySelector('textarea[data-bind-input="new_user"]').value.trim();
        if (!v) return;
        const r = await api("POST", "/api/create", { kind: "memory_entry", file: "USER.md", content: v });
        toast(r.ok ? "added to USER.md" : (r.error || "failed"), r.ok ? "ok" : "danger");
        render();
      });
    </script>
  `;
}

function renderEntries(report) {
  if (!report) return `<div class="dim mono">(file missing)</div>`;
  if (report.badge === "red") {
    return `<div class="dim mono" style="color:var(--danger);">drift detected — save blocked. open the file and rewrite as a clean §-delimited list.</div>`;
  }
  return `<div class="dim mono">${report.bytes.toLocaleString()} chars · ${(report.parsed && report.parsed.entries) || 0} entries · badge ${report.badge}</div>`;
}

function expandHome(p) {
  // We don't know HERMES_HOME here — the API will resolve via paths.hermes_home().
  // The file path returned by the API will be absolute; we just need to be
  // consistent. Use the path as-is since the API normalises.
  return "/home/app/.hermes/" + p;
}

function bootMeta() {
  const el = document.getElementById("boot-meta");
  return el ? JSON.parse(el.textContent) : {};
}

function escape(s) { return String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }