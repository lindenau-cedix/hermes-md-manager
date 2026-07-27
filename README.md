# Hermes MD Manager

A local, offline, single-command curation instrument for **Hermes Agent's
markdown tree** (persona / memory / skills).

The tool exists because Hermes' own frontmatter loader never rejects — a
tab, an unclosed list bracket, a BOM, or `name: yes` (→ Python `True`) all
load **silently corrupted**. `hermes_md_manager` catches those silent
modes, shows you the always-loaded token budget the agent pays every
turn, and lets you edit with a conflict-detecting mutation pipeline that
refuses to clobber changes from the running agent or the background
curator.

Built against the **installed Hermes Agent v0.18.2** at
`/home/app/.hermes/hermes-agent/`. See `docs/hermes-md-research.md` for the
cited ground truth and `docs/design-proposal.md` for the design.

---

## What it does

- **Browse** — a dense ledger over the whole `HERMES_HOME` tree
  (persona + memory + skills). Sortable, filterable. Per-row validity
  badge (green / amber / red).
- **Validate** — whole-tree lint. Two-faced: reproduces Hermes'
  `_validate_frontmatter` (loud rejects) **and** every §4 silent mode
  (BOM, tab-flatten, unquoted-scalar coercion, platform-typo hiding,
  name≠dir dual identity, missing closing `---`, non-UTF-8). Every
  finding cites the rule.
- **Token Budget** — always-loaded cost (SOUL.md + memory snapshot +
  skills **index**, *not* bodies). Worst-offenders flagged. Per-edit
  delta preview.
- **Edit** — schema-driven frontmatter form + raw markdown body, live
  validation, unsaved-change guard. Save routes through the single
  mutation chokepoint (hash==baseline → round-trip proof → external
  fsync'd backup → user-approved diff → atomic write → snapshot-clear).
- **Memory & Persona** — raw-prose SOUL.md editor; §-delimited MEMORY.md
  / USER.md editor with the **drift guard** enforced up-front (entry
  over char-limit blocks the save; Hermes' own next memory write would
  otherwise refuse with a `.bak.<ts>` snapshot).
- **Create / Import-Export** — templates taken from real, valid skills
  in your tree (never invented); import validates before writing;
  export emits a `.tar.gz`.
- **Detail / Resolution / Locks** — per-file detail, lifecycle ops
  (pin/unpin, promote active/stale, archive to Hermes' `.archive/`,
  restore). The **pin toggle is labeled honestly**: `pinned` blocks
  delete/archive only, not `patch`/`edit` (per Hermes' own
  `skill_manager_tool.py:288`). Resolution view shows local-vs-external
  precedence exactly as Hermes computes it.
- **Backups / Trash** — every successful write creates a timestamped
  backup in `$STATE/backups/`; soft-delete moves to external `$STATE/trash/`,
  never to Hermes' `skills/.archive/` (which would race the curator).

---

## What it deliberately does NOT do

- **No auto-merge of conflicting edits.** Refuse + diff.
- **No "content-regeneration lock" UI.** The research proves no such
  field exists in Hermes (`pinned` only blocks delete/archive).
- **No remote Skills-Hub install/search/audit.** Hermes already owns
  that (`hermes skills`).
- **No re-implementation of `skill_manage`'s write-approval staging.**
  Its on-disk staging location is intentionally untraced in this tool.
- **No touching `state.db`.** No skills/memory/persona tables exist
  there (Phase 1 §3.5).
- **No SOUL.md schema.** Persona is raw prose (`prompt_builder.py:1819`).
- **No telemetry, no network egress, no cloud, no multi-user auth.**
  Loopback + per-boot CSRF token only.
- **No editing of binary support files** (PDFs in templates/).

---

## Quick start

```bash
# Use the same python interpreter Hermes itself uses (it has FastAPI,
# uvicorn, and ruamel.yaml already installed).
HERMES_HOME=/home/app/.hermes \
PYTHONPATH=src \
/home/app/.hermes/hermes-agent/venv/bin/python -m hermes_md_manager

# Opens http://127.0.0.1:7788/  (override port with --port N or HERMES_MD_PORT)
```

Single-command check (no server) — verify the source-parity self-check
passes against your installed Hermes:

```bash
PYTHONPATH=src /home/app/.hermes/hermes-agent/venv/bin/python \
  -m hermes_md_manager --check-only
```

---

## Run the tests

```bash
PYTHONPATH=src /home/app/.hermes/hermes-agent/venv/bin/python \
  -m hermes_md_manager.tests
```

15 tests against the real `HERMES_HOME` tree:

- source-parity (29/29 vendor symbols resolve)
- conflict detection (refuses writes with stale baseline)
- byte-identical round-trip (no edits → no bytes change)
- soft-delete goes to external trash, not `skills/.archive/`
- memory drift guard (entry > char-limit blocks save)
- single-resolver rule (no `.hermes` literal outside `paths.py`)
- token budget counts index, not bodies
- validator catches the 4 name≠dir skills + apple/DESCRIPTION.md
- parser parses all 72 real SKILL.md without raising
- §4 silent-mode probes (BOM, tab-flatten, name:yes→True)

---

## How it stays out of Hermes' way

- **Tool state lives in `$XDG_STATE_HOME/hermes-md-manager`** (default
  `~/.local/state/hermes-md-manager/`). Hermes never looks there.
- **Inside `HERMES_HOME` we touch only three things:**
  1. The content files you actually edit (SKILL.md / DESCRIPTION.md /
     SOUL.md / MEMORY.md / USER.md).
  2. `skills/.usage.json` (lifecycle/lock state), using Hermes' own
     `.usage.json.lock` flock from `skill_usage.py:89`–`:122`.
  3. Deletion of `HERMES_HOME/.skills_prompt_snapshot.json` after any
     content write (idempotent, mirrors `clear_skills_system_prompt_cache
     (clear_snapshot=True)` from `learning_mutations.py:200`).
- **We never create a new dotfile inside `HERMES_HOME`** — Hermes'
  scanner excludes only known dot-dirs (`EXCLUDED_SKILL_DIRS` at
  `skill_utils.py:27`); an unknown sidecar is a landmine, not ignored.
- **Source-parity self-check on startup.** We import the actual Hermes
  functions we depend on (`parse_frontmatter`, `_validate_frontmatter`,
  `atomic_replace`, `_detect_external_drift`, the `.usage.json` flock,
  etc.). If any signature drifts after a Hermes upgrade, the tool drops
  to READ-ONLY mode and tells you why — instead of silently using a
  stale algorithm.

---

## Single mutation chokepoint

Every write goes through `write_atomically()` in
`hermes_md_manager/mutation.py`. It enforces:

1. **verify-before-write** — on-disk sha256 must equal the baseline
   captured at read-time. Conflict → refuse + diff, never auto-merge.
2. **backup first** — timestamped full pre-image written to
   `$STATE/backups/<profile-id>/<iso-ts>/` and fsync'd BEFORE the target
   mutation.
3. **atomic write** — temp-in-same-dir + `fsync` + `os.replace` via
   Hermes' own `utils.atomic_replace` (symlink/mode preserving;
   EXDEV/EBUSY fallback for cross-device / bind-mount cases — preserves
   SOUL.md symlinks to a dotfiles repo, GitHub #16743).
4. **user-approved diff** — enforced at the API layer (the chokepoint
   itself refuses `approved=False`).
5. **side effects after success** — `.usage.json` write under the
   flock, snapshot deletion (idempotent `unlink(missing_ok=True)`).

For deletes: two-tier

- **soft-delete (default)** → external `$STATE/trash/`. Never collides
  with the curator's own `.archive/` move.
- **archive** → Hermes' own `skills/.archive/<skill>/` (using Hermes'
  `archive_skill`) so `hermes curator restore` still works. Refused
  for non-curation-eligible skills (hub-installed, external,
  `PROTECTED_BUILTIN_SKILLS`).

---

## Dependencies on Phase-1 findings

The tool is **not** portable across Hermes versions — it intentionally
depends on specific source-line contracts documented in
`docs/hermes-md-research.md`:

- `HERMES_HOME` resolution: `hermes_constants.py:55` (single
  helper, never a hardcoded path).
- `get_skills_dir`: `hermes_constants.py:968`.
- Skill iteration with excluded-dir pruning:
  `agent/skill_utils.py:27`, `:50`, `:785`.
- Loader (`parse_frontmatter`): `agent/skill_utils.py:123` with the
  silent-fallback at `:149`–`:157` (the silent modes we catch).
- Write-validator (`_validate_frontmatter`): `tools/skill_manager_tool.py:524`.
- Name validator: `tools/skill_manager_tool.py:485`,
  `MAX_NAME_LENGTH=64`, `MAX_DESCRIPTION_LENGTH=1024`,
  `MAX_SKILL_CONTENT_CHARS=100_000` at `:170`, `:171`, `:471`.
- Atomic write: `utils.py:91` (`atomic_replace`).
- Skill lifecycle / lock (`.usage.json`):
  `tools/skill_usage.py:53`, `:85`, `:672` (states active/stale/archived
  + `pinned` boolean in the sidecar).
- `.usage.json.lock` flock: `tools/skill_usage.py:89`–`:122`.
- Memory `§`-delimited format: `tools/memory_tool.py:59`,
  `_detect_external_drift` at `:704`.
- The pin semantics ("blocks delete/archive only, not patch/edit"):
  `tools/skill_manager_tool.py:288`.

If any of these change after a Hermes upgrade, the source-parity
self-check will surface it and the tool drops to READ-ONLY.

---

## Known limitations (carried from Phase-1 open questions)

1. **Long-running gateway's in-process skills LRU** may serve a stale
   index between our writes and its next prompt build. The on-disk
   snapshot self-invalidates; the LRU is the operator's responsibility.
2. **Write-approval staging content location** is untraced. If you
   have a staged-but-unapplied agent write, our direct write could
   diverge from what the gate later applies. We document this; we
   don't poke the staging area.
3. **External `skills.external_dirs`** — none configured on this
   install. Precedence logic is read from source but not exercised
   against a real external dir.
4. **Token estimates** use Hermes' own 4-chars/token heuristic (no
   tokenizer installed here). Directional, not exact. Numbers are
   labelled as matching `hermes prompt-size`.

---

## Repo layout

```
hermes-md-manager/
├── AGENTS.md                          # session/agent context file (DE/EN)
├── README.md                          # this file
├── docs/
│   ├── hermes-md-research.md          # Phase 1: cited ground truth
│   └── design-proposal.md             # Phase 2: design (adversarially judged)
└── src/hermes_md_manager/
    ├── __init__.py
    ├── __main__.py                    # entry: `python -m hermes_md_manager`
    ├── paths.py                       # single resolver, state dir, profile id
    ├── hermes_vendor.py               # import + source-parity self-check
    ├── mutation.py                    # single mutation chokepoint
    ├── validator.py                   # two-faced validator + tree scanner
    ├── index_store.py                 # derived FTS5 index (rebuildable)
    ├── app.py                         # FastAPI routes
    ├── config.py                      # per-tool config
    ├── static/                        # SPA (no build step)
    │   ├── index.html
    │   ├── css/app.css
    │   └── js/
    │       ├── app.js                 # boot + state + nav
    │       └── screens/               # 7 screen modules
    └── tests/                         # 15 tests, run via -m hermes_md_manager.tests
```

---

## License

Built for the user's local Hermes Agent. No external distribution.