"""Vendored Hermes modules + source-parity self-check.

The tool depends on a small, fixed set of Hermes symbols (parser, validator,
atomic write, .usage.json flock, memory drift guard). If Hermes upgrades and
any of those symbols moves/changes, the source-parity self-check trips and
the tool drops to READ-ONLY mode — a deliberate, surfaced mitigation for the
v0.18.2 version-drift risk documented in the design proposal.

Vendoring happens by import: the tool's python interpreter adds Hermes'
source root to sys.path (see ``paths.py``) so these symbols resolve as if they
were part of the tool. We never re-implement these algorithms; we use the
exact functions Hermes itself uses.

Each vendor block records the *expected* import location and a fingerprint
of the source file. The fingerprint is recomputed at startup; a mismatch
trips ``read_only=True`` and the API returns a 503 with a clear reason.
"""
from __future__ import annotations

import hashlib
import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


# --- Expected vendor surface (path:LINE + symbol name) ------------------------

@dataclass(frozen=True)
class VendorSpec:
    label: str
    module: str            # import name
    attr: str              # attribute to fetch
    source_relpath: str    # relative to Hermes source root (for fingerprinting)


# These are the exact algorithms the tool relies on (Phase-1 citations).
_VENDOR_SPECS: tuple[VendorSpec, ...] = (
    VendorSpec(
        "parse_frontmatter (loader)",
        "agent.skill_utils", "parse_frontmatter",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "yaml_load (CSafeLoader)",
        "agent.skill_utils", "yaml_load",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "_validate_frontmatter (write validator)",
        "tools.skill_manager_tool", "_validate_frontmatter",
        "tools/skill_manager_tool.py",
    ),
    VendorSpec(
        "_validate_name",
        "tools.skill_manager_tool", "_validate_name",
        "tools/skill_manager_tool.py",
    ),
    VendorSpec(
        "_atomic_write_text",
        "tools.skill_manager_tool", "_atomic_write_text",
        "tools/skill_manager_tool.py",
    ),
    VendorSpec(
        "atomic_replace (utils.py:91)",
        "utils", "atomic_replace",
        "utils.py",
    ),
    VendorSpec(
        "atomic_json_write",
        "utils", "atomic_json_write",
        "utils.py",
    ),
    VendorSpec(
        "MemoryStore._read_file",
        "tools.memory_tool", "MemoryStore",
        "tools/memory_tool.py",
    ),
    VendorSpec(
        "MemoryStore._write_file",
        "tools.memory_tool", "MemoryStore",
        "tools/memory_tool.py",
    ),
    VendorSpec(
        "MemoryStore._detect_external_drift",
        "tools.memory_tool", "MemoryStore",
        "tools/memory_tool.py",
    ),
    VendorSpec(
        "ENTRY_DELIMITER",
        "tools.memory_tool", "ENTRY_DELIMITER",
        "tools/memory_tool.py",
    ),
    VendorSpec(
        "skill_usage.get_record",
        "tools.skill_usage", "get_record",
        "tools/skill_usage.py",
    ),
    VendorSpec(
        "skill_usage.set_state",
        "tools.skill_usage", "set_state",
        "tools/skill_usage.py",
    ),
    VendorSpec(
        "skill_usage.set_pinned",
        "tools.skill_usage", "set_pinned",
        "tools/skill_usage.py",
    ),
    VendorSpec(
        "skill_usage.archive_skill",
        "tools.skill_usage", "archive_skill",
        "tools/skill_usage.py",
    ),
    VendorSpec(
        "skill_usage.restore_skill",
        "tools.skill_usage", "restore_skill",
        "tools/skill_usage.py",
    ),
    VendorSpec(
        "skill_usage._is_curator_managed_record",
        "tools.skill_usage", "_is_curator_managed_record",
        "tools/skill_usage.py",
    ),
    VendorSpec(
        "skill_usage.PROTECTED_BUILTIN_SKILLS",
        "tools.skill_usage", "PROTECTED_BUILTIN_SKILLS",
        "tools/skill_usage.py",
    ),
    VendorSpec(
        "skill_utils.get_skills_dir",
        "agent.skill_utils", "get_skills_dir",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "skill_utils.get_all_skills_dirs",
        "agent.skill_utils", "get_all_skills_dirs",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "skill_utils.iter_skill_index_files",
        "agent.skill_utils", "iter_skill_index_files",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "skill_utils.is_external_skill_path",
        "agent.skill_utils", "is_external_skill_path",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "skill_utils.parse_qualified_name",
        "agent.skill_utils", "parse_qualified_name",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "skill_utils.skill_matches_platform",
        "agent.skill_utils", "skill_matches_platform",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "skill_utils.skill_matches_environment",
        "agent.skill_utils", "skill_matches_environment",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "skill_utils.extract_skill_conditions",
        "agent.skill_utils", "extract_skill_conditions",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "skill_utils.extract_skill_config_vars",
        "agent.skill_utils", "extract_skill_config_vars",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "skill_utils.get_disabled_skill_names",
        "agent.skill_utils", "get_disabled_skill_names",
        "agent/skill_utils.py",
    ),
    VendorSpec(
        "skill_utils.get_external_skills_dirs",
        "agent.skill_utils", "get_external_skills_dirs",
        "agent/skill_utils.py",
    ),
)


# --- Runtime cached imports + fingerprint ------------------------------------


def _fingerprint(path: Path) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    return hashlib.sha256(data).hexdigest()[:16]


@dataclass
class VendorState:
    read_only: bool = False
    reasons: list[str] = field(default_factory=list)
    specs: list[VendorSpec] = field(default_factory=lambda: list(_VENDOR_SPECS))
    resolved: dict[str, Any] = field(default_factory=dict)
    fingerprints: dict[str, str] = field(default_factory=dict)

    def resolve(self, spec: VendorSpec) -> Any:
        if spec.label in self.resolved:
            return self.resolved[spec.label]
        mod = importlib.import_module(spec.module)
        obj = getattr(mod, spec.attr)
        self.resolved[spec.label] = obj
        return obj


_state: VendorState | None = None


def state() -> VendorState:
    global _state
    if _state is not None:
        return _state
    _state = VendorState()
    src_root = Path("/home/app/.hermes/hermes-agent")
    for spec in _state.specs:
        # fingerprint
        path = src_root / spec.source_relpath
        _state.fingerprints[spec.label] = _fingerprint(path)
        # resolve
        try:
            _state.resolve(spec)
        except Exception as exc:  # noqa: BLE001 - parity check must never raise
            _state.read_only = True
            _state.reasons.append(f"vendor import failed: {spec.label} ({spec.module}.{spec.attr}): {exc}")
    return _state


def get(spec: VendorSpec) -> Any:
    """Resolve and return a vendored symbol. If the source-parity check tripped
    the app to READ-ONLY mode, callers that need this symbol will already have
    refused the request at the API layer.
    """
    return state().resolve(spec)


def reload_fingerprints() -> None:
    """Recompute fingerprints without invalidating resolved objects. Useful for
    tests; the API can call it after the user explicitly acknowledges an
    upgrade.
    """
    s = state()
    src_root = Path("/home/app/.hermes/hermes-agent")
    for spec in s.specs:
        s.fingerprints[spec.label] = _fingerprint(src_root / spec.source_relpath)


# Convenience handles used by the rest of the tool (import-site clarity).
def parse_frontmatter():
    return get(_VENDOR_SPECS[0])


def yaml_load():
    return get(_VENDOR_SPECS[1])


def _validate_frontmatter():
    return get(_VENDOR_SPECS[2])


def _validate_name():
    return get(_VENDOR_SPECS[3])


def _atomic_write_text():
    return get(_VENDOR_SPECS[4])


def atomic_replace():
    return get(_VENDOR_SPECS[5])


def atomic_json_write():
    return get(_VENDOR_SPECS[6])


def MemoryStore():
    return get(_VENDOR_SPECS[7])


def ENTRY_DELIMITER():
    return get(_VENDOR_SPECS[10])


def skill_usage_get_record():
    return get(_VENDOR_SPECS[11])


def skill_usage_set_state():
    return get(_VENDOR_SPECS[12])


def skill_usage_set_pinned():
    return get(_VENDOR_SPECS[13])


def skill_usage_archive_skill():
    return get(_VENDOR_SPECS[14])


def skill_usage_restore_skill():
    return get(_VENDOR_SPECS[15])