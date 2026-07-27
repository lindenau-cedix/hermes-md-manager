# Hermes Agent — Markdown Ground-Truth Research (Phase 1)

**Status:** Reconnaissance complete. Read-only. This document is the *only* file
Phase 1 produced under the tool project; nothing under `HERMES_HOME` was touched.

**Subject:** Hermes Agent **v0.18.2** (Nous Research), the version *actually
installed on this machine*.

**Sources of truth (all citations are relative to these roots):**

| Alias | Absolute path |
|---|---|
| `SRC/` | `/home/app/.hermes/hermes-agent/` (installed source — read directly) |
| `HOME/` | `/home/app/.hermes/` (the live profile / `HERMES_HOME`) |

- The configured `HERMES_HOME` env var is **unset**; Hermes therefore uses the
  platform default `~/.hermes` = `HOME/` above (`SRC/hermes_constants.py:46`,
  `:55`, `:110`). `PROFILES_IN_USE = single profile` (default profile).
- `HERMES_SOURCE` was given as "please download yourself"; no download was
  needed — the running code lives at `SRC/` (the `hermes` launcher execs
  `SRC/venv/bin/hermes`), package `hermes-agent==0.18.2`
  (`SRC/hermes_agent.egg-info/PKG-INFO`).
- Every factual claim below carries a `path:LINE` citation. Claims I could not
  confirm from source are quarantined in **§7 Unverified assumptions**.
- Failure behaviour in **§4** is *empirical*: I imported the installed parser
  and validator into Hermes' own venv and ran malformed inputs through them.

Citation confidence: everything in §1–§4 and §7 was read first-hand. In §5
(existing tooling) the `web_server.py` line numbers were located by grep and
route-existence confirmed first-hand; individual handler internals were mapped
in a secondary read pass and are flagged where relevant.

---

## 0. Executive summary (the load-bearing facts)

1. **Three markdown layers drive the agent**, all resolved through
   `get_hermes_home()` (`SRC/hermes_constants.py:55`), never a hardcoded
   `~/.hermes`:
   - **Persona:** `HOME/SOUL.md` — raw prose, no frontmatter, injected whole
     into the system prompt every session.
   - **Memory:** `HOME/memories/MEMORY.md` + `HOME/memories/USER.md` — **not
     frontmatter**; `§`-delimited entry lists, char-budgeted, injected as a
     *frozen snapshot* every session.
   - **Skills:** `HOME/skills/**/SKILL.md` — YAML-frontmatter + markdown body.
     Only a compact **index** (name + description) is loaded every session; full
     bodies load on demand via `skill_view`.
2. **Lifecycle + lock state is a JSON sidecar, not the frontmatter and not
   SQLite.** `HOME/skills/.usage.json` holds `state` (active/stale/archived),
   `pinned`, `use_count`, timestamps (`SRC/tools/skill_usage.py:85`, `:484`).
   `state.db` (SQLite) has **no** skills/memory/persona tables
   (`SRC/hermes_state.py:746`–`:863`). **A file-only tool is *not* lying — but it
   must also read/write `.usage.json` to manage lifecycle/lock, and clear the
   prompt-index cache after edits.**
3. **`pinned` is the only lock, and it only blocks deletion/archival — not
   content rewrites** (`SRC/tools/skill_manager_tool.py:270`). There is **no**
   frontmatter field that protects a hand-edited skill from the learning loop's
   `patch`/`edit`. (Corrects a prior belief — see Appendix A.)
4. **The frontmatter loader never rejects.** On any YAML error it silently
   falls back to naive `key:value` line-splitting
   (`SRC/agent/skill_utils.py:145`–`:157`), so malformed skills load with
   *corrupted* metadata rather than failing loudly. The strict validator
   (`_validate_frontmatter`) runs **only** on the agent's own write tool, never
   on hand-edited files. **These silent modes are the tool's core reason to
   exist.**
5. **Writes are already atomic** (temp + `fsync` + `os.replace`, symlink- and
   mode-preserving — `SRC/utils.py:91`, `SRC/tools/skill_manager_tool.py:757`).
   But **there is no external backup**: foreground skill delete is a hard
   `shutil.rmtree` (`SRC/tools/skill_manager_tool.py:1115`) and `hermes memory
   reset` `unlink`s memory files with no snapshot.
6. **A local web dashboard already exists** and can list/toggle/create/edit
   skills, but has **no delete, no patch, no supporting-file management, no
   memory-content editor, no cross-tree validator, and no local skill index**
   (§5). That is the gap.

---

## 1. Ground truth — every markdown file type

### 1.1 Discovery surface & path resolution

All paths resolve through one helper: `get_hermes_home()`
(`SRC/hermes_constants.py:55`) → context-var override → `HERMES_HOME` env →
platform default (`~/.hermes` POSIX, `%LOCALAPPDATA%\hermes` Windows,
`:46`–`:52`). Derived well-known paths: `get_skills_dir()` → `HERMES_HOME/skills`
(`:968`), `get_config_path()` → `HERMES_HOME/config.yaml` (`:959`),
`get_env_path()` → `HERMES_HOME/.env` (`:974`).

**Skill search roots**, in precedence order (`SRC/agent/skill_utils.py:503`
`get_all_skills_dirs`): `[0]` local `HERMES_HOME/skills` (always first, always
included), then `[1:]` each existing dir from `skills.external_dirs` in
`config.yaml`, expanded (`~`, `${VAR}`), resolved absolute, de-duped, with the
local dir itself skipped (`:420`–`:500`). **Precedence on name collision: local
wins; external skills with an already-seen frontmatter `name` are skipped**
(`SRC/agent/prompt_builder.py:1575`–`:1604`). Bundled skills ship separately and
are *seeded/copied into* `HERMES_HOME/skills` (see `SRC/hermes_constants.py:206`
`get_bundled_skills_dir`; sync in `SRC/tools/skills_sync.py`); at runtime they
are just ordinary files under the local root, tagged via `.bundled_manifest`.

**Skill-folder companion dirs** `references/`, `templates/`, `scripts/`,
`assets/` are **support areas, not skills** (`SRC/agent/skill_utils.py:50`,
`:73`). The scanner prunes them when they sit directly inside a dir containing
`SKILL.md` (`:785` `iter_skill_index_files`, `:796`–`:806`), and also prunes
`.git .github .hub .archive .venv venv node_modules __pycache__ …`
(`EXCLUDED_SKILL_DIRS`, `:27`). Support files are **not loaded** into context on
their own — they are reachable only on demand via `skill_view(..., file_path=…)`
(`SRC/tools/skills_tool.py`).

### 1.2 File-type table

| Type | Path pattern | Always loaded? | What enters context | Writer(s) | Source citations |
|---|---|---|---|---|---|
| **Persona** | `HOME/SOUL.md` | **Yes**, every session (identity slot #1) | Whole file (truncated to context-file cap) | seeded by `hermes_cli/default_soul.py`; edited via generic file tools (no dedicated tool) | `SRC/agent/prompt_builder.py:1819` `load_soul_md`, `:1947` `build_context_files_prompt`, `:1986` |
| **Agent memory** | `HOME/memories/MEMORY.md` | **Yes**, every session (frozen snapshot) | `§`-delimited entries, ≤ `memory_char_limit` | `memory` tool (`SRC/tools/memory_tool.py`), journey edit (`SRC/agent/learning_mutations.py`) | `SRC/tools/memory_tool.py:5`, `:11`, `:55`, `:59` |
| **User profile** | `HOME/memories/USER.md` | **Yes**, every session (frozen snapshot) | `§`-delimited entries, ≤ `user_char_limit` | same as MEMORY.md | `SRC/tools/memory_tool.py:8`, `SRC/agent/learning_mutations.py:23` |
| **Skill** | `HOME/skills/**/SKILL.md` | **Index only** every session; body on demand | `name: description` line under its category; **body via `skill_view`** | `skill_manage` (`SRC/tools/skill_manager_tool.py`), web `POST/PUT /api/skills`, journey edit | `SRC/agent/prompt_builder.py:1445` `build_skills_system_prompt`, `SRC/tools/skills_tool.py:1753` `skill_view` |
| **Category descr.** | `HOME/skills/**/DESCRIPTION.md` | Index only (category header) | `description` frontmatter → category label | copied by `skills_sync`; no dedicated tool | `SRC/agent/prompt_builder.py:1550`–`:1562` |
| **Project context** (out of scope, shares load path) | `<cwd>/AGENTS.md`, `HERMES.md`, `CLAUDE.md`, `.cursorrules` | When agent runs in that dir | Whole file (truncated); frontmatter stripped | user/agent edits | `SRC/agent/prompt_builder.py:1850`–`:1945` |

### 1.3 State / sidecar files under `HOME/skills/` (NOT markdown, but authoritative)

| File | Purpose | Format | Citation |
|---|---|---|---|
| `.usage.json` (+ `.usage.json.lock`) | **Lifecycle + lock + telemetry**, keyed by skill `name` | JSON map; per-skill record `{created_by, use_count, view_count, patch_count, last_*_at, created_at, state, pinned, archived_at}` | `SRC/tools/skill_usage.py:85`, `:484`, lock `:89` |
| `.bundled_manifest` | Marks skills seeded from the bundled repo (curator provenance) | `name:hash` per line | `SRC/tools/skill_usage.py:187` |
| `.hub/lock.json` | Marks Skills-Hub-installed skills | JSON `{installed: {...}}` | `SRC/tools/skill_usage.py:209` |
| `.hub/`, `.hub/index-cache/` | Hub metadata + remote-catalog cache | JSON; **read-blocked to the agent** as an injection carrier | `SRC/agent/file_safety.py:243`–`:256` |
| `.curator_suppressed` | Built-ins the curator pruned (survive re-seed) | one name per line | `SRC/tools/skill_usage.py:264` |
| `.curator_state` | Curator run bookkeeping | JSON (atomic write) | `SRC/agent/curator.py:106`–`:121` |
| `.archive/<skill>/` | **Soft-deleted / archived skills** (recoverable) | moved skill dirs (flat) | `SRC/tools/skill_usage.py:125`, `:696` |
| `HOME/.skills_prompt_snapshot.json` | Cached parsed skill index (cold-start speedup) | JSON, validated by mtime/size manifest | `SRC/agent/prompt_builder.py:1261`, `:1301` |

---

## 2. Frontmatter / content schema (a spec a validator can be generated from)

### 2.1 The parser (loader path — what the agent actually reads)

`parse_frontmatter(content)` (`SRC/agent/skill_utils.py:123`):

1. If `content` does **not** start with `---` → returns `({}, content)`. (A
   leading BOM defeats this — see §4.)
2. Finds the closing fence via regex `\n---\s*\n` on `content[3:]` (`:138`). No
   closing fence → `({}, content)`.
3. Parses the enclosed YAML with **`yaml.CSafeLoader`** (falls back to
   `SafeLoader`) via `yaml.load` (`:105`–`:117`). CSafeLoader confirmed present
   in this install.
4. **On *any* parse exception → silent fallback** to line-by-line
   `key.split(":",1)` (`:149`–`:157`). This never raises and never rejects — it
   produces a *flattened, string-valued, structurally-wrong* dict.

YAML semantics observed empirically (§4): **duplicate keys → last value wins, no
error**; unquoted `yes/no/true/on/off` → Python bool; unquoted integers → int;
tabs are illegal and trigger the silent fallback.

### 2.2 SKILL.md — fields actually consumed by the runtime

Only these frontmatter fields change agent behaviour. Everything else is
preserved on disk but ignored by the discovery/index/gating code path.

| Field (dotted) | Type | Req? | Default | Consumed by | Effect | Citation |
|---|---|---|---|---|---|---|
| `name` | str | **Yes** (write-validator) | dir name | index, disabled-check, collision key | skill identity in the index | `SRC/agent/prompt_builder.py:1361`; validator `SRC/tools/skill_manager_tool.py:549` |
| `description` | str | **Yes** (write-validator) | `""` | index | shown after name; **truncated to 60 chars** for the index (`extract_skill_description`) | `SRC/agent/skill_utils.py:771`; validator caps at **1024** `:553` |
| `platforms` | list\|str | No | all-platforms | `skill_matches_platform` | **hard OS gate**: absent = all; `macos→darwin`, `linux`, `windows→win32` | `SRC/agent/skill_utils.py:21`, `:163`–`:208` |
| `environments` | list\|str | No | all | `skill_matches_environment` | **offer-time only** relevance gate (`kanban`/`docker`/`s6`); never blocks explicit load | `SRC/agent/skill_utils.py:221`, `:272`–`:308` |
| `metadata.hermes.requires_toolsets` | list | No | `[]` | `_skill_should_show` | hide from index unless toolset present | `SRC/agent/skill_utils.py:602`; `SRC/agent/prompt_builder.py:1419` |
| `metadata.hermes.requires_tools` | list | No | `[]` | `_skill_should_show` | hide unless tool present | same |
| `metadata.hermes.fallback_for_toolsets` | list | No | `[]` | `_skill_should_show` | hide **when** toolset present | same |
| `metadata.hermes.fallback_for_tools` | list | No | `[]` | `_skill_should_show` | hide when tool present | same |
| `metadata.hermes.config[]` | list of `{key, description, default?, prompt?}` | No | `[]` | `extract_skill_config_vars` / setup | declares `skills.config.<key>` settings the skill needs | `SRC/agent/skill_utils.py:622`–`:678` |

**Advisory / documentation-only fields** (present in the real tree, *not* read by
the load path traced): `version`, `author`, `license`, `title`, `compatibility`,
`setup`, `dependencies`, `prerequisites` (`commands`/`env_vars`),
`required_credential_files`, `triggers`, top-level `tags`, and
`metadata.hermes.{tags, homepage, related_skills, category, related_docs,
upstream_skill, supersedes, requires_toolsets*}`. These are preserved but do not
change discovery/gating. **Unknown fields are silently ignored** (§4). Whether
hub/search/website tooling consumes `tags`/`triggers` is an open question (§7).

**Write-time validator** `_validate_frontmatter`
(`SRC/tools/skill_manager_tool.py:524`) — runs **only** on `skill_manage`
create/edit/patch and the web create/edit routes, **never** on hand-edits:
non-empty; starts with `---`; closing `\n---\s*\n`; `yaml.safe_load` must
succeed; result must be a mapping; `name` present; `description` present and
≤ 1024; non-empty body. Plus `_validate_name` (`:485`,
`VALID_NAME_RE = ^[a-z0-9][a-z0-9._-]*$`, ≤ 64 chars, `:170`, `:475`),
`_validate_category` (single path segment, same charset, `:499`),
`_validate_content_size` (≤ `MAX_SKILL_CONTENT_CHARS = 100_000`, `:471`;
supporting files ≤ `1_048_576` bytes, `:472`).

**Dual identity footgun:** the index and curator key skills by **frontmatter
`name`** (`prompt_builder.py:1361`, `skill_usage.py:398`), but `skill_manage`'s
`_find_skill` matches by **directory name** (`skill_manager_tool.py:600`). Five
skills in this tree have `name` ≠ dir (§6) — they show one label in the index
but are addressed by another for edits.

### 2.3 DESCRIPTION.md (category level)

Frontmatter with a single consumed key: `description` (`SRC/agent/prompt_builder.py:1554`–
`:1560`). Same parser, same silent-fallback behaviour. Becomes the category
header line in the index.

### 2.4 SOUL.md (persona)

**No schema.** Read as raw UTF-8 prose, `.strip()`ed, scanned for
prompt-injection markers, truncated to the context-file cap, injected whole
(`SRC/agent/prompt_builder.py:1819`–`:1846`). If it *did* carry frontmatter it
would be passed through as prose (the identity slot does not parse it). Deployments
may **symlink** SOUL.md to a dotfiles repo — writers must preserve the symlink
(`SRC/utils.py:91`–`:112`, GitHub #16743).

### 2.5 Memory files (MEMORY.md / USER.md)

**Not frontmatter.** A memory file is a list of entries joined by
`ENTRY_DELIMITER = "\n§\n"` (`SRC/tools/memory_tool.py:59`). Read: split on the
delimiter, `.strip()` each, drop empties (`_read_file`, `:683`–`:702`). Write:
`"\n§\n".join(entries)`, no trailing newline, atomic (`_write_file`, `:760`).
Per-**store** char budgets (not per-entry, not tokens):
`memory_char_limit = 2200`, `user_char_limit = 1375` by default (`:130`,
`:804`; overridable via `memory.memory_char_limit` / `memory.user_char_limit` —
confirmed present in `HOME/config.yaml:554`–`:555`).

**Drift guard (`_detect_external_drift`, `:704`):** before a mutating write the
tool re-parses+re-serialises the on-disk file; if `raw.strip() != roundtrip`
**or** any single entry exceeds the store char-limit, it declares external drift,
saves a `.bak.<unixts>` snapshot next to the file, and **refuses the write**
(`:744`–`:757`, `_drift_error` `:83`). **Consequence for our tool: any memory
file we write must be a clean `§`-delimited list, or Hermes will refuse its own
next memory write.**

---

## 3. Write-path map (mutators, concurrency, caching)

### 3.1 Who writes what

| Mutator | Entry point | Actions | Atomic? | Backup? | Citation |
|---|---|---|---|---|---|
| **`skill_manage`** (agent tool) | `SRC/tools/skill_manager_tool.py:1320`, registered `:1543` | create/edit(full rewrite)/patch(find-replace)/delete/write_file/remove_file | **Yes** (`_atomic_write_text:757` → `utils.atomic_replace`) | **No external backup**; in-memory `original_content` rollback only on a security-scan block (`:886`, `:1006`) | see cells |
| foreground **delete** | `_delete_skill:1027` | user-directed delete | — | **Hard `shutil.rmtree` — irrecoverable** (`:1115`); only the curator/background-review pass archives instead (`:1102`) | `:1027`–`:1129` |
| **skills read** | `SRC/tools/skills_tool.py:1718`/`:1753` | `skills_list`, `skill_view` (+ view telemetry) | n/a | n/a | — |
| **Curator** (background) | `SRC/agent/curator.py:306` `apply_automatic_transitions` | active↔stale↔archived by inactivity; LLM consolidation; archive = soft move to `.archive/` | via `skill_usage`/`archive_skill` (rename) + `atomic_json_write` | archive is recoverable (`hermes curator restore`) | `:306`–`:380`, `SRC/tools/skill_usage.py:696` |
| **Lifecycle/lock state** | `SRC/tools/skill_usage.py` | `set_state`, `set_pinned`, counter bumps | **Yes** (tempfile+fsync+`os.replace`) under **cross-process flock** `.usage.json.lock` | n/a | `:520`–`:542`, `:89`–`:122`, `:657`–`:675` |
| **Memory** | `SRC/tools/memory_tool.py` add/replace/remove | frozen snapshot + drift guard + atomic `§`-write | **Yes** (`:760`) | drift → `.bak.<ts>` (`:752`) | `:336`–`:530` |
| **Journey edit** | `SRC/agent/learning_mutations.py` | edit/delete a skill *or* individual memory chunk (`memory:<source>:<index>`) | reuses skill/memory atomic writers | delete-skill → archive; delete-memory → rewrite file | `:23`, `:124`–`:197` |
| **Web dashboard** | `SRC/hermes_cli/web_server.py` | `POST /api/skills` (create, `:13564`), `PUT /api/skills/content` (edit, `:13583`), toggle/list/content; `POST /api/memory/reset` (`:11843`); `PUT/DELETE /api/learning/node` (`:3039`/`:3027`) | via the same underlying tools | none added | route lines confirmed first-hand |
| **CLI** | `SRC/hermes_cli/…` | `hermes skills` (hub mgr), `hermes memory` (provider+reset), `hermes curator` (pin/unpin/restore/list-archived), `hermes journey`, `hermes backup`, `hermes prompt-size`, `hermes doctor` | varies | `memory reset` = `unlink`, **no backup** | §5 |

### 3.2 The lock / pin mechanism (exact semantics)

`pinned` is a boolean in `.usage.json` set by `set_pinned`
(`SRC/tools/skill_usage.py:672`). It is honoured in exactly two places:
the curator skips pinned skills in its transition walk
(`SRC/agent/curator.py:331`), and `_pinned_guard` refuses `skill_manage`
**delete** (`SRC/tools/skill_manager_tool.py:270`–`:291`) and journey delete
(`SRC/agent/learning_mutations.py:134`). Its own docstring is explicit:
"Patches and edits are allowed on pinned skills; only deletion is blocked"
(`:288`). **There is no field, sidecar, or frontmatter key that stops the
learning loop from `patch`/`edit`-ing a skill's content.**

### 3.3 Lifecycle state machine

States (`SRC/tools/skill_usage.py:53`): `active` → `stale` (unused past
`curator.stale_after_days`) → `archived` (unused past `archive_after_days`;
directory moved to `.archive/`). Reactivates on use. Only **curation-eligible**
skills participate: agent-created (record `created_by=="agent"`), or bundled
built-ins **when `curator.prune_builtins` is true** (default true, `:242`);
hub-installed and `external_dirs` skills are never eligible; `PROTECTED_BUILTIN_SKILLS
= {"plan"}` never (`:66`). State lives **only** in `.usage.json` — not
frontmatter, not SQLite.

### 3.4 Caching & concurrency (does anything clobber my edit?)

- **Skill index cache is two-layer** (`SRC/agent/prompt_builder.py:1445`):
  in-process LRU (max 8, `:1254`) keyed by `(skills_dir, external_dirs, tools,
  toolsets, platform, disabled, compact_categories)`, plus the disk snapshot
  `HOME/.skills_prompt_snapshot.json` validated by an mtime/size **manifest**
  (`:1275`, `:1301`–`:1316`). **If I edit a `SKILL.md`, the disk snapshot
  self-invalidates on the next build (manifest mismatch), but a *running* agent
  process keeps its in-process LRU** until it rebuilds the prompt (next session)
  or `clear_skills_system_prompt_cache(clear_snapshot=True)` is called — which
  the learning path does after its own writes (`SRC/agent/learning_mutations.py:200`).
  → **Our tool should call/emulate that cache-clear (delete the snapshot) after a
  write so a live gateway doesn't serve a stale index.**
- **Hermes never rewrites a `SKILL.md` on its own** except when the agent/curator
  acts (foreground tool call, background learning review, or curator
  archive/consolidation). It will not silently clobber *file content*, but the
  **curator can move/archive a skill dir** between my read and write, and the
  **background review loop can `patch`** it. → this is exactly why the tool needs
  hash-on-read / verify-before-write and conflict refusal.
- **`.usage.json` is the one shared mutable file** with real write contention
  (curator + tools). Our tool must take the same `.usage.json.lock` flock and
  do read-modify-write, or it will race the curator.
- **Memory files:** atomic rename means readers are safe; the drift guard means a
  non-round-trippable write by us breaks Hermes' next memory write.

### 3.5 SQLite? — No shadow for skills/memory/persona

`state.db` DDL: `schema_version, sessions, messages, session_model_usage,
state_meta, gateway_routing, compression_locks, async_delegations`, plus
telegram binding tables (`SRC/hermes_state.py:746`–`:863`, `:6443`+). No
skills/memory/soul table exists. The live `state.db-wal`/`-shm` in `HOME/` are
session/message state. **Verdict: a file+sidecar tool is authoritative; it is
*not* lying — provided it also manages `.usage.json`.**

### 3.6 Write-approval staging gate

`skill_manage` writes pass through `_apply_skill_write_gate`
(`SRC/tools/skill_manager_tool.py:1259`) which can **stage** a write for human
review (`apply_skill_pending`, `:1298`) via `SRC/tools/write_approval.py`. The web
dashboard create/edit routes deliberately bypass this gate ("a write from the
authenticated dashboard IS the user acting directly"). Exact on-disk location of
staged content is not yet traced (§7).

---

## 4. Failure catalogue (empirical)

Method: imported the *installed* `agent.skill_utils.parse_frontmatter` (loader)
and `tools.skill_manager_tool._validate_frontmatter` (agent write-validator) into
Hermes' venv and fed malformed inputs. "Loader" = what the index/agent sees;
"Validator" = what blocks the agent's own writes (and web create/edit).
**Loud** = an error surfaces; **Silent** = it loads wrong with no signal — these
are what the tool must catch.

| Malformation | Loader result | Validator result | Class |
|---|---|---|---|
| **Duplicate key** (`name:` twice) | last value wins, dict OK | accepted | **Silent** |
| **CRLF** line endings | parses; `\r\n` preserved in body | accepted | Silent (benign; but breaks byte round-trip if normalised) |
| **Tab indentation** in a mapping | YAML raises → **fallback**: nested `metadata`/`hermes`/`tags` flattened to empty/`"[x]"` strings | rejects ("cannot start any token") | **Silent corruption** |
| **Unclosed `[` list** (`platforms: [linux, macos`) | fallback: `platforms` becomes the **string** `"[linux, macos"` → platform gate misfires → **skill hidden** | rejects (flow-seq error) | **Silent corruption** |
| **Missing closing `---`** | `{}`; whole file treated as body → no metadata | rejects | **Silent** |
| **No leading `---`** | `{}`; name falls back to dir, empty desc | rejects | **Silent** |
| **UTF-8 BOM before `---`** | `startswith("---")` fails → `{}`; **all frontmatter lost** | rejects | **Silent** |
| **Non-UTF-8 bytes** | `read_text(utf-8)` raises → caught → `({}, "")`; empty metadata (`_read_skill_name` uses `errors="replace"`) | n/a | **Silent degradation** |
| **Missing `name`** | dict without `name` → index uses **dir name** | rejects | **Silent** |
| **Missing `description`** | empty description in index | rejects | **Silent** |
| **Type coercion** (`name: yes`, `description: 123`) | `name=True`, `description=123` → index renders `str(...)` = `"True"`/`"123"` | **accepted** (validator does not type-check) | **Silent corruption** |
| **Frontmatter is a list / scalar / empty** | `isinstance(dict)` fails → `{}` | rejects ("must be a mapping") | **Silent** |
| **Unknown extra field** | preserved, ignored | accepted | Silent (benign) |
| **No body after frontmatter** | metadata parses fine | rejects ("must have content") | Split |
| **Oversized SKILL.md** | loads fine (only description used in index) | rejects > 100 000 chars (agent writes only) | Split |
| **Missing `SKILL.md` in a folder** | folder never discovered as a skill | n/a | Silent (folder ignored) |
| **Duplicate skill `name`** (two files) | local root wins over external; within a root, index de-dups per category | n/a | Silent |

Confirmed YAML engine facts: `CSafeLoader` in use; duplicate keys = **last-wins,
no raise**; tabs illegal.

**The validator the tool must generate is therefore two-faced:** it must (a)
reproduce `_validate_frontmatter`'s loud rejects (so we never write what Hermes'
own tool would reject), *and* (b) additionally flag the **silent** loader
behaviours above — because those never reject, yet they are precisely the
config-corruption the user is trying to prevent. A schema check that only mirrors
`_validate_frontmatter` would miss BOM, tab-flattening, unquoted-scalar coercion,
platform-typo hiding, and name/dir mismatch.

---

## 5. Gap analysis — what already exists vs. what's missing

**Already built (do not rebuild):**

- **Skill *registry/hub* CLI** — `hermes skills browse|search|install|inspect|
  audit|update|uninstall|snapshot|tap|…` (`SRC/hermes_cli/subcommands/skills.py`,
  handlers in `SRC/hermes_cli/skills_hub.py`). This installs/searches *remote*
  skills and security-scans them (`SRC/tools/skills_guard.py`). It is **not** a
  local authoring/lint tool.
- **Agent write tool** `skill_manage` with validated, atomic, gated
  create/patch/edit/delete/write_file (`SRC/tools/skill_manager_tool.py`).
- **Local web dashboard** (`SRC/hermes_cli/web_server.py`): list `GET /api/skills`
  (`:13473`), toggle `:13505`, read content `:13545`, **create** `POST` `:13564`,
  **edit (full rewrite)** `PUT /api/skills/content` `:13583`; hub proxy routes;
  memory status+sizes `GET /api/memory` `:11807`, provider switch `:11829`,
  **destructive** `POST /api/memory/reset` `:11843`; learning-graph node
  edit/delete `PUT/DELETE /api/learning/node` `:3039`/`:3027` (can rewrite a skill
  or a single memory chunk).
- **Prompt/token accounting** — `hermes prompt-size` gives an offline byte
  breakdown (system prompt, **skills index, memory, user profile**, tool schemas)
  (`SRC/hermes_cli/subcommands/prompt_size.py`). ~4 chars/token heuristic
  (`SRC/agent/prompt_builder.py:1178`).
- **Curator CLI** — `hermes curator` pin/unpin/list/restore/list-archived over
  `.usage.json` (`SRC/tools/skill_usage.py`).
- **Backups** — `hermes backup` zips the whole `HERMES_HOME` (or `--quick`); not
  skill/memory-aware.
- **Doctor** — existence/size checks only, no schema validation
  (`SRC/hermes_cli/doctor.py`).

**The gap (what to build — the missing 20-30%):**

1. **A schema validator that reproduces Hermes' *real* accept/reject *and*
   catches the silent modes** (§4) across the whole tree in one pass. Today
   validation is inline, one skill at a time, on agent writes only; nothing lints
   hand-edited files. **This is the core value.**
2. **Never-destructive mutation** — timestamped backups *outside* `HERMES_HOME`
   and soft delete by default. Hermes' foreground delete is `rmtree`, memory reset
   is `unlink`; neither snapshots first.
3. **Conflict detection** — hash-on-read / verify-before-write against the
   curator + background-review racing the file (§3.4). Nothing offers this today.
4. **A single browse view** over the whole tree with type, size, token estimate,
   lifecycle state (`.usage.json`), lock (`pinned`), and validity — the web UI
   lists skills but shows none of the `.usage.json`/validity/token dimensions
   together.
5. **Direct memory content view/edit** with the `§`-format + char-budget +
   drift-safety made explicit. Today: sizes + destructive reset, or indirect
   per-chunk edits via the learning graph.
6. **Supporting-file management** (references/templates/scripts/assets) and
   **skill delete** from a UI — absent from the web server.
7. **Reference-integrity rename/move** honouring the frontmatter-name vs
   directory-name dual identity (§2.2), `related_skills`, and slash-command/cron
   references.
8. **Resolution view** (local-vs-external precedence, §1.1) and **lock/unprotected
   dashboard** — surfacing which curation-eligible skills are *not* pinned.
9. **Token-budget delta preview** — show what an edit does to the always-loaded
   total *before* saving (prompt-size is a static after-the-fact report).

---

## 6. Inventory — this machine today

`HERMES_HOME = /home/app/.hermes` (default profile; `HERMES_HOME` env unset).
`~/.hermes` is **not** a git repo (so the git-aware requirement is a no-op here,
but must still be honoured if the user later makes it one). `SRC/` *is* a git repo
(the Hermes install), working tree clean but for one untracked `.install_method`.

**Persona:** `SOUL.md`, 514 bytes, 1 line, no frontmatter (default Nous seed
text).

**Memory:** `memories/` is **empty** — 0 memory files. So MEMORY.md/USER.md
schema was reconstructed from source, not from live files.

**Skills:** **72** `SKILL.md` files (838 KB total; ~25.7 KB is frontmatter),
category-nested, all UTF-8, all with valid opening `---`, **no CRLF**. Support
dirs present: `references/` ×25, `templates/` ×9, `scripts/` ×13, `assets/` ×0.
**17 category `DESCRIPTION.md`** files (16 with frontmatter; **`apple/DESCRIPTION.md`
is plain prose with no `---`** → its category description is silently dropped by
`prompt_builder.py:1555`). Largest skill: `research-paper-writing/SKILL.md`
(103 674 bytes, > the 100 000-char agent-write cap — fine for a bundled skill,
but a tool "edit" of it via the agent path would be rejected). Sidecars present:
`.bundled_manifest` (3365 B), `.curator_state` (337 B); **no `.usage.json`**
(nothing agent-created/used yet), **no `.skills_prompt_snapshot.json`** yet.

**Schema-shape observations (would-be validator findings):**

- **Union of top-level keys seen (15):** `name, description, version, author,
  license, platforms, metadata, prerequisites, dependencies, tags, title,
  triggers, compatibility, setup, required_credential_files`. Only `name`,
  `description`, `platforms`, `metadata.hermes.*` are runtime-consumed (§2.2).
- **`name:` ≠ directory name** (5): `lm-evaluation-harness`→`evaluating-llms-harness`,
  `vllm`→`serving-llms-vllm`, `audiocraft`→`audiocraft-audio-generation`,
  `segment-anything`→`segment-anything-model` (and dir `apple-notes` etc. match).
  These trip the dual-identity issue (§2.2).
- **Top-level `tags`** instead of `metadata.hermes.tags` (4): `popular-web-designs`,
  `songwriting-and-ai-music`, `huggingface-hub`, `polymarket` → tags not where
  `extract_skill_conditions` looks (harmless today since tags aren't runtime-read,
  but non-canonical).
- **Top-level `triggers`** (2): `popular-web-designs`, `songwriting-and-ai-music`
  — not a field any traced code reads.
- 5 skills omit `version`; several omit `author`/`license`;
  `powerpoint` has a free-text (non-SPDX) `license`. None of these break loading
  (advisory fields).
- No non-UTF-8 or CRLF text files; the only non-UTF-8 bytes under `skills/` are
  binary PDFs in `research-paper-writing/templates/` (expected).

**Always-loaded cost (paid every session)** = `SOUL.md` (514 B) + memory snapshot
(0 B today; budgeted 2200+1375 chars) + the **skills index** (72 lines of
`name: <=60-char desc>` grouped by ~13 categories with their DESCRIPTION headers)
— i.e. the index, *not* the 838 KB of bodies. The bodies are on-demand. A precise
token number needs the same accounting `hermes prompt-size` uses (no tokenizer is
installed here — `tiktoken` import fails — so the tool should ship the
~4-chars/token heuristic Hermes itself uses, and optionally the real tokenizer if
present).

---

## 7. Unverified assumptions & open questions

Kept deliberately honest — these are *not* confirmed from source and must not be
treated as fact when designing the tool:

1. **`web_server.py` handler internals.** Route *existence* and paths were
   confirmed first-hand by grep; the *behaviour* of each handler (exact backup
   semantics, whether create bypasses the approval gate) was mapped in a secondary
   read pass, not line-by-line re-verified by me. Re-open the specific handlers
   before depending on their internals.
2. **Where staged (write-approval) content lives on disk.** `_apply_skill_write_gate`
   / `apply_skill_pending` and `SRC/tools/write_approval.py` implement a staging
   gate, but I did not trace the on-disk staging location or format. Needed if the
   tool must coexist with pending (un-applied) agent writes.
3. **Is `tags` / `triggers` / `prerequisites` consumed anywhere?** The
   discovery/index/gating path does **not** read them. Hub search
   (`skills_hub.py`), the website generator, or slash-command routing *might*.
   Classified as advisory pending a search of those consumers.
4. **SOUL.md writer.** Seeded by `hermes_cli/default_soul.py`; I did not find a
   dedicated *edit* tool (it appears to be edited via generic file tools / claw /
   profile import). Confirm there is no schema/validation applied to SOUL.md on
   write.
5. **External `skills.external_dirs`** — none configured in this `config.yaml`
   (`skills:` block at `HOME/config.yaml:663`, `external_dirs` commented at `:674`).
   Precedence logic (§1.1) was read from source but not exercised against a real
   external dir on this machine.
6. **Curator cadence / trigger** — I mapped the transition *logic* (`curator.py`)
   and config keys (`stale_after_days`, `archive_after_days`, `prune_builtins`) but
   not *when/how often* the curator tick fires in a running gateway. Relevant to how
   aggressively conflict-detection must guard.
7. **`.skills_prompt_snapshot.json` cross-process behaviour** — I confirmed the
   manifest self-invalidation and the in-process LRU, and that the learning path
   clears both after writes. I did not verify whether a *long-running gateway* also
   re-reads the snapshot mid-session or only at session start; §3.4's guidance
   (clear the snapshot after our writes) is the safe assumption pending that check.
8. **Windows/profile-mode paths** — all path logic goes through `get_hermes_home()`;
   the profile/Docker branches (`get_default_hermes_root`, `SRC/hermes_constants.py:113`)
   were read but not exercised (single default profile here).

---

## Appendix A — Prior beliefs, verified against installed source

| Prior belief | Verdict | Evidence |
|---|---|---|
| Home is `~/.hermes`, overridable by `HERMES_HOME`, via a single helper | **Confirmed** | `SRC/hermes_constants.py:55`–`:110`, `:968` |
| Profiles fully isolated (own config/env/persona/memories/sessions/skills/cron/db) | **Confirmed** (profile = its own `HERMES_HOME`) | `SRC/agent/file_safety.py:375` (`PROFILE_SCOPED_AREAS`), `SRC/hermes_constants.py:113` |
| Persona file at home root; memories under `memories/`; loaded into the system prompt every session | **Confirmed**, but persona file is **`SOUL.md`** (raw prose, no frontmatter), and memory is **`MEMORY.md` + `USER.md`** as a **frozen snapshot** | `SRC/agent/prompt_builder.py:1819`; `SRC/tools/memory_tool.py:5`, `:11` |
| Skills under `skills/`, one folder per skill, optional category nesting, `SKILL.md` at the leaf; sibling references/templates/scripts/assets | **Confirmed** | `SRC/agent/skill_utils.py:50`, `:785`; tree inventory §6 |
| `SKILL.md` frontmatter: name + description, optional version/author/platform guards/requirement predicates/nested metadata tags | **Partly confirmed / corrected**: only `name`, `description`, `platforms`, `environments`, and `metadata.hermes.{requires_*/fallback_for_*/config}` are runtime-consumed. `version/author/license/tags/...` are **advisory, ignored by the agent** | §2.2 |
| Skills load only when invoked → cost nothing per session | **Corrected**: skill **bodies** are on-demand, but a **name+description index of every skill is loaded every session** and does cost tokens | `SRC/agent/prompt_builder.py:1445`, `:1669` |
| Agent creates/edits its own skills and memory; a write-approval setting can stage writes | **Confirmed** | `SRC/tools/skill_manager_tool.py:1259`; `SRC/tools/memory_tool.py`; `SRC/tools/write_approval.py` |
| Background curator moves skills active→stale→archived | **Confirmed**; state in `.usage.json`, archive = soft move to `.archive/` | `SRC/agent/curator.py:306`; `SRC/tools/skill_usage.py:53`, `:696` |
| Hand-edited skills can be regenerated unless **locked in frontmatter** | **Corrected**: the lock is **`pinned` in `.usage.json`, not frontmatter**, and it only blocks **deletion/archival — not `patch`/`edit`**. No content-regeneration lock exists | `SRC/tools/skill_usage.py:672`; `SRC/tools/skill_manager_tool.py:270`–`:291` |
| External skill dirs merge via config; local wins on collision | **Confirmed** | `SRC/agent/skill_utils.py:420`, `SRC/agent/prompt_builder.py:1575`–`:1604` |
| Sessions in SQLite; cron in JSON; check if skill/memory shadow into the DB | **Confirmed + answered**: sessions/messages in `state.db`; **skill/memory state does NOT shadow into SQLite** — lifecycle in `.usage.json`, memory in files | `SRC/hermes_state.py:746`–`:863`; `SRC/tools/skill_usage.py:85` |

---

*End of Phase 1. Per the brief: stopping here for review. No design or build work
has begun; nothing under `HERMES_HOME` was modified.*
