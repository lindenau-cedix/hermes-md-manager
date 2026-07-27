# AGENTS.md — Hermes Agent Markdown Manager

> Meta-file for agents/humans working in this repo. The *product* research lives
> in `docs/hermes-md-research.md`. This file tracks project state & process.

## Letzter Durchlauf (most recent session)

**2026-07-27 — Phase 1 (Reconnaissance) complete; awaiting user review.**

- Located the installed Hermes source (no download needed): `HERMES_SOURCE =
  /home/app/.hermes/hermes-agent/` (v0.18.2, Nous Research). `HERMES_HOME =
  /home/app/.hermes` (env unset → platform default; single default profile).
- Read the discovery/parse/validate/load/write paths **first-hand** and
  **empirically tested** the installed frontmatter parser + validator against
  malformed input (probe script in the session scratchpad, not committed).
- Wrote the sole Phase-1 deliverable: **`docs/hermes-md-research.md`** — ground
  truth table, frontmatter schema, write-path map, empirical failure catalogue,
  gap analysis, live-tree inventory, and an honest open-questions section.
- **Did NOT** design, build, or touch anything under `HERMES_HOME`.
- Biggest corrections vs. the brief's prior beliefs: the persona file is
  `SOUL.md` (raw prose, no frontmatter); the lock is `pinned` in
  `.usage.json` (**not** frontmatter) and only blocks delete/archive, not
  content rewrites; lifecycle state is `.usage.json`, **not** SQLite; the
  skill *index* (name+desc) is loaded every session (skills aren't free); the
  loader **never rejects** — malformed YAML silently degrades.
- **Next:** user reviews `docs/hermes-md-research.md`. On approval → Phase 2
  (design proposal, < 2 pages, no code), then hard stop again.

## What this project is

A local, offline management tool for curating Hermes Agent's markdown tree
(persona / memory / skills) safely — validated against how the *installed*
Hermes actually parses and writes these files. Target: local web app
(FastAPI + static SPA on 127.0.0.1), UI in English.

## Phase gates (from the brief)

1. **Reconnaissance** → `docs/hermes-md-research.md`. **[DONE — awaiting review]**
2. **Design proposal** (short, no code). **[BLOCKED on Phase-1 approval]**
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
    └── hermes-md-research.md     # Phase 1 deliverable
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
