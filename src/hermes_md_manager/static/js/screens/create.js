// Create / Import-Export.
// Create picks a known-green real skill as a template; import validates first.

import { api, toast, registerAction } from "/static/js/app.js";

export function renderCreate(state) {
  // pick three real, valid skills as templates (from the loaded tree)
  const candidates = (state.tree || []).filter(f =>
    f.kind === "skill" && f.badge === "green" && f.name
  ).slice(0, 12);
  const templateOptions = candidates.map(c =>
    `<option value="${escape(c.path)}">${escape(c.name)} (${escape(c.path.split("/").slice(-3,-1).join("/"))})</option>`
  ).join("");
  return `
    <div class="section-h">Create — new skill from a real template</div>
    <div class="dim mono" style="margin-bottom:8px;">templates are taken from real, valid skills in your tree (badge green). new dir name + frontmatter name are set together to avoid the dual-identity footgun.</div>
    <form data-form="create">
      <div class="toolbar">
        <label><span class="dim mono">name</span><input type="text" data-bind-input="name" placeholder="my-new-skill" /></label>
        <label><span class="dim mono">category</span><input type="text" data-bind-input="category" placeholder="(optional, single dir)" /></label>
      </div>
      <div class="toolbar">
        <label><span class="dim mono">template from</span><select data-bind-input="template">${templateOptions}</select></label>
        <button data-act="load_template" type="button">load template</button>
      </div>
      <textarea rows="18" data-bind-input="content"></textarea>
      <div class="toolbar">
        <button class="primary" type="submit">create skill</button>
      </div>
    </form>

    <div class="section-h">Export a skill folder</div>
    <form data-form="export">
      <div class="toolbar">
        <input type="text" placeholder="path to SKILL.md or its dir" data-bind-input="export_path" />
        <button class="primary" type="submit">download .tar.gz</button>
      </div>
    </form>

    <div class="section-h">Import a skill archive</div>
    <div class="dim mono" style="margin-bottom:8px;">the archive is VALIDATED before anything is written. the dry-run mode shows what would be extracted.</div>
    <form data-form="import">
      <div class="toolbar">
        <label><span class="dim mono">name on disk</span><input type="text" data-bind-input="import_name" placeholder="my-skill" /></label>
        <label><span class="dim mono">archive (.tar.gz base64)</span><input type="file" data-bind-input="import_file" accept=".tar.gz,.tgz,application/gzip" /></label>
      </div>
      <div class="toolbar">
        <button data-act="import_dry" type="button">dry run (validate only)</button>
        <button class="primary" type="submit">import</button>
      </div>
    </form>
    <script type="module">
      import { api, toast, registerAction, state } from "/static/js/app.js";
      let templateContent = "";
      registerAction("load_template", async () => {
        const path = document.querySelector('select[data-bind-input="template"]').value;
        const r = await fetch("/api/file/raw?path=" + encodeURIComponent(path));
        templateContent = await r.text();
        document.querySelector('textarea[data-bind-input="content"]').value = templateContent;
        toast("template loaded");
      });
      document.querySelectorAll("form[data-form='create']").forEach(f => {
        f.onsubmit = async (e) => {
          e.preventDefault();
          const name = f.querySelector('input[data-bind-input="name"]').value.trim();
          const category = f.querySelector('input[data-bind-input="category"]').value.trim();
          const content = f.querySelector('textarea[data-bind-input="content"]').value;
          if (!name || !content) { toast("name + content required", "danger"); return; }
          const r = await api("POST", "/api/create", { kind: "skill", name, category, content });
          toast(r.ok ? "created" : (r.error || "failed"), r.ok ? "ok" : "danger");
        };
      });
      document.querySelectorAll("form[data-form='export']").forEach(f => {
        f.onsubmit = async (e) => {
          e.preventDefault();
          const path = f.querySelector('input[data-bind-input="export_path"]').value.trim();
          if (!path) return;
          const r = await fetch("/api/export?path=" + encodeURIComponent(path));
          if (!r.ok) { toast("export failed", "danger"); return; }
          const blob = await r.blob();
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = path.split("/").slice(-2)[0] + ".tar.gz";
          a.click();
          URL.revokeObjectURL(url);
        };
      });
      const readFile = (f) => new Promise((res, rej) => {
        const reader = new FileReader();
        reader.onload = () => res(reader.result);
        reader.onerror = rej;
        reader.readAsDataURL(f);
      });
      const importArchive = async (dry) => {
        const name = document.querySelector('input[data-bind-input="import_name"]').value.trim();
        const fileEl = document.querySelector('input[data-bind-input="import_file"]');
        const file = fileEl.files[0];
        if (!name || !file) { toast("name + file required", "danger"); return; }
        const dataUrl = await readFile(file);
        const b64 = dataUrl.split(",")[1];
        const r = await api("POST", "/api/import", { name, archive_b64: b64, dry_run: dry });
        toast(r.ok ? (dry ? "dry-run ok · " + r.members + " members" : "imported → " + r.path) : (r.detail || "failed"), r.ok ? "ok" : "danger");
      };
      registerAction("import_dry", () => importArchive(true));
      document.querySelectorAll("form[data-form='import']").forEach(f => {
        f.onsubmit = async (e) => { e.preventDefault(); importArchive(false); };
      });
    </script>
  `;
}

function escape(s) { return String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }