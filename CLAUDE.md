# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A local, offline, single-command curation instrument for **Hermes Agent's
markdown tree** — `~/.hermes/SOUL.md`, `~/.hermes/memories/{MEMORY,USER}.md`,
and every `~/.hermes/skills/**/SKILL.md`. Built for Hermes Agent **v0.18.2**
installed at `/home/app/.hermes/hermes-agent/`. The tool exists because
Hermes' own YAML frontmatter loader never rejects on malformed input
(missing closing fence, tab indent, BOM, `name: yes` → Python `True`,
unclosed `[`, name≠dir dual identity) — these load **silently corrupted**.
The tool catches them.

**Read these first, in this order, before touching anything:**

1. `docs/hermes-md-research.md` — the cited ground truth. Every implementation
   choice traces back to a path:LINE in this doc. Read the §0 executive
   summary, §2.2 schema, §3 write-path map, §4 failure catalogue.
2. `docs/design-proposal.md` — the design (Loupe, 28/30 from adversarial panel).
3. `README.md` — user-facing run commands + dependencies.
4. `AUDIT.md` — what was verified vs. what is claimed; what's still open.

## Commands

All commands assume the Hermes venv (it ships FastAPI/uvicorn/ruamel):

```bash
# Source-parity self-check (no server; read-only)
PYTHONPATH=src /home/app/.hermes/hermes-agent/venv/bin/python \
  -m hermes_md_manager --check-only

# Boot the FastAPI app on 127.0.0.1:7788 (loopback only; per-boot CSRF token)
HERMES_HOME=/home/app/.hermes PYTHONPATH=src \
  /home/app/.hermes/hermes-agent/venv/bin/python \
  -m hermes_md_manager --port 7788

# Run the full test suite (17 tests, runs against the live tree but is read-only)
PYTHONPATH=src HERMES_HOME=/home/app/.hermes \
  /home/app/.hermes/hermes-agent/venv/bin/python \
  -m hermes_md_manager.tests
```

There is no linter, formatter, or build step. There is no `pip install`,
no `node_modules`, no bundler. The single SPA dependency is no dependency
(vanilla ES modules + one tiny Preact via CDN-vendored file — see the
`static/` dir).

## Architecture at a glance — the safety spine

The whole tool funnels **every mutation** through one chokepoint so the
safety properties are impossible to bypass. Reading in dependency order:

```
app.py                     # 17 FastAPI routes; ALL mutating routes require
                           # `approved=true` in the request body and check
                           # `hv.state().read_only` first (lines 276, 303,
                           # 362, 403, 461, 475, 553, 636).

mutation.write_atomically # The single mutation chokepoint. Receives
                           # `baseline_sha256` (captured at read-time) and:
                           #   1. SHA-256 vs baseline → refuse if changed
                           #   2. UTF-8 decode check
                           #   3. Backup to $STATE/backups/<profile>/<ts>/
                           #      (fsync'd, BEFORE target mutation)
                           #   4. Temp-in-same-dir + fsync + os.replace via
                           #      Hermes' own utils.atomic_replace (symlink/
                           #      mode preserving; EXDEV/EBUSY fallback)
                           #   5. close manifest → return WriteResult
                           # Reads-only callers should never touch the disk
                           # directly; only this function writes.

paths.py                  # The single resolver for HERMES_HOME
                           # (via hermes_constants.get_hermes_home()) and
                           # the only place a hardcoded "/home/app/.hermes"
                           # literal lives (test t2 excludes paths.py from
                           # the single-resolver grep intentionally).

hermes_vendor.py          # 29 vendored Hermes symbols — parser, validator,
                           # atomic writer, .usage.json flock, memory drift
                           # guard, etc. Source-parity check at startup:
                           #   resolved symbols + recorded (but **not**
                           #   compared-to-baseline) SHA-256 fingerprints.
                           # If any symbol DISAPPEARS (rename/removal),
                           # drops to READ-ONLY. If it CHANGES BODY under
                           # the same name, NOT caught — body-drift gap.

validator.py              # Two-faced. LOUD pass delegates to vendored
                           # `_validate_frontmatter` so the tool reproduces
                           # Hermes' accept/reject exactly. SILENT pass is
                           # independent logic that catches every §4 mode.

index_store.py            # DERIVED SQLite FTS5 cache at
                           # $STATE/index.sqlite. Never authoritative —
                           # always rebuildable from disk. Garbage-collect-
                           # able without loss.

config.py                 # Per-tool config in $STATE/config.json.

static/                   # Vanilla-JS SPA, no build step, 7 screens.
                           index.html boots into app.js which loads
                           screens/{ledger,validate,budget,editor,detail,
                           memory,create}.js.
```

## Coexistence contract — non-negotiable

The tool writes into `HERMES_HOME` exactly two things:

1. The user-edited content (`SKILL.md`, `DESCRIPTION.md`, `SOUL.md`,
   `MEMORY.md`, `USER.md`).
2. The lifecycle/lock sidecar `~/.hermes/skills/.usage.json`, written
   under Hermes' **own** `skill_usage._usage_file_lock()` flock
   (`tools/skill_usage.py:89`–`:122`) — same lock Hermes uses, so the tool
   can never race the curator.

It also **deletes** `~/.hermes/.skills_prompt_snapshot.json` after any
content write (idempotent `unlink(missing_ok=True)`), mirroring
`clear_skills_system_prompt_cache(clear_snapshot=True)` from
`learning_mutations.py:200`. **The tool does not write any other file
under `HERMES_HOME`** — no new dotfile, no new sidecar. All tool state
lives outside `HERMES_HOME` under `$XDG_STATE_HOME/hermes-md-manager/`,
namespaced by a SHA-256 of the resolved `HERMES_HOME` (so profile
switching never crosses backups).

## Two-tier deletion

- **soft-delete (default)** → external `$STATE/trash/<profile>/<ts>/<skill>/`.
  Never collides with Hermes' `.archive/`.
- **lifecycle archive** → Hermes' own `skills/.archive/<skill>/` via
  `skill_usage.archive_skill`, so `hermes curator restore` still finds it.
  Refused for non-curation-eligible skills (`is_hub_installed`,
  `is_external_skill_path`, `PROTECTED_BUILTIN_SKILLS = {"plan"}`).

## Agent-context conventions

- **Don't invent schema.** Validator only catches modes documented in
  Phase-1 §4. Anything new must be first confirmed against Hermes source
  and added to `docs/hermes-md-research.md` before being implemented.
- **Read-only under `HERMES_HOME` until the user explicitly approves a
  write.** Tests are read-only against the live tree by construction (use
  `/tmp` copies). The mutation chokepoint's only out-of-band side effect
  is creating backup dirs under `$STATE/backups/<profile>/`.
- **Never commit/push/checkout -b manually.** The dashboard
  auto-commits on session end.
- **The source-parity self-check is the contract with Hermes upgrades.**
  If a vendored symbol disappears or renames, the tool drops to
  READ-ONLY rather than silently using stale code. Body-drift (same
  name, changed implementation) is NOT detected — documented gap.

## Where the audit left things

`AUDIT.md` records what was actually verified vs. what was claimed by
the implementation that landed before the audit. Key items:

- 17/17 tests pass against the live tree.
- Source-parity 29/29 vendor symbols resolve.
- The chokepoint does NOT enforce byte-identity itself (the validator
  does — see `validator.py`'s `loud_check_skill`). Documented in AUDIT.md.
- No real-time curator race was demonstrated until
  `tests/__init__.py: t17`, which spawns a threading.Thread racing writer.
  This is the only Phase-4 deliverable that previously was missing.
- The SPA's UI aesthetic (warm near-black bg, editorial serif + grotesque,
  one accent, line icons) was NOT visually evaluated.
- `paths.py:25` hardcodes `/home/app/.hermes/hermes-agent` for the Hermes
  source path. The brief's single-resolver rule applies to `HERMES_HOME`,
  not the Hermes source. `tests/__init__.py: t2` excludes `paths.py`
  intentionally.

If you're picking this up after a Hermes upgrade, the first thing to run
is `python -m hermes_md_manager --check-only`. If it returns non-zero,
read the reasons — those are the contracts that need to be patched.
