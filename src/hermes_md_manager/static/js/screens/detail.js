// File Detail / Resolution / Locks — per-file inspection + lifecycle ops.

import { api, navigate, toast, registerAction } from "/static/js/app.js";

export async function renderDetail(state) {
  const path = state.selected;
  if (!path) {
    return `<div class="section-h">Detail / Resolution / Locks</div>
      <div class="dim">select a file from the ledger, or enter a skill name on the Resolution view below.</div>
      <div class="section-h">Resolution view</div>
      <div class="toolbar">
        <input type="text" placeholder="skill name (frontmatter name)" data-bind-input="resolution_name" />
        <button data-act="resolve">show</button>
      </div>
      <div id="resolution-out"></div>`;
  }
  const d = await api("GET", `/api/file?path=${encodeURIComponent(path)}`);
  const fm = (d.report && d.report.parsed) || {};
  const u = d.usage || {};
  return `
    <div class="section-h">Detail — ${escape(path.split("/").slice(-3).join("/"))}</div>
    <div class="editor-shell">
      <div class="editor-pane">
        <h2>Frontmatter</h2>
        <pre class="mono" style="padding: 10px 12px; margin:0;">${escape(JSON.stringify(fm, null, 2))}</pre>
        <h2>Lifecycle (.usage.json)</h2>
        <pre class="mono" style="padding: 10px 12px; margin:0;">${escape(JSON.stringify(u, null, 2))}</pre>
        <h2>Resolution</h2>
        <div class="toolbar">
          <input type="text" value="${escape(fm.name || "")}" data-bind-input="resolution_name" />
          <button data-act="resolve">show</button>
        </div>
        <div id="resolution-out"></div>
      </div>
      <div class="editor-pane">
        <h2>Locks &amp; Curator</h2>
        <div class="toolbar">
          ${d.curation_eligible ? "" : `<span class="dim mono">not curation-eligible (hub-installed / external / protected built-in)</span>`}
        </div>
        <div class="toolbar">
          <button data-act="pin" data-pinned="${u.pinned ? "false" : "true"}">
            ${u.pinned ? "unpin" : "pin"} (pinned=${u.pinned ? "true" : "false"})
          </button>
          <button data-act="archive">archive (→ Hermes .archive/)</button>
          <button data-act="restore">restore</button>
          <button data-act="promote_active">promote → active</button>
          <button data-act="promote_stale">promote → stale</button>
        </div>
        <div class="dim mono" style="padding: 0 12px;">
          pin blocks delete/archive only — NOT patch/edit
          (<span class="mono">skill_manager_tool.py:288</span>).
        </div>
        <h2>Rename / Duplicate</h2>
        <form data-form="rename">
          <div class="toolbar">
            <input type="text" placeholder="new name" data-bind-input="new_name" />
            <button data-act="rename_dry" type="button">scan references</button>
            <button class="primary" type="submit">rename</button>
          </div>
        </form>
        <form data-form="duplicate">
          <div class="toolbar">
            <input type="text" placeholder="new copy name" data-bind-input="dup_name" />
            <button class="primary" type="submit">duplicate</button>
          </div>
        </form>
        <h2>Delete</h2>
        <div class="toolbar">
          <button data-act="delete_soft">soft-delete → external trash</button>
          <button data-act="delete_archive">archive → Hermes .archive/</button>
        </div>
      </div>
    </div>
    <script type="module">
      import { api, toast } from "/static/js/app.js";
      const path = "${escape(path)}";
      const name = ${JSON.stringify(fm.name || "")};
      registerAction("resolve", async () => {
        const v = document.querySelector('input[data-bind-input="resolution_name"]').value.trim();
        if (!v) return;
        const r = await api("GET", "/api/resolution?skill=" + encodeURIComponent(v));
        const out = document.getElementById("resolution-out");
        const rows = []
          .concat(r.local.map(p => ({ p, w: "local", winner: p === r.winner })))
          .concat(r.external.map(p => ({ p, w: "external", winner: p === r.winner })));
        if (!rows.length) out.innerHTML = '<div class="dim mono">no file with frontmatter name ' + v + ' found anywhere</div>';
        else out.innerHTML = rows.map(x => '<div class="resolution-row ' + (x.winner ? "winner" : "loser") + '">'
          + (x.winner ? "★ " : "  ") + x.w + " · " + x.p + '</div>').join("")
            + '<div class="dim mono" style="margin-top:6px;">rule: ' + r.rule + '</div>';
      });
      registerAction("pin", async (d) => {
        if (!name) { toast("no frontmatter name", "danger"); return; }
        const r = await api("POST", "/api/lock", { name, pinned: d.pinned === "true" });
        toast(r.ok ? (d.pinned === "true" ? "pinned" : "unpinned") : (r.detail || "lock failed"));
        render();
      });
      const act = async (action) => {
        if (!name) { toast("no frontmatter name", "danger"); return; }
        const r = await api("POST", "/api/lifecycle", { action, name });
        toast(r.ok ? r.message : (r.detail || "failed"), r.ok ? "ok" : "danger");
        render();
      };
      registerAction("archive", () => act("archive"));
      registerAction("restore", () => act("restore"));
      registerAction("promote_active", () => act("promote_active"));
      registerAction("promote_stale", () => act("promote_stale"));

      // rename + duplicate + delete forms
      document.querySelectorAll("form[data-form='rename']").forEach(f => {
        f.onsubmit = async (e) => {
          e.preventDefault();
          const new_name = f.querySelector('input[data-bind-input="new_name"]').value.trim();
          if (!new_name) return;
          // first dry-run (no approved) → show references
          const dry = await api("POST", "/api/rename", { path, new_name, approved: false });
          const ok = confirm("rename to '" + new_name + "'. References that mention the old name:\n\n"
            + (dry.references.hits.map(h => " · " + h.where + " (" + h.kind + ")").join("\n") || "(none)")
            + "\n\nproceed?");
          if (!ok) return;
          const r = await api("POST", "/api/rename", { path, new_name, approved: true });
          toast(r.ok ? "renamed" : (r.detail || "failed"), r.ok ? "ok" : "danger");
          render();
        };
      });
      document.querySelectorAll("form[data-form='duplicate']").forEach(f => {
        f.onsubmit = async (e) => {
          e.preventDefault();
          const dup_name = f.querySelector('input[data-bind-input="dup_name"]').value.trim();
          if (!dup_name) return;
          const r = await api("POST", "/api/duplicate", { path, new_name: dup_name });
          toast(r.ok ? "duplicated → " + r.new_path : (r.detail || "failed"), r.ok ? "ok" : "danger");
          render();
        };
      });
      registerAction("delete_soft", async () => {
        if (!confirm("soft-delete: move " + path + " to external $STATE/trash/? recoverable.")) return;
        const r = await api("POST", "/api/delete", { path, mode: "soft", approved: true });
        toast(r.ok ? "moved to trash" : (r.error || "failed"), r.ok ? "ok" : "danger");
        render();
      });
      registerAction("delete_archive", async () => {
        if (!confirm("archive: move " + path + " into Hermes' skills/.archive/ — uses Hermes' own archive_skill. recoverable via hermes curator restore.")) return;
        const r = await api("POST", "/api/delete", { path, mode: "archive", approved: true });
        toast(r.ok ? r.message : (r.error || "failed"), r.ok ? "ok" : "danger");
        render();
      });
    </script>
  `;
}

function escape(s) { return String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }