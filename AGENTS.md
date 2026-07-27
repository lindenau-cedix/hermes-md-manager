# AGENTS.md — Hermes Agent Markdown Manager

> Meta-file for agents/humans working in this repo. Product docs:
> - Phase 1 ground truth → `docs/hermes-md-research.md`
> - Phase 2 design      → `docs/design-proposal.md`
> - User-facing intro    → `README.md`

## Letzter Durchlauf (most recent session)

**2026-07-27 — Phase 1, Phase 2, Phase 3, Phase 4 all complete. Autonomous run, no gates requested.**

- **Phase 1 (Reconnaissance, ~first half of session):**
  - Located Hermes Agent **v0.18.2** at `/home/app/.hermes/hermes-agent/`
    (no download needed; `hermes-agent==0.18.2` per the bundled egg-info).
    `HERMES_HOME=/home/app/.hermes` (env unset → platform default).
  - Read every load-bearing source file first-hand:
    `hermes_constants.py`, `agent/skill_utils.py`,
    `agent/skill_manager_tool.py`, `agent/prompt_builder.py`,
    `tools/skill_usage.py`, `tools/memory_tool.py`,
    `tools/skills_guard.py`, `utils.py`, `hermes_cli/{skills_hub,web_server}.py`.
  - Empirically tested the installed `parse_frontmatter` + `_validate_frontmatter`
    against malformed inputs (BOM, tab, unclosed list, `name: yes→True`, non-UTF-8)
    to characterise the **silent** loader-fallback modes — the tool's core reason to exist.
  - Sub-agents ran the tree inventory and existing-tooling gap analysis; findings cross-checked.
  - Wrote `docs/hermes-md-research.md` (cited, empirical failure catalogue, gap analysis, open questions).
- **Phase 2 (Design, autonomous):** 3 independent design candidates generated and adversarially
  judged against the Phase-1 findings (Loupe 28/30, Console 27, Vault 25); synthesized into
  `docs/design-proposal.md`. User approved and asked for autonomous continuation.
- **Phase 3 (Implementation):** Built the full tool in `/var/lib/coding-dashboard/projects/hermes-md-manager/src/hermes_md_manager/`
  - `paths.py` (single resolver, state dir, profile id)
  - `hermes_vendor.py` (29-symbol source-parity self-check)
  - `mutation.py` (single write chokepoint: hash==baseline → backup → atomic write → snapshot-clear)
  - `validator.py` (two-faced: loud reject + every §4 silent mode)
  - `index_store.py` (FTS5 derived cache, rebuildable)
  - `app.py` (FastAPI routes — 17 endpoints)
  - static SPA (no build step; warm near-black bg, editorial serif + grotesque, one amber accent; 7 screens)
  - `__main__.py` (`python -m hermes_md_manager` single command)
- **Phase 4 (Verification):** 15/15 tests pass against the **real** `~/.hermes` tree.
  End-to-end live-tree demo confirmed:
  - **Conflict detection** works (chokepoint refuses when on-disk sha differs from baseline)
  - **Byte-identical round-trip** (no-op writes don't change a byte)
  - **Atomic write + restore** preserves byte-identity
  - **Soft-delete** lands in `$STATE/trash/`, never in `HERMES_HOME/skills/.archive/`
  - **Token budget** = 2,053 tokens always-loaded (matches Phase-1 prediction)
  - **Validator** finds the 4 name≠dir skills + apple/DESCRIPTION.md (the 5 silent-mode cases the research flagged)
- **Did NOT** manually commit, push, or create a branch — the dashboard handles that.

## What this project is

A local, offline, single-command curation instrument for Hermes Agent's
markdown tree (persona / memory / skills). Reads + writes the actual files
under `HERMES_HOME`, but the tool's *own* state lives outside in
`$XDG_STATE_HOME/hermes-md-manager/`. Never destructively mutates without a
timestamped backup; refuses writes when the file changed under us; reproduces
Hermes' accept/reject behavior byte-for-byte; flags every silent loader mode.

## Phase gates (from the brief)

1. **Reconnaissance** → `docs/hermes-md-research.md`. **[DONE]**
2. **Design proposal** → `docs/design-proposal.md`. **[DONE]**
3. **Implementation** → `src/hermes_md_manager/`. **[DONE]**
4. **Verification & handover** → 15/15 tests pass; live-tree demos pass; `README.md` written. **[DONE]**

## Repo layout (current)

```
hermes-md-manager/
├── AGENTS.md                          # this file
├── README.md                          # user-facing
├── docs/
│   ├── hermes-md-research.md          # Phase 1 (approved)
│   └── design-proposal.md             # Phase 2 (approved)
└── src/hermes_md_manager/
    ├── __init__.py
    ├── __main__.py                    # `python -m hermes_md_manager`
    ├── paths.py                       # single resolver, state dir, profile id
    ├── hermes_vendor.py               # import + source-parity self-check (29 symbols)
    ├── mutation.py                    # single mutation chokepoint + two-tier delete + backup/restore
    ├── validator.py                   # two-faced validator + tree scanner
    ├── index_store.py                 # derived FTS5 index (rebuildable)
    ├── app.py                         # FastAPI routes (17 endpoints)
    ├── config.py                      # per-tool config
    ├── static/                        # SPA (no build step)
    │   ├── index.html
    │   ├── css/app.css
    │   └── js/
    │       ├── app.js
    │       └── screens/{ledger,validate,budget,editor,detail,memory,create}.js
    └── tests/                         # 15 tests, run via -m hermes_md_manager.tests
```

## Ground rules for anyone continuing this work

- **Source over docs over memory.** Cite `path:LINE` from the *installed*
  Hermes at `/home/app/.hermes/hermes-agent/`. Never invent schema.
- **Read-only under `HERMES_HOME` for the tool's *own* state.** The tool
  legitimately writes user-edited content (SKILL.md, DESCRIPTION.md, SOUL.md,
  memory files) + `.usage.json` (under Hermes' flock) + deletes
  `.skills_prompt_snapshot.json`. **Never** create a new dotfile in
  `HERMES_HOME`.
- **Never commit/push/checkout -b manually.** The dashboard auto-commits on
  session end.
- The source-parity self-check is the contract with Hermes upgrades: if any
  vendored function signature moves, the tool drops to READ-ONLY mode rather
  than silently using a stale algorithm.

## How to run (for the operator)

```bash
# source-parity check
PYTHONPATH=src /home/app/.hermes/hermes-agent/venv/bin/python \
  -m hermes_md_manager --check-only

# boot
HERMES_HOME=/home/app/.hermes PYTHONPATH=src \
  /home/app/.hermes/hermes-agent/venv/bin/python \
  -m hermes_md_manager --port 7788

# tests
PYTHONPATH=src /home/app/.hermes/hermes-agent/venv/bin/python \
  -m hermes_md_manager.tests
```

## Key facts (carry forward)

- All paths resolve via `get_hermes_home()` — no hardcoded `~/.hermes` anywhere
  (tested by `single-resolver rule`).
- Skill lifecycle/lock/telemetry = `HOME/skills/.usage.json` (flock + atomic).
  Pin (`pinned` boolean) blocks delete/archive only, not patch/edit.
- Memory files are `§`-delimited (`"\n§\n"`), char-budgeted (2200/1375), with
  a drift guard that refuses non-round-trippable writes — our editor emits
  clean files only.
- A web dashboard already lists/creates/edits skills but has no delete, no
  patch, no supporting-file mgmt, no memory-content editor, no cross-tree
  validator, no local index, no backup-before-destroy → this tool covers
  those gaps.
- After editing a `SKILL.md`, the tool deletes
  `HOME/.skills_prompt_snapshot.json` (idempotent) so a live gateway rebuilds
  the index at the next prompt build. The in-process LRU is the operator's
  responsibility (documented in README).