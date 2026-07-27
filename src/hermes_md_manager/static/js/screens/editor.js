// Edit — schema-driven frontmatter form + raw markdown body + live validate.
// Save routes through the single mutation chokepoint (/api/write).

import { api, navigate, toast, registerAction } from "/static/js/app.js";

export async function renderEditor(state) {
  const path = state.selected;
  if (!path) {
    return `<div class="section-h">Edit</div><div class="dim">select a file from the ledger.</div>`;
  }
  const detail = await api("GET", `/api/file?path=${encodeURIComponent(path)}`);
  const raw = await api("GET", `/api/file/raw?path=${encodeURIComponent(path)}`);
  const baseline = raw.headers ? raw.headers.get("X-Sha256") : "";
  state.baseline = baseline;
  const text = await raw.text();
  state.editorBuffer = text;

  // Render the frontmatter as a typed form (only known fields). The raw text
  // area below lets the user edit anything else verbatim.
  const parsed = (detail.report && detail.report.parsed) || {};
  const fm = parsed;

  const fields = [
    { key: "name", type: "text", required: true },
    { key: "description", type: "textarea", required: true },
    { key: "version", type: "text" },
    { key: "author", type: "text" },
    { key: "license", type: "text" },
    { key: "platforms", type: "list" },
    { key: "environments", type: "list" },
    { key: "tags", type: "list" },
    { key: "homepage", type: "text" },
    { key: "category", type: "text" },
  ];
  const known = new Set(fields.map(f => f.key));
  const otherFm = Object.fromEntries(Object.entries(fm).filter(([k]) => !known.has(k) && k !== "metadata" && k !== "prerequisites" && k !== "dependencies" && k !== "setup" && k !== "compatibility" && k !== "required_credential_files" && k !== "triggers" && k !== "title"));
  const otherFmStr = JSON.stringify(otherFm, null, 2);
  const metadataRaw = fm.metadata ? JSON.stringify(fm.metadata, null, 2) : "";
  const fmHtml = fields.map(f => {
    let v = fm[f.key];
    if (v === undefined || v === null) v = "";
    if (Array.isArray(v)) v = v.join(", ");
    if (typeof v === "object") v = JSON.stringify(v);
    if (f.type === "textarea") {
      return `<label><span class="k">${f.key}</span><textarea data-bind-input="fm.${f.key}" rows="3">${escape(v)}</textarea></label>`;
    }
    if (f.type === "list") {
      return `<label><span class="k">${f.key}</span><input type="text" data-bind-input="fm.${f.key}" placeholder="comma-separated" value="${escape(v)}" /></label>`;
    }
    return `<label><span class="k">${f.key}</span><input type="text" data-bind-input="fm.${f.key}" value="${escape(v)}" /></label>`;
  }).join("");

  const findingsHtml = (detail.report && detail.report.findings || []).map(f => `
    <div class="finding">
      <span class="sev-${f.severity === "reject" ? "reject" : f.severity === "silent_corruption" ? "silent" : "advisory"}">${label(f.severity)}</span>
      <span class="rule">${escape(f.rule)}</span>
      <div>${escape(f.message)}</div>
      ${f.fix ? `<div class="fix">fix: ${escape(f.fix)}</div>` : ""}
    </div>
  `).join("");

  return `
    <div class="section-h">Edit — ${escape(path.split("/").slice(-3).join("/"))}</div>
    <div class="dim mono">baseline sha256: ${baseline.slice(0, 12)}… (captured at read-time; the write chokepoint will refuse if the file changed under us)</div>
    <div class="editor-shell" style="margin-top:10px;">
      <div class="editor-pane">
        <h2>Frontmatter (schema-driven)</h2>
        <div class="fm-form">${fmHtml}</div>
        <h2>Frontmatter — metadata.hermes (raw JSON)</h2>
        <div class="fm-form"><label><span class="k">metadata</span><textarea data-bind-input="fm.metadata" rows="6">${escape(metadataRaw)}</textarea></label></div>
        <h2>Other frontmatter (raw JSON)</h2>
        <div class="fm-form"><label><span class="k">extras</span><textarea data-bind-input="fm.other" rows="4">${escape(otherFmStr)}</textarea></label></div>
      </div>
      <div class="editor-pane">
        <h2>Raw markdown (full SKILL.md / DESCRIPTION.md)</h2>
        <textarea data-bind-input="body" rows="22">${escape(text)}</textarea>
        <h2>Findings</h2>
        <div class="findings">${findingsHtml || `<div class="dim">no findings</div>`}</div>
        <div class="toolbar">
          <button data-act="rev" class="primary">re-validate</button>
          <button data-act="save" class="primary">save (diff + write)</button>
          <button data-act="cancel">cancel</button>
          <span class="dim mono" style="margin-left:auto;">buffer: <span id="buf-bytes">${text.length}</span> chars</span>
        </div>
      </div>
    </div>
    <script type="module">
      import { api, toast, navigate } from "/static/js/app.js";
      registerAction("rev", async () => {
        // re-validate the current buffer
        const r = await api("POST", "/api/validate_one", { path: "${escape(path)}" });
        toast("re-validated: " + r.findings.length + " finding(s), badge " + r.badge);
        render();
      });
      registerAction("save", async () => {
        const content = document.querySelector('textarea[data-bind-input="body"]').value;
        const r = await api("POST", "/api/write", {
          path: "${escape(path)}",
          content,
          baseline_sha256: "${escape(baseline)}",
          approved: true,
        });
        if (r.ok) {
          toast("saved · backup " + r.backup_id);
          navigate("ledger");
        } else {
          toast(r.error || "save failed", "danger");
        }
      });
      registerAction("cancel", () => { navigate("ledger"); });
    </script>
  `;
}

function label(s) {
  return s === "reject" ? "REJ" : s === "silent_corruption" ? "SIL" : "ADV";
}
function escape(s) { return String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }