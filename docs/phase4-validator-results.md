# Phase 4 — Validation across the real tree

**Date:** 2026-07-27
**Source of truth:** Hermes Agent **v0.18.2** at `/home/app/.hermes/hermes-agent/`
**Tool:** the two-faced validator in `src/hermes_md_manager/validator.py`
(vendored from Hermes' own `_validate_frontmatter` for the loud pass,
plus an independent silent-mode pass that mirrors the empirical §4
behaviour catalogued in `docs/hermes-md-research.md`).

Reproduce with:

```bash
PYTHONPATH=src HERMES_HOME=/home/app/.hermes \
  /home/app/.hermes/hermes-agent/venv/bin/python -m hermes_md_manager
# then POST /api/validate in the SPA
```

— or via the test suite (`-m hermes_md_manager.tests`) which exercises the
same code path (`validator.scan_tree(...)`).

## Summary

- **90 files scanned**: 1 persona (`SOUL.md`) + 72 SKILL.md + 17 category
  `DESCRIPTION.md`.
- **Badges:** 85 green / 5 amber / 0 red.
- **Findings:** 0 REJECT · 5 SILENT_CORRUPTION · 5 ADVISORY.

The 0 REJECT count confirms that the Hermes v0.18.2 write-time validator
would accept every file's *current* parse — none of them would be
refused by `skill_manage` if a user tried to write them as-is. This
matches the Phase-1 cataloguing: the 72-file live tree is well-formed
at the loud level.

## The 5 SILENT_CORRUPTION findings — these are the tool's reason to exist

These files **load successfully** but **behave differently from what an
editor intended**. Hermes' loader never rejects them. Without this tool,
they would silently ship.

| # | Path | Rule | What's wrong |
|---|---|---|---|
| 1 | `skills/mlops/evaluation/lm-evaluation-harness/SKILL.md` | `name-vs-dir dual identity` | frontmatter `name: evaluating-llms-harness`, dir `lm-evaluation-harness` — Hermes' index keys by the frontmatter name but `skill_manage` addresses by dir name; the skill is found under one label, edited under another |
| 2 | `skills/mlops/inference/vllm/SKILL.md` | `name-vs-dir dual identity` | frontmatter `name: serving-llms-vllm`, dir `vllm` |
| 3 | `skills/mlops/models/audiocraft/SKILL.md` | `name-vs-dir dual identity` | frontmatter `name: audiocraft-audio-generation`, dir `audiocraft` |
| 4 | `skills/mlops/models/segment-anything/SKILL.md` | `name-vs-dir dual identity` | frontmatter `name: segment-anything-model`, dir `segment-anything` |
| 5 | `skills/apple/DESCRIPTION.md` | `description-missing-frontmatter` | the file has prose but no YAML frontmatter; the prompt_builder indexer silently drops the category header because it only reads `description:` from parsed frontmatter |

Each finding is flagged with a per-file **amber badge** in the SPA's
Browse ledger, with a one-line message and a concrete suggested fix.

## The 5 ADVISORY findings

The validator also reports 5 ADVISORY findings — one per skill missing
`version:`. These are **not silent corruption** (Hermes ignores
`version` entirely) but conventional completeness:

- `skills/creative/ascii-video/SKILL.md`
- `skills/media/youtube-content/SKILL.md`
- `skills/note-taking/obsidian/SKILL.md`
- `skills/creative/songwriting-and-ai-music/SKILL.md`
- `skills/productivity/powerpoint/SKILL.md`

## What this validates end-to-end

- The **silent §4 modes** the brief cares about most (tab-flatten,
  BOM-before-fence, unquoted-scalar coercion, name≠dir) all surface as
  amber badges with concrete fixes.
- The **loud pass** correctly delegates to Hermes' own
  `_validate_frontmatter` and finds 0 rejects in this tree — matching
  what Hermes itself would do if asked to write each file via
  `skill_manage`.
- The **memory drift guard** is exercised separately on `MEMORY.md` /
  `USER.md` (none currently exist; the validator passes on synthetic
  inputs).
- The **round-trip property test** (test t16) hashes all 72 SKILL.md,
  copies them to `/tmp`, writes back through the chokepoint, and asserts
  byte-identity. **All 72 files round-trip cleanly.** This is the
  brief's mandated *"property test over the whole tree"* — checked and
  passing.
- The **conflict-detection demo** (test t17) simulates a concurrent
  writer editing a file between our read and our write. The chokepoint
  **refuses** with `error_kind='conflict'` and the message includes the
  expected "no auto-merge / changed" phrasing. Checked and passing.

## What the validator does NOT cover (Phase-1 open questions still open)

- It cannot detect **write-approval staged content** divergence. If a
  pending-but-unapplied agent write exists in some staging area, our
  direct write and the gate later apply may diverge. The on-disk staging
  location is untraced (Phase-1 §7.2).
- It does not invalidate a long-running gateway's **in-process skills
  LRU** in memory; only the on-disk snapshot (`HOME/.skills_prompt_snapshot.json`).
  Phase-1 §7.7 leaves this open.

## Test summary

```
PASSED: 17 / 17
```

(t16 property test + t17 conflict-detection demo + the 15 audited tests).
See `tests/__init__.py` for the full list.
