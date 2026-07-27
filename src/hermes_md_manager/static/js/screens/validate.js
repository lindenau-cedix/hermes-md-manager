// Validate — whole-tree lint, fix queue with n/p navigation.

import { navigate, registerAction, api, toast } from "/static/js/app.js";

export function renderValidate(state) {
  const counts = state.counts || { green: 0, amber: 0, red: 0 };
  const findings = state.findings || [];
  const sevOrder = { reject: 0, silent_corruption: 1, advisory: 2 };
  findings.sort((a, b) => (sevOrder[a.severity] ?? 9) - (sevOrder[b.severity] ?? 9));
  const rows = findings.map(f =>
    `<tr data-act="open" data-path="${escape(f.path)}">
       <td><span class="badge ${f.severity === "reject" ? "red" : f.severity === "silent_corruption" ? "amber" : "green"}">${label(f.severity)}</span></td>
       <td class="mono">${escape(f.rule)}</td>
       <td class="path mono">${escape(f.path.split("/").slice(-3).join("/"))}</td>
       <td>${escape(f.message)}</td>
       <td class="dim">${escape(f.fix || "")}</td>
     </tr>`
  ).join("");
  return `
    <div class="section-h">Validate — whole-tree lint</div>
    <div class="kpi-strip">
      <div class="kpi"><span class="v">${counts.green}</span><span class="l">clean</span></div>
      <div class="kpi"><span class="v" style="color:var(--warn);">${counts.amber}</span><span class="l">silent</span></div>
      <div class="kpi"><span class="v ${counts.red ? "danger" : ""}">${counts.red}</span><span class="l">rejected</span></div>
      <div class="kpi"><span class="v">${findings.length}</span><span class="l">total findings</span></div>
    </div>
    <div class="toolbar">
      <button data-act="rerun">re-run</button>
      <span class="dim mono">two-faced: vendored <code>parse_frontmatter</code> (loader+silent) + <code>_validate_frontmatter</code> (loud reject)</span>
    </div>
    <table class="ledger">
      <thead><tr><th>sev</th><th>rule</th><th>path</th><th>message</th><th>suggested fix</th></tr></thead>
      <tbody>${rows || `<tr><td colspan="5" class="dim">no findings — tree is clean</td></tr>`}</tbody>
    </table>
    <script type="module">
      import { registerAction, navigate, toast } from "/static/js/app.js";
      registerAction("open", (d) => { navigate("editor", { selected: d.path }); });
      registerAction("rerun", async () => {
        const r = await api("POST", "/api/validate");
        state.findings = r.findings; state.counts = r.counts; render();
        toast("re-validated");
      });
    </script>
  `;
}

function label(s) {
  return s === "reject" ? "REJ" : s === "silent_corruption" ? "SIL" : "ADV";
}
function escape(s) { return String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }