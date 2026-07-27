# AGENTS.md — Hermes Agent Markdown Manager

> Meta-file for agents/humans working in this repo. The *product* research lives
> in `docs/hermes-md-research.md`. This file tracks project state & process.

## Letzter Durchlauf (most recent session)

**2026-07-27 — Phase 1 + Phase 2 complete; awaiting user review of Phase 2.**

- **Phase 1 (DONE, approved by user):** Located Hermes v0.18.2 at
  `/home/app/.hermes/hermes-agent/` (no download needed); `HERMES_HOME =
  /home/app/.hermes` (env unset → default). Read the
  discovery/parse/validate/load/write paths **first-hand**; empirically tested
  the installed frontmatter parser + validator against malformed input. Sole
  deliverable: **`docs/hermes-md-research.md`**. Key corrections to the
  brief's prior beliefs: persona file is `SOUL.md` (raw prose, no
  frontmatter); lock = `pinned` in `.usage.json` (blocks delete/archive only,
  not patch/edit); lifecycle state lives in `.usage.json` (NOT SQLite); skill
  *index* (name+desc) loads every session (bodies are on-demand); the loader
  never rejects — malformed YAML silently degrades.
- **Phase 2 (DONE — `docs/design-proposal.md`):** Three independent design
  candidates generated (Vault / Loupe / Console) and adversarially judged
  (Loupe 28/30, Console 27, Vault 25). Synthesis adopts Loupe's
  stateless-about-content spine + Console's UI discipline + the three-color
  validity badge from Vault, and inherits the single mutation chokepoint from
  all three. Hard stops at Phase-1 citations throughout.
- **Did NOT** design outside the brief's fixed constraints, **did NOT** touch
  `HERMES_HOME`, **did NOT** start implementation.
- **Next:** user reviews `docs/design-proposal.md`. On approval → Phase 3
  implementation, then Phase 4 verification & `README.md`.

## What this project is

A local, offline management tool for curating Hermes Agent's markdown tree
(persona / memory / skills) safely — validated against how the *installed*
Hermes actually parses and writes these files. Target: local web app
(FastAPI + static SPA on 127.0.0.1), UI in English.

## Phase gates (from the brief)

1. **Reconnaissance** → `docs/hermes-md-research.md`. **[APPROVED]**
2. **Design proposal** → `docs/design-proposal.md`. **[awaiting review]**
3. **Implementation** (safety-first: atomic writes, external backups, conflict
   detection, diff-before-commit, dry-run, round-trip fidelity). **[not started]**
4. **Verification & handover** (validator run, conflict-detection demo,
   round-trip test, `README.md`). **[not started]**

## Repo layout (current)

```
hermes-md-manager/
├── AGENTS.md                     # this file
├── README.md                     # stub (pre-existing)
└── docs/
    ├── hermes-md-research.md     # Phase 1 deliverable (APPROVED)
    └── design-proposal.md        # Phase 2 deliverable (awaiting review)
```

## Ground rules for anyone continuing this work

- **Source over docs over memory.** Cite `path:LINE` from the *installed*
  Hermes at `/home/app/.hermes/hermes-agent/`. Never invent schema.
- **Read-only under `HERMES_HOME` until the user approves a build.**
- **Do NOT `git add/commit/push/checkout -b`.** The dashboard auto-commits when
  the session ends; a manual commit would break that hand-off.
- Interactive session — ask before making risky assumptions.

## Key facts to carry forward (see `docs/hermes-md-research.md` for citations)

- Paths resolve via `get_hermes_home()` — no hardcoded `~/.hermes` anywhere.
- Skill lifecycle/lock/telemetry = `HOME/skills/.usage.json` (flock + atomic).
- Memory files are `§`-delimited (`"\n§\n"`), char-budgeted, with a drift guard
  that refuses non-round-trippable writes — our editor must emit clean files.
- A web dashboard already lists/creates/edits skills but has no delete, no
  patch, no supporting-file mgmt, no memory-content editor, no cross-tree
  validator, no local index, and no backup-before-destroy → that's the gap.
- Reuse Hermes' own atomic writer pattern (`SRC/utils.py:91` `atomic_replace`:
  temp+fsync+os.replace, symlink/mode/owner preserving).
- After editing a `SKILL.md`, clear `HOME/.skills_prompt_snapshot.json` so a
  live gateway doesn't serve a stale index.
