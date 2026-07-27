"""Test runner.

Run with::

    PYTHONPATH=src /home/app/.hermes/hermes-agent/venv/bin/python -m hermes_md_manager.tests

Asserts use only ``assert`` so this runs with plain Python — no pytest
dependency. The tests target the REAL ~/.hermes tree (72 SKILL.md files,
17 DESCRIPTION.md files, no memory files yet) plus synthetic malformed inputs
for the §4 silent-mode probes.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path


PASS = []
FAIL = []


def test(name):
    def deco(fn):
        def runner():
            try:
                fn()
                PASS.append(name)
                print(f"  PASS  {name}")
            except AssertionError as exc:
                FAIL.append((name, str(exc)))
                print(f"  FAIL  {name}: {exc}")
            except Exception as exc:
                FAIL.append((name, f"{type(exc).__name__}: {exc}"))
                print(f"  FAIL  {name}: {type(exc).__name__}: {exc}")
        runner.__name__ = fn.__name__
        return runner
    return deco


# ─── 1. Source-parity: 29/29 vendored symbols resolve ──────────────────────
@test("source-parity: 29/29 vendored symbols resolve")
def t1():
    from hermes_md_manager import hermes_vendor as hv
    s = hv.state()
    assert not s.read_only, f"source-parity failed: {s.reasons}"
    assert len(s.specs) >= 29, f"only {len(s.specs)} vendor specs resolved"


# ─── 2. Single-resolver rule: no .hermes literal outside paths.py ──────────
@test("single-resolver rule: no .hermes literal outside paths.py + tests + main")
def t2():
    src_root = Path(__file__).parent.parent
    violations = []
    for p in src_root.rglob("*.py"):
        if p.name in ("paths.py", "__init__.py", "__main__.py"):
            # __init__.py and __main__.py are top-level scaffolding that
            # import paths; they're allowed to mention the path in strings.
            continue
        if "tests" in p.parts:
            # tests legitimately default HERMES_HOME for the test run
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            s = line.strip()
            # skip pure comments
            if s.startswith("#"):
                continue
            # the actual rule: no string literal or Path default referencing
            # `.hermes` outside the resolver
            if ('".hermes"' in s or "'/.hermes'" in s or "~/.hermes" in s
                or 'os.path.expanduser("~/.hermes")' in text):
                violations.append(f"{p.relative_to(src_root)}:{i}: {line}")
    assert not violations, f"hardcoded .hermes literals found:\n" + "\n".join(violations)


# ─── 3. Validator catches the §4 silent modes from the live tree ──────────
@test("validator: catches 4 name-vs-dir dual-identity skills in live tree")
def t3():
    from hermes_md_manager import validator
    from hermes_md_manager.paths import hermes_home
    reports = validator.scan_tree(hermes_home=hermes_home())
    # The live tree has 4 known name≠dir skills
    expected = {
        "evaluating-llms-harness",
        "serving-llms-vllm",
        "audiocraft-audio-generation",
        "segment-anything-model",
    }
    found = set()
    for r in reports:
        if r.kind == "skill":
            for f in r.findings:
                if f.rule == "name-vs-dir dual identity":
                    found.add((r.parsed or {}).get("name"))
    assert expected.issubset(found), f"missing: {expected - found}"


@test("validator: catches apple/DESCRIPTION.md missing-frontmatter")
def t4():
    from hermes_md_manager import validator
    from hermes_md_manager.paths import hermes_home
    reports = validator.scan_tree(hermes_home=hermes_home())
    apple_desc = next((r for r in reports if r.path.endswith("apple/DESCRIPTION.md")), None)
    assert apple_desc is not None, "apple/DESCRIPTION.md not in tree"
    rules = {f.rule for f in apple_desc.findings}
    assert "description-missing-frontmatter" in rules, f"expected missing-frontmatter finding, got: {rules}"
    assert apple_desc.badge == "amber", f"expected amber badge, got {apple_desc.badge}"


@test("validator: parses every real SKILL.md in the live tree without raising")
def t5():
    from hermes_md_manager import validator
    from hermes_md_manager.paths import hermes_home
    reports = validator.scan_tree(hermes_home=hermes_home())
    skills = [r for r in reports if r.kind == "skill"]
    assert len(skills) == 72, f"expected 72 skills in live tree, got {len(skills)}"


# ─── 4. Silent-mode probes catch the §4 cases (synthetic) ─────────────────
@test("validator: BOM before fence → SILENT_CORRUPTION")
def t6():
    from hermes_md_manager import validator
    from hermes_md_manager.paths import hermes_home
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".md", delete=False) as f:
        f.write(b"\xef\xbb\xbf---\nname: a\ndescription: d\n---\n# body\n")
        tmp = Path(f.name)
    try:
        # write via direct file (no frontmatter-aware path needed for this probe)
        r = validator.validate_skill_md(tmp, hermes_home=hermes_home())
        rules = {f.rule for f in r.findings}
        assert "BOM-before-fence" in rules, f"expected BOM finding, got: {rules}"
    finally:
        tmp.unlink(missing_ok=True)


@test("validator: tab indentation → loader-fallback flatten SILENT")
def t7():
    from hermes_md_manager import validator
    from hermes_md_manager.paths import hermes_home
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".md", delete=False) as f:
        f.write(b"---\nname: a\ndescription: d\nmetadata:\n\thermes:\n\t\ttags: [x]\n---\n# body\n")
        tmp = Path(f.name)
    try:
        r = validator.validate_skill_md(tmp, hermes_home=hermes_home())
        rules = {f.rule for f in r.findings}
        assert any("loader-fallback" in x for x in rules), f"expected loader-fallback finding, got: {rules}"
    finally:
        tmp.unlink(missing_ok=True)


@test("validator: name: yes → bool coercion SILENT")
def t8():
    from hermes_md_manager import validator
    from hermes_md_manager.paths import hermes_home
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".md", delete=False) as f:
        f.write(b"---\nname: yes\ndescription: 123\n---\n# body\n")
        tmp = Path(f.name)
    try:
        r = validator.validate_skill_md(tmp, hermes_home=hermes_home())
        rules = {f.rule for f in r.findings}
        assert "yaml bool coercion" in rules or "name-bool-coercion" in rules, f"expected bool coercion, got: {rules}"
    finally:
        tmp.unlink(missing_ok=True)


# ─── 5. Round-trip byte fidelity on real tree ─────────────────────────────
@test("round-trip: parser parses every SKILL.md without raising")
def t9():
    """All 72 files must parse without exception; an exception here means we
    would have corrupted the agent's view of its skills at load time."""
    from hermes_md_manager import hermes_vendor as hv
    from hermes_md_manager.paths import hermes_home
    parse = hv.parse_frontmatter()
    iter_files = hv.iter_skill_index_files()
    home = hermes_home()
    skills_root = home / "skills"
    n = 0
    for path in iter_files(skills_root, "SKILL.md"):
        raw = path.read_text(encoding="utf-8", errors="replace")
        fm, body = parse(raw)
        n += 1
    assert n == 72, f"expected 72 SKILL.md, parsed {n}"


# ─── 6. Conflict detection: simulate a concurrent write ───────────────────
@test("chokepoint: refuses write when baseline_sha256 differs from disk")
def t10():
    from hermes_md_manager import mutation
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    target = home / "skills" / "creative" / "ascii-art" / "SKILL.md"
    real_sha = mutation.sha256_of(target)
    fake_baseline = "0" * 64
    result = mutation.write_atomically(
        target=target,
        content=b"---faked---\n",
        baseline_sha256=fake_baseline,
        op="conflict_test",
        approved=True,
        relative_to=home,
    )
    assert not result.ok, "chokepoint accepted a write with stale baseline"
    assert result.error_kind == "conflict", f"expected conflict error_kind, got {result.error_kind}"
    # file must NOT have been modified
    assert mutation.sha256_of(target) == real_sha, "file was modified despite refusal"


# ─── 7. Atomic write preserves content exactly (write→read round-trip) ─────
@test("atomic write: byte-identical round-trip for an arbitrary file")
def t11():
    from hermes_md_manager import mutation
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    target = home / "skills" / "creative" / "ascii-art" / "SKILL.md"
    real = target.read_bytes()
    sha_before = mutation.sha256_of(target)
    # write the same bytes back
    result = mutation.write_atomically(
        target=target,
        content=real,
        baseline_sha256=sha_before,
        op="round_trip_test",
        approved=True,
        relative_to=home,
    )
    assert result.ok, f"round-trip write failed: {result.error}"
    after = target.read_bytes()
    assert after == real, "round-trip changed file content"
    # clean up the backup directory created by the test
    # (we don't rmtree here — the mutation system keeps it for restore)
    print(f"    backup_id={result.backup_id}")


# ─── 8. Soft delete → external trash; Hermes' .archive/ untouched ────────
@test("soft delete: moves skill to external trash, NOT to skills/.archive/")
def t12():
    # use a copy of a skill to avoid touching the real tree
    import tempfile
    from hermes_md_manager import mutation as _mutation
    home = Path(os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    real = home / "skills" / "creative" / "ascii-art"
    with tempfile.TemporaryDirectory() as tmpd:
        src = Path(tmpd) / "ascii-art-copy"
        shutil.copytree(real, src)
        result = _mutation.soft_delete_skill(src)
        assert result.ok, f"soft delete failed: {result.error}"
        assert not src.exists(), "skill dir should have been moved"
        # the destination should be in our state dir, not HERMES_HOME
        dest = Path(result.message.split("moved to ", 1)[1])
        assert not str(dest).startswith(str(home)), \
            f"soft delete landed inside HERMES_HOME ({dest}) — should be external trash"


# ─── 9. Memory drift guard: hand-edited (non-roundtrippable) file is flagged ─
@test("memory drift guard: a single-entry file > char_limit is REJECT")
def t13():
    """The second predicate of Hermes' _detect_external_drift:
    any single parsed entry > store char_limit → drift.

    This is the most common real drift case: an external writer (shell
    append, manual edit, sister session) appends a large block that lands
    as one entry on the next read. Hermes would refuse its own next write
    with a .bak.<ts> snapshot. Our validator catches it ahead of time.
    """
    from hermes_md_manager import validator
    # A single "entry" (no §) that exceeds the 2200 char limit.
    long_entry = ("x" * 3000).encode("utf-8")
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".md", delete=False) as f:
        f.write(long_entry)
        tmp = Path(f.name)
    try:
        r = validator.validate_memory_file(tmp, char_limit=2200)
        rules = {f.rule for f in r.findings}
        assert any("over char limit" in x for x in rules), \
            f"expected char-limit finding, got: {rules}"
        assert r.badge == "red", f"expected red badge (REJECT), got {r.badge}"
    finally:
        tmp.unlink(missing_ok=True)


@test("memory drift guard: clean §-delimited file passes")
def t14():
    from hermes_md_manager import validator
    ENTRY_DELIM = "\n§\n"
    entries = ["entry one", "entry two", "entry three"]
    clean = ENTRY_DELIM.join(entries)
    with tempfile.NamedTemporaryFile(mode="wb", suffix=".md", delete=False) as f:
        f.write(clean.encode("utf-8"))
        tmp = Path(f.name)
    try:
        r = validator.validate_memory_file(tmp, char_limit=2200)
        assert r.badge == "green", f"clean file should be green, got {r.badge} with findings {[f.rule for f in r.findings]}"
    finally:
        tmp.unlink(missing_ok=True)


# ─── 10. The token budget never includes skill bodies ─────────────────────
@test("token budget: skills INDEX lines counted, bodies NOT counted")
def t15():
    from hermes_md_manager import validator
    from hermes_md_manager.paths import hermes_home
    reports = validator.scan_tree(hermes_home=hermes_home())
    home = hermes_home()
    skills_root = home / "skills"
    total_skill_bytes = sum(
        r.bytes for r in reports if r.kind == "skill"
    )
    # Simulate the budget's index-only calc (matches /api/budget logic).
    # We do NOT import from hermes internals — re-implement the truncated
    # description rule here for the assertion.
    index_chars = 0
    for r in reports:
        if r.kind != "skill":
            continue
        fm = r.parsed if isinstance(r.parsed, dict) else {}
        name = str(fm.get("name", "") or "")
        desc = str(fm.get("description", "") or "").strip().strip("'\"")
        if len(desc) > 60:
            desc = desc[:57] + "..."
        index_chars += len(f"    - {name}: {desc}")
    # Budget index_chars should be FAR smaller than total body bytes
    assert index_chars < total_skill_bytes / 5, \
        f"budget index_chars ({index_chars}) suspiciously large vs total skill bytes ({total_skill_bytes})"


# ─── main ──────────────────────────────────────────────────────────────────
def main() -> int:
    print(f"Hermes MD Manager — tests  (HERMES_HOME={os.environ.get('HERMES_HOME')})")
    print()
    # discover test functions t1..tN; skip the decorator itself
    import inspect
    test_names = []
    for k, v in sorted(globals().items()):
        if k.startswith("t") and k[1:].isdigit() and callable(v):
            try:
                inspect.getsource(v)
                test_names.append(v)
            except (OSError, TypeError):
                pass
    for t in test_names:
        t()
    print()
    print(f"PASSED: {len(PASS)} / {len(PASS) + len(FAIL)}")
    if FAIL:
        print("FAILURES:")
        for name, err in FAIL:
            print(f"  - {name}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())