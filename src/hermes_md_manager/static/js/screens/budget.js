// Token Budget — always-loaded total + per-file breakdown.
// Uses Hermes' own ~4 chars/token heuristic (agent/prompt_builder.py:1181).

import { api } from "/static/js/app.js";

export async function renderBudget(state) {
  if (!state.budget) state.budget = await api("GET", "/api/budget");
  const b = state.budget;
  const rows = b.breakdown.map(r => `
    <tr>
      <td class="path mono">${escape(r.path)}</td>
      <td>${r.kind}</td>
      <td class="num">${formatNumber(r.chars)}</td>
      <td class="num">${r.tokens_est}</td>
    </tr>`).join("");
  return `
    <div class="section-h">Token budget — always-loaded cost</div>
    <div class="kpi-strip">
      <div class="kpi"><span class="v accent">${formatNumber(b.always_loaded_chars)}</span><span class="l">always-loaded chars</span></div>
      <div class="kpi"><span class="v accent">${b.tokens_est.toLocaleString()}</span><span class="l">est. tokens (1 turn)</span></div>
      <div class="kpi"><span class="v">${formatNumber(b.persona_chars)}</span><span class="l">persona (SOUL.md)</span></div>
      <div class="kpi"><span class="v">${formatNumber(b.memory_chars)}</span><span class="l">memory snapshot</span></div>
      <div class="kpi"><span class="v">${formatNumber(b.index_chars)}</span><span class="l">skills index</span></div>
    </div>
    <div class="dim mono">heuristic: ${b.chars_per_token} chars/token (Hermes' own default — agent/prompt_builder.py:1181).</div>
    <div class="dim mono" style="margin-top:6px;">bodies of SKILL.md are NOT counted — only the per-skill <code>name: description</code> line is in the index, loaded every turn.</div>
    <table class="ledger" style="margin-top:14px;">
      <thead><tr><th>path</th><th>kind</th><th class="num">chars</th><th class="num">tokens (est.)</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function formatNumber(n) { return Number(n || 0).toLocaleString(); }
function escape(s) { return String(s == null ? "" : s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }