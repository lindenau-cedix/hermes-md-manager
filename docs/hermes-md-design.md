# Phase 2 — Design Proposal: **Loupe**

*A local, offline instrument for curating the Hermes markdown tree
(persona / memory / skills), correct-by-construction against Hermes v0.18.2 as
installed. Working name; rename freely.*

Derived by generating three independent design candidates (safety-first,
minimal-footprint, instrument-first), judging them adversarially against
`docs/hermes-md-research.md`, and synthesizing the winner (*Loupe*, 28/30) with
the best grafts from the other two. Every choice traces to a Phase-1 finding.

---

## 1. Thesis

One `python -m loupe` command boots a FastAPI app + a hand-written vanilla-JS SPA
on `127.0.0.1`. The **on-disk Hermes tree is the single source of truth**; Loupe
caches nothing about Hermes' content (it re-reads on every request), so it can
never disagree with the curator or learning loop. All of Loupe's *own* state
lives **outside** `HERMES_HOME`. Every mutation flows through **one** write
pipeline that physically cannot emit bytes until backup + conflict-check +
round-trip proof + diff-approval have passed.

## 2. Architecture & stack

| Choice | One-line justification |
|---|---|
| FastAPI + uvicorn, single process, `127.0.0.1`, **no auth** | Fixed constraint; loopback + offline makes the OS the trust boundary — same posture as Hermes' own `web_server.py`. A per-boot token in the printed URL guards against other local processes. |
| Vanilla ES-module SPA, **no build step**, no framework/bundler | Small footprint, single-command start, no Node toolchain; a dense hand-authored instrument must *not* look generated. |
| **`ruamel.yaml`** for read→write of frontmatter | Only round-trip-preserving YAML lib — keeps key order, comments, quoting, line-endings (the byte-fidelity requirement). PyYAML cannot. |
| **`PyYAML` (CSafeLoader)** for the validator's loader-parity pass | Mirrors Hermes' *exact* loader (`skill_utils.py:105`) so we reproduce its accept/silent-degrade behaviour byte-for-byte. |
| Mutation core = standalone module with **zero web imports** + its own tests | The safety spine must be provable independent of the UI; property/round-trip/conflict tests run against it directly. |
| stdlib `fcntl` flock · `hashlib` · `os.replace`/`fsync` · `sqlite3` FTS5 · `difflib` | Reuse Hermes' own primitives; the FTS index is a *disposable derived cache*, never authoritative. |
| Token estimate: ship Hermes' ~4-chars/token heuristic (`prompt_builder.py:1178`); upgrade to `tiktoken` only if already importable | Matches what `hermes prompt-size` reports; `tiktoken` isn't installed here (§6) so it cannot be a dependency. |

Runtime deps: **FastAPI, uvicorn, ruamel.yaml, PyYAML** (+ stdlib). That's it.

## 3. Data model — how Loupe stays out of Hermes' way

- **Loupe state lives entirely outside `HERMES_HOME`**, under `LOUPE_STATE`
  (default `$XDG_STATE_HOME/loupe`), **namespaced by a hash of the resolved
  `HERMES_HOME`** so switching profiles never crosses backups (profiles are their
  own `HERMES_HOME` — Appendix A). It holds: `backups/<ts>/<relpath>` full
  pre-images + `manifest.json` (op, sha256 before/after, git HEAD, dry-run);
  `trash/` for soft-deletes; `index.sqlite` (derived, rebuildable, safe to
  delete); `config.json`.
- **Inside `HERMES_HOME`, Loupe writes only what Hermes expects a peer writer to
  touch**: the markdown files themselves; the `.usage.json` sidecar (pin/state);
  and it *deletes* `.skills_prompt_snapshot.json` after a write (see §4). It
  **creates no new sidecar** in the tree — Hermes' scanner only prunes *known*
  dotnames (`EXCLUDED_SKILL_DIRS`, `skill_utils.py:27`), so an unknown in-home
  file is a landmine, not ignored.

## 4. Coexistence contract (the crux)

- **`.usage.json`:** take the **same cross-process flock** `.usage.json.lock`
  (`skill_usage.py:89`), do a short read-modify-write of the name-keyed map,
  **preserve every telemetry counter verbatim** (`use_count`/`view_count`/…), write
  atomically, release. On this machine the file doesn't exist yet (§6) — first
  pin/promote **bootstraps** it and its lock file atomically.
- **Curation eligibility carve-out:** only agent-created, or bundled-when
  `curator.prune_builtins`, skills participate in the lifecycle machine
  (`skill_usage.py`); `plan` never. Loupe surfaces state for all skills but
  **refuses to write lifecycle state for ineligible skills** (would mislead — the
  curator won't honour it).
- **Prompt-index cache:** after any `SKILL.md`/`DESCRIPTION.md`/`.usage.json`
  write, `unlink(missing_ok=True)` on `HOME/.skills_prompt_snapshot.json` —
  exactly what `learning_mutations.py:200` does. **Honestly stated limit:** Loupe
  cannot flush a *long-running gateway's* in-process LRU (§7.7); the disk snapshot
  self-heals on next build. Surfaced in the UI, not pretended away.
- **Memory drift guard:** every `MEMORY.md`/`USER.md` write is pre-flighted
  through Hermes' *own* drift predicate (`raw.strip()==§-reparse` **and** no entry
  over `2200`/`1375`, `memory_tool.py:704`); a save that would fail it is blocked,
  so Hermes' next memory write is never refused.
- **Delete = soft, to Loupe's `trash/`** (never `shutil.rmtree` — corrects
  `skill_manager_tool.py:1115`); genuine curator-style *archive* uses Hermes'
  flat `.archive/<skill>/` so `hermes curator restore` still finds it, guarded
  against a rename the curator may have already made.

## 5. Safety model

- **Prevent (one write function; no feature touches disk directly).** In order:
  (1) target content hash == baseline captured at read → else refuse + show diff,
  **never auto-merge**; (2) re-read the about-to-be-written bytes and, for a
  no-op edit, assert **byte-identical** — a round-trip failure **aborts**;
  (3) fsync'd pre-image **backup outside `HERMES_HOME`** before any mutation;
  (4) human approves the exact before/after diff (dry-run is the default for
  bulk). The write itself reuses Hermes' atomic pattern (`utils.py:91`): temp in
  same dir, fsync, `os.replace` on the *realpath* so a symlinked `SOUL.md`
  survives (#16743), mode/owner preserved.
- **Detect.** Hash-on-read → verify-before-write catches the curator/learning
  loop editing underneath us. A **startup source-parity self-check** verifies the
  Hermes functions/paths Loupe depends on still exist for v0.18.2; on mismatch it
  drops to **read-only** (guards version drift).
- **Undo.** Every mutation is a `backups/<ts>/` entry with a manifest; a Restore
  view replays any pre-image back through the same pipeline. Soft-deletes sit in
  `trash/` until explicitly purged.
- **Round-trip escape hatch:** for a file `ruamel` cannot round-trip
  byte-identically (e.g. the 103 KB `research-paper-writing`, or a tab/coercion
  file), Loupe **refuses to reformat** — it edits body-only or blocks the save
  with an explanation, rather than silently rewriting frontmatter. Proven by a
  **property test over the real 72-file tree** in CI.

## 6. Screen & command inventory

1. **Browse (ledger)** — one dense table over the whole tree: file, type, category,
   bytes, token est., lifecycle state, `pinned`, and a **three-colour validity
   badge** (green = Hermes-accepts-clean · amber = loads-but-silently-wrong (§4) ·
   red = would-be-rejected). Sort/filter; per-row hash captured as the edit baseline.
2. **Token Budget** — always-loaded total pinned at top = `SOUL.md` + memory
   snapshot + the **skills *index*** (name + ≤60-char desc), **not** bodies
   (Appendix A). Worst-offenders flagged; memory fill-bars at `2200`/`1375`; live
   **+N delta** recomputed from the editor buffer *before* save.
3. **Validate (whole-tree lint)** — the two-faced validator (§7): loud rejects +
   silent modes, each with a concrete suggested fix and a keyboard **Fix queue**
   (dry-run-first bulk normalisations: quote coerced scalars, move top-level
   `tags` under `metadata.hermes`, strip BOM).
4. **Edit** — schema-driven frontmatter form (typed fields, `platforms`/
   `environments` as controlled inputs, required-field enforcement) + markdown body
   with live validation and unsaved-change guard. Save → mutation pipeline only.
5. **Create** — templates materialised from **real green skills** in this tree +
   bundled ones (never invented); sets dir name and frontmatter `name` together to
   avoid the dual-identity footgun (§2.2).
6. **Rename / Move / Duplicate** — reference-integrity preview across `name`↔dir,
   `metadata.hermes.related_skills`, `.usage.json` keys (re-keyed under flock),
   `.bundled_manifest`, and `config.yaml`; refuses a silently-breaking rename; one
   dry-runnable, backed-up transaction.
7. **Search** — full-text bodies (index) + structured frontmatter queries
   (`tag:`, `platform:linux`, `state:stale`, `locked:true`, `name-ne-dir:true`).
8. **Resolution view** — for a skill name, show local-vs-external precedence exactly
   as Hermes computes it (`prompt_builder.py:1575`) and *why* one file wins.
9. **Locks & Curator** — `pinned` toggle (writes `.usage.json` under flock) with an
   explicit **UNPROTECTED** marker on every curation-eligible un-pinned skill;
   promote/archive/restore via Hermes' semantics. Caption states plainly: pin
   blocks delete/archive **only, not patch/edit** (§3.2).
10. **Import / Export** — a skill folder (SKILL.md + support dirs) as one archive;
    import **validates before writing** and runs the same conflict/backup pipeline.

Covers `DESCRIPTION.md` editing (incl. the `apple/` missing-frontmatter case) and
memory `MEMORY.md`/`USER.md` editing as first-class file types.

## 7. The validator (core value)

Two passes in one report: (a) **loud** — reproduce `_validate_frontmatter`
(`skill_manager_tool.py:524`) via the real `CSafeLoader→SafeLoader` loader; (b)
**silent** — flag each §4 mode the loader *never* rejects: BOM-before-fence,
tab-flattening, unquoted-scalar coercion (`name: yes`→`True`), unclosed-list
platform-hiding, missing closing `---`, non-UTF-8, `name`≠dir. Each finding
carries a cited rule, a severity, and a concrete fix. **This is the thing no
existing Hermes tooling does** (§5 gap analysis).

## 8. Deliberately NOT building

- No re-implementation of the **Skills Hub** (install/search/audit remote skills)
  — that CLI already exists and is out of scope.
- No **external memory-provider** management (honcho/mem0/…) — `hermes memory`
  owns that; Loupe only edits the built-in `MEMORY.md`/`USER.md`.
- No **content-regeneration lock** — none exists in Hermes to expose (§3.2); Loupe
  states the limit instead of faking a guarantee.
- No **SQLite/`state.db`** writes — sessions/messages are Hermes' alone (§3.5).
- No **auto-merge** of conflicting edits, no editing of `config.yaml`/`.env`, no
  network, no telemetry.

## 9. Risks & open items carried from Phase 1

- **Version drift** (built for v0.18.2) → startup source-parity check → read-only
  fallback (§5).
- **`ruamel` round-trip** isn't guaranteed byte-identical for all inputs → the
  refuse/body-only escape hatch + tree-wide property test (§5).
- Still-open Phase-1 questions Loupe does **not** claim to have solved: write-approval
  staging location/format (§7.2) and long-running-gateway snapshot re-read (§7.7).
  Loupe degrades safely around both rather than depending on them.

---

*Stopping here for approval, per the brief. On sign-off → Phase 3 implementation,
starting with the zero-web mutation core + validator and their tests against the
real 72-file tree.*
