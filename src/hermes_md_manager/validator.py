"""Two-faced validator + tree scanner.

Two passes over every file:

  1. **Loud pass** — vendored ``_validate_frontmatter``
     (``tools/skill_manager_tool.py:524``) via ``yaml.safe_load``.
     Rejects things Hermes itself refuses to write.

  2. **Silent pass** — vendored ``parse_frontmatter`` loader
     (``agent/skill_utils.py:123``) with the silent-fallback path at
     ``:149``:157``. Catches the §4 silent-corruption modes the loader
     silently absorbs. Each finding cites the rule (file:line) and carries a
     severity (REJECT / SILENT_CORRUPTION / ADVISORY) plus a concrete
     suggested fix.

Validator outputs per file:
    file        — path
    type        — "skill" | "category_description" | "persona" | "memory"
    parsed      — frontmatter dict (or None on parse failure)
    body        — raw body string (after frontmatter fence)
    findings    — list of Finding dataclasses
    badge       — "green" | "amber" | "red"  (loud reject -> red;
                   silent corruption -> amber; else green)
    bytes       — file size
    sha256      — content hash (for conflict baseline)
"""
from __future__ import annotations

import dataclasses
import enum
import hashlib
import re
from pathlib import Path
from typing import Any, Iterator

from . import hermes_vendor as hv


# ---------------------------------------------------------------------------
# Severity + Finding
# ---------------------------------------------------------------------------


class Severity(str, enum.Enum):
    REJECT = "reject"             # Hermes' own _validate_frontmatter refuses this
    SILENT = "silent_corruption"  # loader accepts but the value is silently wrong
    ADVISORY = "advisory"         # works today; worth surfacing


@dataclasses.dataclass
class Finding:
    severity: Severity
    rule: str       # e.g. "loader-fallback flatten (skill_utils.py:149)"
    message: str
    fix: str | None = None


# ---------------------------------------------------------------------------
# Per-file classification
# ---------------------------------------------------------------------------


FileKind = str  # "skill" | "category_description" | "persona" | "memory" | "other"


def classify(path: Path, *, hermes_home: Path) -> FileKind:
    p_str = str(path)
    home = str(hermes_home)
    if path.name == "SOUL.md" and path.parent == hermes_home:
        return "persona"
    if path.name in ("MEMORY.md", "USER.md") and path.parent.name == "memories":
        return "memory"
    if path.name == "SKILL.md" and path.parent.parent == hermes_home / "skills":
        # could be flat: ~/hermes/skills/<skill>/SKILL.md
        return "skill"
    if path.name == "SKILL.md":
        # nested: ~/hermes/skills/<cat>/.../<skill>/SKILL.md
        try:
            rel = path.relative_to(hermes_home / "skills")
        except ValueError:
            return "other"
        parts = rel.parts  # ("cat", ..., "skill", "SKILL.md")
        if len(parts) >= 3:
            return "skill"
        return "other"
    if path.name == "DESCRIPTION.md" and "skills" in p_str[len(home):].split("/"):
        return "category_description"
    return "other"


# ---------------------------------------------------------------------------
# Silent-mode probes
# ---------------------------------------------------------------------------


_BOM = "﻿"


def _detect_silent_modes(content: str, parsed: dict[str, Any] | None) -> list[Finding]:
    findings: list[Finding] = []

    # 1. UTF-8 BOM before the leading ---
    if content.startswith(_BOM):
        findings.append(Finding(
            Severity.SILENT,
            "BOM-before-fence",
            "file starts with a UTF-8 BOM; the loader requires content to start with '---' so the BOM makes the entire frontmatter silently unparseable.",
            fix="save the file without a leading BOM (most editors add one for Excel-derived files).",
        ))

    # 2. tab indentation
    fm_start = content.find("---")
    fm_end = content.find("\n---", 3)
    if fm_start == 0 and fm_end != -1:
        fm_block = content[3:fm_end]
        for line in fm_block.splitlines():
            if "\t" in line:
                findings.append(Finding(
                    Severity.SILENT,
                    "loader-fallback flatten (skill_utils.py:149)",
                    "YAML frontmatter contains a tab character; the loader falls back to naive key:value splitting, which flattens nested structures to empty/string-valued keys.",
                    fix="replace tab characters with spaces (YAML requires it).",
                ))
                break

    # 3. YAML type coercion: unquoted yes/no/on/off/true/false, bare numerics
    if isinstance(parsed, dict):
        for key in ("name", "description"):
            v = parsed.get(key)
            if isinstance(v, bool):
                findings.append(Finding(
                    Severity.SILENT,
                    "yaml bool coercion",
                    f"frontmatter `{key}` parsed as Python bool ({v!r}) because it was unquoted. The loader will call str() and render it as 'True'/'False' in the index.",
                    fix=f"quote the value: `{key}: \"{str(v).lower()}\"` or `{key}: \"some-name\"`.",
                ))
            elif isinstance(v, int):
                findings.append(Finding(
                    Severity.SILENT,
                    "yaml int coercion",
                    f"frontmatter `{key}` parsed as int ({v}); the index will render str(...) — fine for numeric version strings, wrong for description.",
                    fix="quote the value.",
                ))
            elif isinstance(v, float):
                findings.append(Finding(
                    Severity.SILENT,
                    "yaml float coercion",
                    f"frontmatter `{key}` parsed as float ({v}); the index will render str(...) which is rarely intended.",
                    fix="quote the value.",
                ))

        # 4. platforms value is a string (unclosed list) rather than a list
        plats = parsed.get("platforms")
        if isinstance(plats, str) and plats.startswith("["):
            findings.append(Finding(
                Severity.SILENT,
                "platforms unclosed-list string",
                f"`platforms` parsed as the string {plats!r} because the YAML list was unclosed. The platform gate will misfire and the skill may be hidden.",
                fix="close the list: `platforms: [macos, linux]`.",
            ))

        # 5. empty string metadata.hermes (stringified from flatten fallback)
        meta = parsed.get("metadata")
        if meta == "":
            findings.append(Finding(
                Severity.SILENT,
                "loader-fallback flatten",
                "`metadata` parsed as the empty string because the YAML below it contained tabs/indentation errors. All hermes-specific nested fields are LOST.",
                fix="fix indentation (no tabs); restore nested metadata.hermes.* keys.",
            ))

    return findings


# ---------------------------------------------------------------------------
# Loud pass (delegates to vendored _validate_frontmatter)
# ---------------------------------------------------------------------------


def _loud_findings(content: str) -> list[Finding]:
    fn = hv._validate_frontmatter()
    err = fn(content)
    if err is None:
        return []
    return [Finding(Severity.REJECT, "vendor: _validate_frontmatter", err)]


# ---------------------------------------------------------------------------
# Single-file validator
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class FileReport:
    path: str
    kind: FileKind
    bytes: int
    sha256: str
    parsed: dict[str, Any] | None
    body: str | None
    findings: list[Finding]
    badge: str  # "green" | "amber" | "red"

    @property
    def is_valid(self) -> bool:
        return self.badge != "red"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "parsed": self.parsed,
            "body_present": self.body is not None and bool(self.body.strip()),
            "findings": [
                {
                    "severity": f.severity.value,
                    "rule": f.rule,
                    "message": f.message,
                    "fix": f.fix,
                }
                for f in self.findings
            ],
            "badge": self.badge,
        }


def validate_skill_md(path: Path, *, hermes_home: Path) -> FileReport:
    """Validate a single SKILL.md or DESCRIPTION.md file."""
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    kind = classify(path, hermes_home=hermes_home)

    findings: list[Finding] = []
    if kind == "skill":
        findings.extend(_loud_check_skill(raw.decode("utf-8", errors="replace")))

    # Try loader-side parse
    parsed: dict[str, Any] | None = None
    body: str | None = None
    content = raw.decode("utf-8", errors="replace")
    # Always attempt the loader-side parse — silent-mode probes are pure
    # content checks (BOM/tab/coercion/platforms-str) and don't depend on
    # file kind, so we run them for any file that parses to a dict.
    try:
        loader = hv.parse_frontmatter()
        parsed_any, body_any = loader(content)
        if isinstance(parsed_any, dict) and parsed_any:
            parsed = parsed_any
            body = body_any
    except Exception:
        parsed = None
    # Silent-mode probes run for any markdown file (BOM/tab/coercion/platforms
    # are content-level; kind-specific findings are added below).
    findings.extend(_detect_silent_modes(content, parsed))

    if kind == "category_description":
        # DESCRIPTION.md must have frontmatter AND a description field
        if not content.startswith("---"):
            findings.append(Finding(
                Severity.SILENT,
                "description-missing-frontmatter",
                "category DESCRIPTION.md has no YAML frontmatter at all; Hermes' indexer only reads a `description:` key from parsed frontmatter, so the category header is silently dropped.",
                fix="wrap the description in YAML frontmatter: `---\\ndescription: <one-sentence>\\n---\\n<body>`.",
            ))
        elif isinstance(parsed, dict) and not parsed.get("description"):
            findings.append(Finding(
                Severity.SILENT,
                "missing-description",
                "category DESCRIPTION.md has frontmatter but no `description:` field; the category header is silently dropped from the skills index.",
                fix="add `description: <one-sentence category description>` to the frontmatter.",
            ))

    if kind == "skill":
        # Dual-identity check: frontmatter `name:` vs directory name
        # Hermes keys the index by frontmatter name (skill_usage.py:398) but
        # skill_manage addresses by directory name (skill_manager_tool.py:600).
        # A mismatch shows one label in the index but is addressed by another
        # for edits — a real footgun in 5/72 skills in the live tree.
        if isinstance(parsed, dict) and parsed.get("name"):
            fm_name = str(parsed["name"])
            dir_name = path.parent.name
            if fm_name != dir_name:
                findings.append(Finding(
                    Severity.SILENT,
                    "name-vs-dir dual identity",
                    f"frontmatter `name: {fm_name}` differs from directory name `{dir_name}`. Hermes' index keys by frontmatter name but `skill_manage` addresses by directory name — the skill is found under one label and edited under another.",
                    fix="set `name:` to match the directory name (or rename the directory).",
                ))

        # Coerced-true name (the Phase-1 §4 silent mode "name: yes → True")
        # — already covered by the silent-mode probes above, but make the
        # rule name match what the operator will see in logs.
        if isinstance(parsed, dict) and isinstance(parsed.get("name"), bool):
            findings.append(Finding(
                Severity.SILENT,
                "name-bool-coercion",
                f"frontmatter `name` parsed as Python bool ({parsed['name']!r}) because it was unquoted.",
                fix="quote the value: `name: \"some-name\"`.",
            ))

        # Missing optional but conventional fields (advisory — surfaced so
        # the operator sees them, not auto-fixed).
        if isinstance(parsed, dict):
            if "version" not in parsed:
                findings.append(Finding(
                    Severity.ADVISORY,
                    "missing-version",
                    "skill has no `version:` field; convention is semver.",
                    fix="add `version: 1.0.0`.",
                ))

    badge = _badge(findings)
    return FileReport(
        path=str(path),
        kind=kind,
        bytes=len(raw),
        sha256=sha,
        parsed=parsed,
        body=body,
        findings=findings,
        badge=badge,
    )


def _loud_check_skill(content: str) -> list[Finding]:
    """Loud pass: vendor _validate_frontmatter + name/category validity."""
    fn = hv._validate_frontmatter()
    err = fn(content)
    if err is not None:
        return [Finding(Severity.REJECT, "vendor: _validate_frontmatter", err)]
    # name validity
    parsed, _ = hv.parse_frontmatter()(content)
    name = parsed.get("name") if isinstance(parsed, dict) else None
    if isinstance(name, str):
        name_err = hv._validate_name()(name)
        if name_err:
            return [Finding(Severity.REJECT, "vendor: _validate_name", name_err)]
    return []


def _badge(findings: list[Finding]) -> str:
    if any(f.severity == Severity.REJECT for f in findings):
        return "red"
    if any(f.severity == Severity.SILENT for f in findings):
        return "amber"
    return "green"


# ---------------------------------------------------------------------------
# Memory files
# ---------------------------------------------------------------------------


def validate_memory_file(path: Path, *, char_limit: int) -> FileReport:
    """Validate a MEMORY.md / USER.md file.

    Checks the same drift predicate Hermes uses (``_detect_external_drift``):
        raw.strip() == "\n§\n".join(parsed)  AND  every entry ≤ char_limit
    """
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    content = raw.decode("utf-8", errors="replace")
    delim = hv.ENTRY_DELIMITER()  # "\n§\n"
    parsed = [e.strip() for e in content.split(delim) if e.strip()]
    roundtrip = delim.join(parsed)
    findings: list[Finding] = []
    if content.strip() and content.strip() != roundtrip:
        findings.append(Finding(
            Severity.SILENT,
            "memory-drift",
            "file content wouldn't round-trip through the §-serializer; Hermes' own _detect_external_drift will refuse its next memory write.",
            fix="rewrite the file as a clean §-delimited list of entries.",
        ))
    for i, entry in enumerate(parsed):
        if len(entry) > char_limit:
            findings.append(Finding(
                Severity.REJECT,
                "memory-entry over char limit",
                f"entry #{i+1} is {len(entry)} chars (limit {char_limit}). Hermes budgets the WHOLE file against this limit and will refuse on the next write.",
                fix=f"split this entry; consolidate it elsewhere; or raise `memory.{(path.name.lower().removesuffix('.md'))}_char_limit` in config.yaml.",
            ))
    return FileReport(
        path=str(path),
        kind="memory",
        bytes=len(raw),
        sha256=sha,
        parsed={"entries": len(parsed)},
        body=content,
        findings=findings,
        badge=_badge(findings),
    )


# ---------------------------------------------------------------------------
# Tree scanner
# ---------------------------------------------------------------------------


def iter_skill_files(hermes_home: Path) -> Iterator[Path]:
    """Walk HERMES_HOME/skills/ yielding SKILL.md and DESCRIPTION.md files,
    honoring Hermes' own support-dir + excluded-dir pruning.
    """
    skills_root = hermes_home / "skills"
    if not skills_root.is_dir():
        return
    iter_files = hv.iter_skill_index_files()
    for fname in ("SKILL.md", "DESCRIPTION.md"):
        yield from iter_files(skills_root, fname)


def scan_tree(*, hermes_home: Path | None = None,
              memory_char_limit: int = 2200,
              user_char_limit: int = 1375) -> list[FileReport]:
    home = hermes_home or _default_hermes_home()
    out: list[FileReport] = []

    # SOUL.md
    soul = home / "SOUL.md"
    if soul.exists():
        raw = soul.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        out.append(FileReport(
            path=str(soul),
            kind="persona",
            bytes=len(raw),
            sha256=sha,
            parsed=None,
            body=raw.decode("utf-8", errors="replace").strip(),
            findings=[],
            badge="green",
        ))

    # MEMORY.md, USER.md
    memories = home / "memories"
    if memories.is_dir():
        for name, limit in (("MEMORY.md", memory_char_limit), ("USER.md", user_char_limit)):
            p = memories / name
            if p.exists():
                out.append(validate_memory_file(p, char_limit=limit))

    # Skills tree
    for path in iter_skill_files(home):
        out.append(validate_skill_md(path, hermes_home=home))

    return out


def _default_hermes_home() -> Path:
    from . import paths
    return paths.hermes_home()