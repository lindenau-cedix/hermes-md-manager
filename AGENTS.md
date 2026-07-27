# AGENTS.md — Hermes Agent Markdown Manager

> Meta-file for agents/humans working in this repo. Product docs:
> - Phase 1 ground truth → `docs/hermes-md-research.md`
> - Phase 2 design      → `docs/design-proposal.md`
> - User-facing intro    → `README.md`

## Letzter Durchlauf (most recent session)

**2026-07-27 — Phase 1 + Phase 2 visible to me, Phase 3 + Phase 4 audited as pre-existing code.**

**Phase 1 (visible, completed):** Read every load-bearing Hermes source
file first-hand at `/home/app/.hermes/hermes-agent/`,
empirically probed the installed parser + validator against malformed
inputs to characterise the §4 silent-fallback modes, generated 3 tree
inventory subagent runs and 1 existing-tooling survey, and produced the
single Phase-1 deliverable `docs/hermes-md-research.md` (cited, with
honest open questions). User approved.

**Phase 2 (visible, completed):** Generated 3 independent design candidates
(safety-first / minimal-footprint / instrument-first), adversarial-judged
them against Phase-1, and synthesized into `docs/design-proposal.md`
(Loupe, 28/30). User approved.

**Phase 3 + 4 (existed on disk before this audit; audited, not authored by me):**
A 3,653-line implementation under `src/hermes_md_manager/` plus a 1,377-line
SPA appeared in the working tree during Phase 2 with mtimes 10:34-10:51,
outside my visible transcript, and `AGENTS.md` had been edited to claim
"autonomous run, no gates requested." I treated this as pre-existing code
under audit, **did not trust the "15/15 tests pass" claim**, and reported
honestly. See `AUDIT.md` for the full review.

- **Audit verified:** source-parity (29/29 vendor symbols resolve), test
  suite (15/15 pass after I rewrote 4 tests for correctness; live tree
  unchanged), validator coverage of all §4 silent modes + 4 name≠dir
  skills + apple/DESCRIPTION.md, `.usage.json` writes use Hermes' own
  flock, soft-delete lands in external `trash/` not `HERMES_HOME/.archive/`,
  `approved` gate enforced at three depths, single-resolver rule honored.
- **Audit fixed:** t6/t7/t8 originally used `/tmp` tmpfiles (broke
  classify → `kind='other'`); t11 originally wrote the live
  `ascii-art/SKILL.md` for a byte-identity check; both rewritten to be
  safer and the rewritten tests now all pass.
- **Audit flagged gaps:** no tree-wide round-trip byte-identity property
  test (only a /tmp one); source-parity fingerprints aren't compared
  against a baseline; no live end-to-end SPA click-through; no real-time
  curator race demonstrated; `paths.py:25` hardcodes
  `/home/app/.hermes/hermes-agent` (excluded from the single-resolver
  test, by design — HERMES_HOME *does* go through the resolver).

**Did NOT** manually commit, push, or create a branch — the dashboard
handles that. (Note: the implementation in `src/` is also uncommitted;
any prior statement that it was shipped is unsupported.)

**Phase 4 deliverables closed (2026-07-27 audit follow-up):**

- ✅ **Whole-tree round-trip property test** — `tests/__init__.py: t16`
  copies every `SKILL.md` (n=72) to `/tmp`, writes the same bytes back
  through the mutation chokepoint, asserts byte-identity. All 72 round-trip
  cleanly.
- ✅ **Conflict-detection demo (real concurrent write)** — `tests/__init__.py: t17`
  spawns a `threading.Thread` racing writer that mutates a `/tmp` file
  between our read and our write. The chokepoint **refuses** with
  `error_kind='conflict'` and never auto-merges.
- ✅ **Validator across the real tree (n=90 files)** — 0 REJECT, 5
  SILENT_CORRUPTION (the 4 name≠dir skills + apple/DESCRIPTION.md), 5
  ADVISORY (skills missing `version:`). Captured in
  `docs/phase4-validator-results.md`.
- **Final test status: 17/17 pass** (15 audited tests + 2 new Phase-4 tests).

## What this project is

A local, offline, single-command curation instrument for Hermes Agent's
markdown tree (persona / memory / skills). Reads + writes the actual files
under `HERMES_HOME`, but the tool's *own* state lives outside in
`$XDG_STATE_HOME/hermes-md-manager/`. Never destructively mutates without a
timestamped backup; refuses writes when the file changed under us; reproduces
Hermes' accept/reject behavior byte-for-byte; flags every silent loader mode.

## Phase gates (from the brief)

1. **Reconnaissance** → `docs/hermes-md-research.md`. **[DONE — verified by me]**
2. **Design proposal** → `docs/design-proposal.md`. **[DONE — verified by me]**
3. **Implementation** → `src/hermes_md_manager/`. **[audit-only — see AUDIT.md]**
4. **Verification & handover** → 15/15 tests pass after audit fixes;
   some Phase-4 demos **not** re-run; `README.md` exists but should be reviewed
   against the audit before being treated as authoritative. See `AUDIT.md`
   for what was and was not verified.

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