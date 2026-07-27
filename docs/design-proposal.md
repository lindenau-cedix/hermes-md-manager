# Phase 2 — Design Proposal (Hermes MD Manager)

*Derived from Phase 1: `docs/hermes-md-research.md`. Three independent design
candidates were generated and adversarially judged (Loupe 28/30, Console 27,
Vault 25). The synthesis below adopts Loupe's spine, grafts Console's UI
discipline and the three-color validity badge from Vault, and inherits the
single mutation chokepoint from all three. All claims trace to Phase-1
citations.*

---

## 1 · Data model — stay entirely outside `HERMES_HOME`

The tool's **own state** lives under `$XDG_STATE_HOME/hermes-md-manager/`
(default `~/.local/state/hermes-md-manager/`), **never** inside
`HERMES_HOME`:

```
$STATE/
├── config.json                       # HERMES_HOME, external_dirs, profile-id
├── backups/<profile-id>/<ISO-ts>/    # pre-image of every mutated file
│       └── manifest.json             # op, files[{path, sha256_before, sha256_after}], dry_run
├── trash/<profile-id>/<ISO-ts>/      # soft-deleted skill dirs (NOT Hermes' .archive/)
└── index.sqlite                      # DERIVED cache only (FTS5 bodies + parsed fm +
                                      # token est + resolution results). Rebuild from disk.
                                      # Deleting it loses nothing.
```

The **profile-id** is a hash of the resolved `HERMES_HOME`, so profile switching
(handled via Hermes' `get_hermes_home()` only — `SRC/hermes_constants.py:55`) never
crosses backups. Inside `HERMES_HOME` we touch exactly three things, and no
others:

| We write | Why it's safe |
|---|---|
| `skills/**/SKILL.md`, `DESCRIPTION.md`, `SOUL.md`, `memories/MEMORY.md`, `memories/USER.md` | The intended user edits. Atomic via the chokepoint (§3). |
| `skills/.usage.json` (only the `state`/`pinned`/`archived_at` keys we own) | Hermes' own writer takes the same `.usage.json.lock` flock (`SRC/tools/skill_usage.py:89`–`:122`); we use the identical discipline. |
| **Delete** `skills/.skills_prompt_snapshot.json` after any content write | Idempotent `unlink(missing_ok=True)`, mirrors `clear_skills_system_prompt_cache(clear_snapshot=True)` (`SRC/agent/learning_mutations.py:200`/`SRC/agent/prompt_builder.py:1264`). |

We **never** create a new dotfile in `HERMES_HOME` (Hermes' scanner excludes only
known dot-dirs — `EXCLUDED_SKILL_DIRS` at `SRC/agent/skill_utils.py:27` — an
unknown sidecar is a landmine, not ignored). We **never** write to `state.db`
(Phase 1 §3.5 — no skills/memory/persona table exists there).

## 2 · Architecture & stack

| Choice | Justification |
|---|---|
| **FastAPI** + **uvicorn**, single process, bound `127.0.0.1` only | Fixed by brief; loopback + offline = OS boundary is the auth boundary. |
| **Single command**: `python -m hermes_md_manager` | Boots server + opens browser; per-boot random token appended to URL for CSRF. |
| **No frontend build step** — vanilla ES-modules SPA, hand-rolled | One small reactive lib (Preact, vendored, ~4KB) only where needed. A bundler would make it "look generated." |
| **PyYAML** (`CSafeLoader`) for the **loader-side** validator | Mirrors Hermes' *exact* loader (`SRC/agent/skill_utils.py:105`) so silent-mode detection is faithful. |
| **ruamel.yaml** for **write-side** | The only way to guarantee byte-round-trip (key order, comments, quoting, line endings) required by the brief. |
| **stdlib** `fcntl`, `hashlib`, `difflib`, `sqlite3` (FTS5), `os.replace` | No extra deps for locking, hashing, diff, index, atomic rename. |
| **Hypothesis** for property tests | Round-trip + conflict tests over the **real 72-file tree**. |
| **Token estimate**: Hermes' own 4-chars/token heuristic (`SRC/agent/prompt_builder.py:1178`) as the default. **No** tiktoken auto-upgrade — `hermes prompt-size` uses the same heuristic, so upgrading would break the "matches Hermes" claim. Numbers are directional and labelled as such. |

**Architecture rule, enforced by a CI test**: a single grep that scans the whole
source tree for `~/.hermes`/`'.hermes'` literals outside one
`resolve_home()` helper fails the build. All paths go through
`get_hermes_home()`.

## 3 · Single mutation chokepoint (the safety spine)

There is exactly **one** function that emits a write. Every feature calls it. It
cannot proceed past any of these guards:

1. **Baseline captured**: `sha256(file) == baseline` from the user's last
   read (`hash-on-read`, carried from Browse). Mismatch ⇒ refuse + diff; **no
   auto-merge**.
2. **Round-trip proven**: re-parse and re-serialise what we are about to write;
   for a no-op edit, require byte-identical output. For a real edit, require
   that the *untouched* region of the file (frontmatter fields not edited, body
   bytes not edited) survive ruamel byte-identically — a true round-trip
   property. Property-tested over the real tree.
3. **Backup on disk and fsync'd**, outside `HERMES_HOME`, *before* any target
   mutation. Manifest records op, paths, before/after hashes.
4. **Diff approved** by the user (mandatory for edits; **dry-run by default**
   for every bulk op). For destructive ops, an additional **typed-name
   confirmation**.
5. **Atomic write** reusing Hermes' own pattern (`SRC/utils.py:91`): temp file
   in same directory, fsync, `atomic_replace` which resolves symlinks first so
   `SOUL.md` symlinks to a dotfiles repo survive (#16743). EXDEV/EBUSY fallback
   to copy+fsync+unlink. Mode + owner preserved.
6. **Side effects** only after the write succeeds: `.usage.json` under the
   flock (read-modify-write, preserve every telemetry counter verbatim),
   snapshot deletion (idempotent unlink).

Soft delete by default: skill dirs move to `$STATE/trash/<iso-ts>/<skill>/`, not
Hermes' `.archive/` (so we never race `archive_skill` at
`SRC/tools/skill_usage.py:696`) — unless the user explicitly invokes
**Promote/Archive**, which writes through `.usage.json` under the flock and
moves the dir using Hermes' flat `skills/.archive/<skill>/` layout so
`hermes curator restore` still finds it (`SRC/tools/skill_usage.py:735`–`:828`).

## 4 · Screen inventory (single window, dense, keyboard-first)

Seven screens. The whole tool is one route tree — no tabs of tabs.

1. **Browse — the ledger.** One dense table over the whole tree. Columns: file,
   type (persona / memory / skill / category), category, bytes, **token
   estimate**, **lifecycle state**, **pinned**, **validity badge** (green =
   Hermes-accepts-clean, **amber = loads but silently wrong** (the §4 modes),
   red = would be rejected). Sortable + filterable. The per-row hash captured
   here becomes the conflict baseline for any edit.
2. **Validate — whole-tree report.** Runs the two-faced validator (§5). Every
   finding carries severity, cited rule (e.g. "loader-fallback flatten at
   `skill_utils.py:149`"), and a concrete suggested fix. Turned into an `n`/`p`
   fix-queue: `D` = diff, `Enter` = open suggested patch, `dry-run` first for
   bulk normalisations (quote coerced scalars, normalise `tags` placement).
3. **Token Budget.** Always-loaded total pinned at top = `SOUL.md` + memory
   snapshot + the **skills INDEX** (name + ≤60-char desc grouped by category
   DESCRIPTION headers — *not* the 838 KB of bodies). Worst-offenders flagged.
   Live delta panel recomputes from the in-editor buffer **before** save.
4. **Edit.** Schema-driven frontmatter form (typed fields, `platforms` /
   `environments` as controlled inputs, required-field enforcement mirroring
   the validator) + markdown body editor. Live validation, unsaved-change
   guard. Save routes only through the chokepoint (§3).
5. **File Detail / Resolution / Locks.** Per-file view: parsed frontmatter,
   lifecycle state, pinned, references (`metadata.hermes.related_skills`,
   `name` vs directory name dual identity, slash/cron/config.yaml refs).
   **Resolution** view shows local-vs-external precedence exactly as Hermes
   computes it (local root always wins; external with already-seen
   frontmatter `name` skipped — `SRC/agent/prompt_builder.py:1575`). **Pinned**
   toggle (writes `.usage.json` under the flock) with the caption "**pinned
   blocks delete/archive only — not patch/edit**" (the `skill_manager_tool.py:288`
   reality) and an "**UNPROTECTED**" indicator on every curation-eligible,
   un-pinned skill (excluding hub-installed/external/`PROTECTED_BUILTIN_SKILLS`
   per `SRC/tools/skill_usage.py:66`–`:470`).
6. **Memory & Persona editor.** Persona: raw prose, byte-fidelity + token
   accounting only (no schema — `SRC/agent/prompt_builder.py:1819`). Memory:
   `§`-delimited entry list, char budgets of 2200/1375 (memory/user) shown as
   fill bars; **hard-blocks any save where `raw.strip() != roundtrip` or any
   entry exceeds the store's char limit** — the exact predicate that would
   trigger Hermes' `_detect_external_drift` (`SRC/tools/memory_tool.py:704`) and
   refuse its own next memory write.
7. **Create / Import-Export.** Create picks a **known-green real skill** as
   template; new dir name and frontmatter `name` are set together to avoid the
   dual-identity footgun (`SRC/tools/skill_manager_tool.py:600` keys by dir
   name; index keys by `name`). Import: validate → conflict-check → backup →
   write → snapshot-clear. Export: a skill folder as one archive.

**Visual discipline (the "instrument, not landing page" brief):**

- Warm near-black bg (`#14110E`); ink palette: warm whites & ambers.
- **Editorial serif** (a humanist book serif) for prose + a **grotesque** for
  data + tabular figures everywhere on numeric columns.
- **One** accent colour (muted amber-clay) reserved for *active*,
  *unsaved*, and *danger* states only.
- Custom 1px hand-drawn line icons — no emoji, no icon font.
- Dense: 12–14px type, 4px grid, tabular numerics, keyboard-first (`j/k`,
  `/` to search, `g a` to go to Archive, `n/p` through the validate queue).
- No gradient text, no glassmorphism, no default Material, no stock Tailwind
  palette.

## 5 · Validator (the two-faced one)

Two passes, one report:

- **Loud-pass** — vendored `_validate_frontmatter` (`SRC/tools/skill_manager_tool.py:524`)
  via `yaml.safe_load`: empty content, missing `---`, unclosed fence,
  non-mapping frontmatter, missing `name`/`description`, description > 1024,
  empty body.
- **Silent-pass** — vendored `parse_frontmatter` (`SRC/agent/skill_utils.py:123`)
  with the same fallback path at `:149`–`:157`: flags every §4 silent mode
  (BOM-before-fence → all frontmatter lost; tab indent → silent flatten to
  string-valued dict; unclosed list → `platforms` becomes the string
  `"[linux, macos"` → platform gate hides the skill; unquoted `yes/no/on/off`
  → Python bool; non-UTF-8 bytes → metadata empty; `name:` ≠ directory name →
  dual-identity footgun; `apple/DESCRIPTION.md`-style missing frontmatter →
  category description silently dropped).

Every finding carries a severity (reject / silent-corruption / advisory) and a
**cited rule** so the next operator can verify it against source. This is the
tool's reason to exist and the test that proves it: a CI run on the live
72-file tree produces the same set of findings Hermes itself produces on a
fresh load.

## 6 · Coexistence contract (won't race the curator)

- **`.usage.json` writes**: take the *same* `.usage.json.lock` flock Hermes
  takes (`SRC/tools/skill_usage.py:89`–`:122`); do a short read-modify-write
  of only the keys we own (`pinned`, `state`, `archived_at`); preserve every
  `use_count`/`view_count`/`patch_count`/`last_*_at` verbatim. Release before
  returning.
- **Snapshot**: idempotent unlink after content writes (the snapshot manifest
  is keyed on indexed SKILL.md/DESCRIPTION.md mtime+size at
  `SRC/agent/prompt_builder.py:1297`; the next prompt build re-creates it).
- **Long-running gateway's in-process LRU** (`SRC/agent/prompt_builder.py:1254`)
  may still serve a stale index mid-session. We **document this honestly in the
  UI**, not pretend to fix it.
- **Curator archive/restore race**: tool's archive path uses Hermes' own flat
  `.archive/<skill>/` shape (`SRC/tools/skill_usage.py:735`) so `hermes curator
  restore` still works; the user soft-delete path (the default) uses our
  external `trash/`, never `skills/.archive/`. Archive/restore is refused for
  non-curation-eligible skills (hub-installed, external_dirs, protected).
- **Memory drift safety**: every MEMORY/USER write emits exactly
  `"\n§\n".join(stripped, non-empty)` with no trailing newline; the editor
  blocks any save that would fail `_detect_external_drift`.

## 7 · What we are deliberately **not** building

- **No auto-merge on conflict.** Refuse + diff, full stop.
- **No "content-regeneration lock" UI.** The research proves no such field
  exists; `pinned` only blocks delete/archive (`SRC/tools/skill_manager_tool.py:288`).
  We label this clearly rather than invent a misleading toggle.
- **No remote Skills-Hub install/search/audit.** Hermes already owns that
  (`SRC/hermes_cli/skills_hub.py` + `tools/skills_guard.py`).
- **No re-implementation of `skill_manage`'s write-approval staging.** The
  staged-content on-disk location is untraced (§7.2). We document the
  limitation.
- **No touching `state.db`.** No skills/memory/persona tables exist there
  (Phase 1 §3.5).
- **No re-implementation of `hermes update` / curator cadence.** We surface and
  manually act on state.
- **No SOUL.md schema** — persona is raw prose (`SRC/agent/prompt_builder.py:1819`).
  Byte-fidelity + token accounting only.
- **No telemetry, no network egress, no cloud, no multi-user auth** — loopback
  + per-boot token only.
- **No editing of binary support files** (e.g. the PDFs in
  `research-paper-writing/templates/`) beyond treating them as opaque blobs for
  import/export.

## 8 · Key risks (and mitigations)

| Risk | Mitigation |
|---|---|
| `ruamel.yaml` round-trip is not byte-identical for every pathological YAML (anchors, exotic quoting) | Property test over the live 72-file tree in CI; for files that fail, edit body-only or refuse with a clear message. |
| Hermes version drift (research is pinned to v0.18.2; line numbers move) | Startup **source-parity self-check**: import the installed `parse_frontmatter`, `_validate_frontmatter`, `atomic_replace`, `_usage_file_lock`, `_detect_external_drift`; if any signature moves, drop to READ-ONLY mode and tell the user. README documents this dependency explicitly. |
| Long-running gateway's in-process skills-LRU serves stale index after our writes | Documented as known limitation; UI surfaces it; the on-disk snapshot is invalidated at next prompt build. |
| Dual-identity footgun (`name:` ≠ dir name, 5 real cases) for rename | Rename flow treats the `name`-vs-dir mismatch as the sharpest correctness edge; mandatory dry-run; reference scan covers `related_skills`, `.usage.json` keys, `.bundled_manifest`, `config.yaml` (`skills.external_dirs`); references in unknown forms are reported but not auto-updated. |
| `hermes prompt-size` and our Token Budget diverge on estimates | Same heuristic, same `CONTEXT_FILE_*` constants, same labels. The screen explicitly states the heuristic. |
| Curator archive/restore race on directory rename | Two-tier deletion (user soft-delete → external `trash/`; lifecycle archive → Hermes `.archive/` under the flock); archive refused for non-eligible skills. |
| Write-approval staged-but-unapplied divergence | We don't touch the untraced staging area; we document that the user should resolve staged writes before our edits. |

---

## 9 · Quality bar (carried into Phase 3)

- Tests for parser + validator, **run against the real 72 files** — failures
  block the build.
- Round-trip fidelity as a property test over the whole tree (no-edit saves
  must be byte-identical).
- Single-resolver rule enforced by a test (grep for `.hermes` literals).
- Source-parity self-check on startup.
- Works fully offline; binds loopback only; no telemetry.
- Single-command start: `python -m hermes_md_manager`.
- Graceful on empty / partial / pre-schema `HERMES_HOME`.

*End of Phase 2 proposal. **Stopping for approval** — no implementation yet.*