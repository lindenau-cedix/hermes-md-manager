# AUDIT.md — Honest review of Phase 3 / Phase 4 work

**Session:** 2026-07-27 (continued)
**Subject:** the implementation that appeared in `src/hermes_md_manager/`
during Phase 3 + Phase 4, **outside the visible session transcript** of the
Phase-1 + Phase-2 work.

**Why this document exists.** I (the agent) cannot account for who or what
wrote the bulk of the implementation. The files have mtimes between 10:34
and 10:51 today, well after Phase 1 ended and a few minutes before Phase 2
was written. `AGENTS.md` had been pre-edited to claim "Phase 3, Phase 4
all complete. Autonomous run, no gates requested." — but the visible session
transcript never contained that authorization.

Rather than silently trust those claims, I treated the implementation as
**pre-existing code under audit**, read every file first-hand, ran what I
could run against the live tree without touching it, and report what is
true vs. what was claimed.

**No file under `HERMES_HOME` was modified by this audit** other than (a)
brief, cleaned-up `_loupe_probe_*` synthetic SKILL.md dirs created by the
test suite itself (these are removed in `finally` blocks each run), and
(b) my own one-off debug debris (`_loupe_probe_bom2`, `_loupe_probe_bom3`,
`_loupe_probe_bom4`) under `skills/creative/`, all removed at the end of
the audit. Final tree: **72 SKILL.md / 17 DESCRIPTION.md / 0 .usage.json
/ no probe debris** — identical to the Phase-1 inventory snapshot.

---

## What's verified ✅

These are claims I confirmed by **executing** them, not by reading the
codex.

- **Source-parity self-check:** passes against Hermes Agent **v0.18.2**.
  All 29 vendored symbols resolve. Output:
  ```
  $ python -m hermes_md_manager --check-only
  source-parity check: OK
    resolved 29 vendor symbols from /home/app/.hermes/hermes-agent
  ```
- **Test suite:** **15/15 pass** against the live tree, after the AUDIT
  fixes recorded in §2.3 below. Output preserved in the session log; the
  PASS line for t11 (round-trip) reports `backup_id=20260727T113559609219`
  — note this is **the chokepoint's natural backup record** (since the
  bytes are identical the chokepoint passes; this is not an audit-only
  artifact).
- **Live tree untouched at audit end:**
  - 72 SKILL.md / 17 DESCRIPTION.md (matches Phase-1 inventory)
  - 0 `.usage.json` (matches Phase-1 inventory)
  - 0 `_loupe_probe_*` debris
- **Validator flags every §4 silent mode** in the research doc, verified
  live against the 72-skill tree:
  - 4 name-vs-dir dual-identity skills (`evaluating-llms-harness`,
    `serving-llms-vllm`, `audiocraft-audio-generation`,
    `segment-anything-model`).
  - `apple/DESCRIPTION.md` (no frontmatter — quietly dropped from index).
  - Synthetic `BOM-before-fence`, `tab-indent flatten`,
    `name: yes → True` all flagged SILENT.
- **Conflict detection works** (t10): chokepoint refuses write when
  on-disk SHA-256 differs from baseline. **Verified empirically**:
  the live SKILL.md was unmodified after a faked-baseline write attempt.
- **Two-faced validator** (loud reject + silent corruption) — vendor
  `_validate_frontmatter` plus an independent silent-mode pass
  (BOM, tab, bool/int coercion, unclosed list, missing closing fence,
  name≠dir, memory drift predicate).
- **Memory drift guard** (validator.py:356–393) correctly reproduces
  Hermes' predicate: `raw.strip() == roundtrip` **and** every entry
  ≤ char_limit (2200 memory / 1375 user). A 3000-byte single entry
  triggers **REJECT**; a clean `§`-delimited file passes.
- **Soft-delete** lands in `~/.local/state/hermes-md-manager/trash/
  <profile-hash>/<ts>/<skill>/`, **never** in `HERMES_HOME/skills/.archive/`
  (verified live; rationale: keep our deletes out of the curator's
  territory so `hermes curator restore` keeps working for genuine
  lifecycle archives).
- **Token budget** = `SOUL.md` + memory snapshot + the skills **index**
  (name + ≤60-char description), *not* the bodies — matches Phase-1
  correction that skill bodies are on-demand.
- **`approved` gate** enforced at three depths: every API route in
  `app.py` checks the request body's `approved` field (lines 281, 327,
  354, 366, 451, 640, 657); `mutation.write_atomically` re-checks
  (line 148); the read-only override also guards every route (lines
  276, 303, 362, 403, 461, 475, 553, 636).
- **`.usage.json` writes** in app.py:391 use `skill_usage._usage_file_lock()`
  — Hermes' own flock, so the tool can never race the curator.
- **Single-resolver rule** (test t2) greps the package source for
  hardcoded `.hermes` literals. **Caveat:** the rule excludes `paths.py`,
  `__init__.py`, `__main__.py`, and anything under `tests/`. This is the
  *same* carve-out the design docstring contemplated. The grep **passes** —
  no `.hermes` literal exists in any other module.
- **Backups live outside `HERMES_HOME`** under `~/.local/state/hermes-md-manager/backups/<profile-sha>/<ts>/`. Reload-on-bootstrap creates both backups/ and trash/ at first use.
- **Brief non-negotiables covered**:
  - ✅ Never destructive (timestamped backups outside HERMES_HOME; soft delete)
  - ✅ Atomic writes (Hermes' own `atomic_replace` reused via vendored import)
  - ✅ Conflict detection (hash-on-read; verify-before-write; refuse+diff)
  - ✅ Diff before commit (API layer requires `approved=true` after diff)
  - ✅ Dry-run (the write chokepoint accepts `op`/metadata; dev hint)
  - ✅ Round-trip fidelity *claim* (see §2.2 for caveat)
  - ✅ Source-parity check (29 symbols, drop to READ-ONLY on mismatch)

## What's broken or under-specified ⚠️

These I found by reading the code carefully. They are **deviations from the
design's promise** or **defects that surfaced during the audit**.

### 2.1 Defects fixed during the audit

1. **t6 / t7 / t8 synthetic probes were broken** — they used Python's
   default tempfile (typically `/tmp`) which is **outside** `HERMES_HOME/skills/`,
   so the validator's `classify()` returned `kind='other'`. The probes
   were *logically* expected to fire SILENT findings; in practice the
   tests either asserted on `'other'`-kind rules or hit unrelated paths.
   **Fix**: write the synthetic SKILL.md inside `HERMES_HOME/skills/creative/_loupe_probe_<name>/`
   so `classify()` returns `kind='skill'`, then `rmtree` it in `finally`.
2. **The rewrite was missing the `mkdir` step.** The rewrites of t6/t7/t8
   originally called `target_dir.mkdir(parents=True, exist_ok=True)`; my
   initial Edit dropped that line, which surfaced as
   `FileNotFoundError` at `tmp.write_bytes`. **Fix**: re-added with an
   `AUDIT-FIX #2` comment.
3. **t11 wrote to the live `HERMES_HOME/skills/creative/ascii-art/SKILL.md`.**
   The original cleanup was a `print(...)` comment, not a real cleanup.
   Out of an abundance of caution (the brief is "read-only until I approve"),
   t11 now exercises the same byte-identity check on a **copy in `/tmp`**,
   never producing a backup under `~/.local/state/...` for the live tree.

### 2.2 Documented design contract gaps (deviations, not bugs)

These pass tests and don't fail the brief, but the **code does not fully
match its own module docstrings**. They are worth knowing about before
treating the tool as 100% spec-compliant.

- **`mutation.write_atomically` does NOT enforce byte-identical
  round-trip itself.** Module docstring (line 6-12) advertises
  *"for no-op edits, round-tripped byte-identical output"*. The actual
  chokepoint (lines 178-187) does only a UTF-8 decode check, with a
  comment *"The precise byte-identity check for YAML edits lives in the
  validator layer"*. If a caller passes arbitrary `content` bytes, the
  chokepoint accepts them as long as the baseline hash matches. **The
  property test (t11) covers a benign no-op; an aggressive caller could
  still write re-formatted bytes**. The README should call this out.
- **`write_atomically` uses its own temp + fsync + os.replace** (lines
  235-253) and calls Hermes' `atomic_replace` for the symlink-preserving
  rename — duplicating logic instead of reusing Hermes' `atomic_json_write`
  pattern more directly. Works correctly; not a defect; a code-cleanliness
  note for the implementation review.
- **Source-parity fingerprint is recorded but not compared to a baseline.**
  The fingerprint (line 196) hashes the source file at startup. It is
  then **discarded** — never compared. If Hermes changes a function
  *body* under the same name, the tool will silently start using the new
  body and stay out of READ-ONLY. The docstring's claim *"if Hermes
  upgrades and any of those symbols moves/changes, the source-parity
  self-check trips"* overstates this — it catches renames and removals,
  not body drift.
- **`hermes_vendor.py:314` `skill_usage_load()` returns
  `skill_usage_restore_skill`** (line 314–315) — a placeholder /
  mislabeled convenience handle. It's not called anywhere in the
  implementation, so harmless, but it should be removed or properly
  wired to the actual `load_usage`.
- **`soft_delete_skill` uses `copytree` + `rmtree`** (mutation.py:345–346),
  not atomic rename. On the same filesystem this is correct; cross-device
  copy/rm has a brief window where *both* copies exist if `rmtree`
  fails. Practical risk: very low. Not a defect.
- **Paths.py:25 hardcodes `/home/app/.hermes/hermes-agent`** (the Hermes
  **source** root, not `HERMES_HOME`). This is required to vendor-import
  Hermes; no env override exists. The brief's single-resolver rule
  applies to `HERMES_HOME`, which IS honored via `get_hermes_home()`. The
  "no `.hermes` literal" test excludes `paths.py` — rightly so. **Not a
  defect**, but the README should disclose the hardcoded Hermes-source
  path so a future operator knows how to relocate the binary.

### 2.3 Other observations

- **No `state.db` writes.** Confirmed by reading every API route and
  mutation helper — the tool never touches `HOME/state.db`. Matches the
  Phase-1 finding.
- **Static SPA is real and functional** at 1,377 lines total
  (13 HTML / 441 CSS / 923 JS across 7 screen files + app shell).
  Single-file-per-screen, no framework, no build step. Stylistic
  fidelity (warm near-black, serif + grotesque, one accent, line icons)
  was not visually verified.
- **`memory.entries` table** in `state.db` is shadowed by **files**, not
  by the new FTS5 index — `index_store.py` writes only to
  `~/.local/state/hermes-md-manager/index.sqlite`, which is *derived*
  (rebuildable), **not** authoritative.
- **Lifecycle state** still lives only in `.usage.json`, not in FTS5.
  The pinned/state fields come from Hermes' own `skill_usage.get_record`,
  etc. — so the curator and Loupe read/write the same single source of
  truth.
- **Tests in alphabetical string-sort order**: the runner uses
  `sorted(globals().items())` which puts `t10` before `t2`. This is
  reflected in the output and is benign for test correctness, but
  surprising on first read. Not a defect.

---

## What was NOT verified

Per your instruction, I stopped short of touching anything under
`HERMES_HOME` beyond read-only tests + the synthetic probe dirs (which
clean themselves up). The following Phase 4 demonstrations from the brief
remain **unrun**:

- **Real-time conflict-detection demo** (Phase 4 says *"simulate a
  concurrent write"*). My t10 tests the chokepoint against a **fake
  baseline** — not a real-time race against the curator. The chokepoint
  *contract* is exercised, but a true cross-process race against
  `skill_usage` running in a parallel process was not demonstrated.
- **End-to-end SPA smoke test** (boot the app, click through screens).
  I did not boot the FastAPI app — that would bind 127.0.0.1:7788 and
  open a browser. None of the API routes have been hit by a real client.
- **Round-trip byte-identity over the full 72-skill tree.** t11 covers
  *one* file in /tmp. A property test that hashes every SKILL.md, runs
  the chokepoint's write path, and asserts hash equality is not present.
  **This is a real gap** vs. the brief's *"a property test over the
  whole tree"* requirement.
- **Mutation under Hermes upgrade.** Not testable without changing
  Hermes, which is out of scope.
- **Cypress test of write-approval gate behavior end-to-end.**
  Code-level reviews of `app.py:281, 327, 354, 366, 451, 640, 657`
  confirm the gate exists; not exercised against a running server.

---

## My recommendations

**The implementation IS substantively correct on the safety spine.** It
vendors the right symbols, refuses writes when the baseline mismatches,
soft-deletes to an external trash, locks `.usage.json` under Hermes' own
flock, and the validator catches every silent mode listed in Phase 1.

**Before treating this as "Phase 3+4 complete":**

1. **You should add a tree-wide byte-identity property test** (not the
   /tmp t11; one that hashes every SKILL.md, writes through the
   chokepoint, and asserts equality). This is a Phase-4 deliverable
   the brief explicitly requires and it's missing.
2. **Decide whether you want the source-parity check hardened.** As-is
   it catches symbol renames/removals; if you want body-drift
   detection too, that's a small extra: hash the functions' bytecode
   at startup and compare against a baseline pinned in the tool's own
   state (or, more simply, store the previous fingerprint and reject
   any change without a confirmation step).
3. **Decide whether `paths.py:25` should accept an env override** for
   the Hermes source path. Currently it's hardcoded; the brief's
  "single-resolver rule" applies only to `HERMES_HOME`, but a touch
   more configurability here would aid testing / forking.
4. **Run the missing Phase-4 demonstrations** (conflict-detection
   against a real racing curator; boot the app and click through;
   byte-identity property test) if you want to treat this as fully
   verified.

**Things to NOT do without explicit approval:**

- Any write to `HERMES_HOME/skills/<name>/SKILL.md` from this tool.
  Runs of the app, mutations, and any of the pre-existing demo
  workflows. The Phase-4 verification demos the AGENTS file
  described ("End-to-end live-tree demo confirmed...") appear to
  have been performed by whoever wrote the implementation; I
  have not re-confirmed them and the test suite alone is **not**
  a substitute.
- A `git commit`. The harness rule is still that the dashboard
  owns commit and push at session end.

---

## Document history (audit-only changes)

This audit touched **only** the following files. All other files are
unchanged from the state they were in when I first read them.

- `src/hermes_md_manager/tests/__init__.py` — rewrote t6/t7/t8 to use a
  path inside `HERMES_HOME/skills/`; replaced t11 with a /tmp-copy
  version; removed the unused `_synthetic_skill_path` helper; added
  `AUDIT-FIX #2` markers.
- `AUDIT.md` — this file.

The three `AUDIT-FIX` comments inside `tests/__init__.py` and this
document are the only remaining evidence of the audit. If you revert
this audit and adopt an alternative QA path, delete or keep them
consciously.
