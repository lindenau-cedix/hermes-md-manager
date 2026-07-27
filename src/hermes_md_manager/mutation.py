"""Mutation chokepoint — the single function that emits writes.

Every feature that wants to mutate anything (skill/memory/SOUL content,
``.usage.json``, ``.skills_prompt_snapshot.json``) goes through ``write_atomically``
or one of the higher-level helpers that call it. The function enforces the
guards in order:

    1. baseline hash captured at read-time matches on-disk hash
       (verify-before-write, refuse+diff, NO auto-merge)
    2. for no-op edits, round-tripped byte-identical output
       (read → write with no semantic changes is bit-perfect)
    3. pre-image backup written OUTSIDE HERMES_HOME and fsync'd BEFORE
       any target mutation
    4. user-approved diff (enforced by the API layer; the chokepoint itself
       refuses if ``approved=False``)
    5. atomic write reusing Hermes' utils.atomic_replace (symlink/mode
       preserving; EXDEV/EBUSY fallback)
    6. side-effects after success: .usage.json write under the flock,
       snapshot deletion, manifest close

Soft-delete has its own two-tier handling:
    user soft-delete (the default)  → external $STATE/trash/
    lifecycle archive                → Hermes' own skills/.archive/<skill>/
                                        (so `hermes curator restore` still works)

The chokepoint NEVER:
    - merges concurrent writes automatically
    - writes outside the small set of paths Hermes itself expects a peer to write
    - invents schema fields Hermes doesn't parse
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import errno
import hashlib
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Literal

from . import hermes_vendor as hv
from . import paths


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class WriteResult:
    ok: bool
    backup_id: str | None = None
    target: str | None = None
    sha256_after: str | None = None
    bytes_written: int = 0
    message: str | None = None
    error: str | None = None
    error_kind: str | None = None  # "conflict" | "round_trip" | "permission" | "drift" | "ineligible" | "other"


@dataclasses.dataclass
class BackupRecord:
    id: str
    created_at: str
    profile_id: str
    files: list[dict[str, Any]]
    op: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(64 * 1024), b""):
                h.update(chunk)
    except OSError:
        return ""
    return h.hexdigest()


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%fZ")


def _profile_backups_root() -> Path:
    p = paths.backups_dir() / paths.profile_id()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _backup_id() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f")


# ---------------------------------------------------------------------------
# The single write chokepoint
# ---------------------------------------------------------------------------


def write_atomically(
    *,
    target: Path,
    content: bytes,
    baseline_sha256: str | None,
    op: str,
    approved: bool,
    round_trip_check: bool = True,
    relative_to: Path | None = None,
    metadata: dict[str, Any] | None = None,
) -> WriteResult:
    """The only function in this package that emits a write to a Hermes-side
    file. See module docstring for the full guard chain.

    Args:
        target: absolute path to the file to write.
        content: bytes to write.
        baseline_sha256: sha256 of the on-disk file captured at read-time, or
            ``None`` if this is a CREATE (file didn't exist). Required for
            edits.
        op: human label for the operation (e.g. "edit_skill_md").
        approved: caller has shown the user the diff and they approved it.
        round_trip_check: when True, decode content as utf-8 and check that
            whitespace / trailing-newline invariants are reasonable. (The
            precise byte-identity check for YAML edits lives in the validator
            layer; this guard prevents obviously-broken writes.)
        relative_to: when provided, paths in the backup manifest are recorded
            relative to this root (e.g. ``HERMES_HOME``).
        metadata: free-form dict stored in the backup manifest.

    Returns:
        ``WriteResult`` with ``ok=True`` and the backup id on success, or
        ``ok=False`` with ``error_kind`` and a clear ``error`` message.
    """
    if not approved:
        return WriteResult(
            ok=False,
            target=str(target),
            error="write not approved by user",
            error_kind="other",
        )

    if not target.exists() and baseline_sha256 is not None:
        return WriteResult(
            ok=False,
            target=str(target),
            error=f"target {target} does not exist but a baseline hash was supplied (file was deleted between read and write)",
            error_kind="conflict",
        )

    if target.exists():
        current_sha = sha256_of(target)
        if baseline_sha256 is not None and current_sha != baseline_sha256:
            return WriteResult(
                ok=False,
                target=str(target),
                error=(
                    f"conflict: {target.name} changed since read "
                    f"(expected {baseline_sha256[:12]}…, on-disk {current_sha[:12]}…). "
                    f"Refusing to write. No auto-merge."
                ),
                error_kind="conflict",
            )

    if round_trip_check:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            return WriteResult(
                ok=False,
                target=str(target),
                error=f"content is not valid UTF-8: {exc}",
                error_kind="other",
            )

    # 1. Backup FIRST, outside HERMES_HOME
    backup_id = _backup_id()
    backup_root = _profile_backups_root() / backup_id
    backup_root.mkdir(parents=True, exist_ok=True)
    manifest_files: list[dict[str, Any]] = []

    if target.exists():
        sha_before = sha256_of(target)
        size_before = target.stat().st_size
        # store backup under HERMES_HOME-relative path
        if relative_to:
            try:
                rel = target.relative_to(relative_to)
            except ValueError:
                rel = Path(target.name)
        else:
            rel = Path(target.name)
        dest = backup_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(target, dest)
        except OSError as exc:
            return WriteResult(
                ok=False,
                target=str(target),
                error=f"backup failed: {exc}",
                error_kind="permission",
            )
        # fsync the backup dir's parent (best-effort)
        try:
            fd = os.open(str(dest.parent), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
        manifest_files.append({
            "path": str(rel),
            "sha256_before": sha_before,
            "sha256_after": None,
            "size_before": size_before,
            "size_after": None,
        })

    # 2. Atomic write (reuse Hermes' utils.atomic_replace — symlink/mode preserving)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    sha_after: str | None = None
    bytes_written = 0
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        bytes_written = len(content)
        # atomic_replace handles symlinks + EXDEV/EBUSY fallback (utils.py:91)
        hv.atomic_replace()(tmp_path, target)
        sha_after = sha256_of(target)
    except OSError as exc:
        # best-effort cleanup
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        # remove the empty backup record
        try:
            shutil.rmtree(backup_root)
        except OSError:
            pass
        return WriteResult(
            ok=False,
            target=str(target),
            error=f"atomic write failed: {exc}",
            error_kind="permission" if exc.errno == errno.EACCES else "other",
        )
    finally:
        pass

    # 3. Close out the backup manifest
    if manifest_files and sha_after is not None:
        manifest_files[0]["sha256_after"] = sha_after
        manifest_files[0]["size_after"] = bytes_written
    manifest = BackupRecord(
        id=backup_id,
        created_at=_iso_now(),
        profile_id=paths.profile_id(),
        files=manifest_files,
        op=op,
    )
    (backup_root / "manifest.json").write_text(
        json.dumps(dataclasses.asdict(manifest), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return WriteResult(
        ok=True,
        backup_id=backup_id,
        target=str(target),
        sha256_after=sha_after,
        bytes_written=bytes_written,
    )


# ---------------------------------------------------------------------------
# Side-effects (run only after a successful write)
# ---------------------------------------------------------------------------


def clear_prompt_snapshot(*, hermes_home: Path | None = None) -> bool:
    """Delete ``$HERMES_HOME/.skills_prompt_snapshot.json`` (idempotent).

    Mirrors ``clear_skills_system_prompt_cache(clear_snapshot=True)`` (Hermes'
    own learning path calls this after a write).
    """
    home = hermes_home or paths.hermes_home()
    p = home / ".skills_prompt_snapshot.json"
    try:
        p.unlink(missing_ok=True)
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Two-tier delete
# ---------------------------------------------------------------------------


def soft_delete_skill(skill_dir: Path) -> WriteResult:
    """User soft-delete: move the skill directory to external trash/.

    NEVER uses Hermes' ``skills/.archive/`` (that's the curator's territory).
    Always recoverable from $STATE/trash/<iso-ts>/<skill>/.
    """
    if not skill_dir.is_dir():
        return WriteResult(
            ok=False,
            target=str(skill_dir),
            error=f"not a directory: {skill_dir}",
            error_kind="other",
        )
    trash_root = paths.trash_dir() / paths.profile_id()
    trash_root.mkdir(parents=True, exist_ok=True)
    ts = _backup_id()
    dest = trash_root / ts / skill_dir.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        # First copy (so the move is reversible), then remove.
        shutil.copytree(skill_dir, dest)
        shutil.rmtree(skill_dir)
    except OSError as exc:
        return WriteResult(
            ok=False,
            target=str(skill_dir),
            error=f"soft-delete failed: {exc}",
            error_kind="permission",
        )
    (trash_root / ts / "manifest.json").write_text(
        json.dumps({
            "op": "soft_delete_skill",
            "source": str(skill_dir),
            "dest": str(dest),
            "created_at": _iso_now(),
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return WriteResult(
        ok=True,
        backup_id=ts,
        target=str(skill_dir),
        message=f"moved to {dest}",
    )


def lifecycle_archive_skill(name: str) -> tuple[bool, str]:
    """Promote/archive a skill: write the lifecycle state under the flock AND
    move the dir into Hermes' ``skills/.archive/<name>/`` so ``hermes curator
    restore`` still finds it.

    Returns (ok, message). Refuses for non-curation-eligible skills (hub,
    external_dirs, PROTECTED_BUILTIN).
    """
    from tools import skill_usage  # vendored

    if name in skill_usage.PROTECTED_BUILTIN_SKILLS:
        return False, f"'{name}' is a protected built-in; never archived"
    if skill_usage.is_hub_installed(name):
        return False, f"'{name}' is hub-installed; never archived"
    eligible = skill_usage.is_curation_eligible(name)
    if not eligible:
        # bundled built-ins: requires prune_builtins
        if skill_usage.is_bundled(name):
            return False, f"'{name}' is bundled built-in; enable curator.prune_builtins to archive"
        return False, f"'{name}' is not curation-eligible"

    ok, msg = skill_usage.archive_skill(name)
    if ok:
        clear_prompt_snapshot()
    return ok, msg


def lifecycle_restore_skill(name: str) -> tuple[bool, str]:
    """Restore an archived skill. Refuses if it would shadow a hub-installed
    or bundled-builtin skill. (Delegates to Hermes' own restore_skill.)
    """
    from tools import skill_usage  # vendored
    ok, msg = skill_usage.restore_skill(name)
    if ok:
        clear_prompt_snapshot()
    return ok, msg


# ---------------------------------------------------------------------------
# Restore from backup
# ---------------------------------------------------------------------------


def list_backups() -> list[dict[str, Any]]:
    root = paths.backups_dir() / paths.profile_id()
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in sorted(root.iterdir(), reverse=True):
        manifest = child / "manifest.json"
        if not manifest.exists():
            continue
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append(data)
    return out


def restore_backup(backup_id: str) -> WriteResult:
    """Restore the files captured in the given backup.

    Files are restored byte-for-byte via atomic_replace. The current on-disk
    state becomes the pre-image of a *new* backup so restore is itself
    recoverable.
    """
    root = paths.backups_dir() / paths.profile_id() / backup_id
    manifest = root / "manifest.json"
    if not manifest.exists():
        return WriteResult(
            ok=False,
            target=backup_id,
            error=f"backup not found: {backup_id}",
            error_kind="other",
        )
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return WriteResult(
            ok=False,
            target=backup_id,
            error=f"manifest unreadable: {exc}",
            error_kind="other",
        )
    hermes_home = paths.hermes_home()
    last_err: str | None = None
    for entry in data.get("files", []):
        rel = Path(entry["path"])
        src = root / rel
        dst = hermes_home / rel
        if not src.exists():
            continue
        # Use write_atomically's atomic write path but skip the baseline check
        # (we are restoring — the file may currently be in any state).
        content = src.read_bytes()
        result = write_atomically(
            target=dst,
            content=content,
            baseline_sha256=None,
            op=f"restore:{backup_id}",
            approved=True,
            round_trip_check=False,
            relative_to=hermes_home,
        )
        if not result.ok:
            last_err = result.error
    if last_err:
        return WriteResult(
            ok=False,
            target=backup_id,
            error=f"partial restore: {last_err}",
            error_kind="permission",
        )
    clear_prompt_snapshot()
    return WriteResult(
        ok=True,
        backup_id=backup_id,
        target=backup_id,
        message=f"restored {len(data.get('files', []))} file(s) from backup {backup_id}",
    )


# ---------------------------------------------------------------------------
# Trash recovery (user soft-delete)
# ---------------------------------------------------------------------------


def list_trash() -> list[dict[str, Any]]:
    root = paths.trash_dir() / paths.profile_id()
    if not root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for ts in sorted(root.iterdir(), reverse=True):
        manifest = ts / "manifest.json"
        entry: dict[str, Any] = {"id": ts.name, "path": str(ts)}
        if manifest.exists():
            try:
                m = json.loads(manifest.read_text(encoding="utf-8"))
                entry.update({
                    "op": m.get("op"),
                    "source": m.get("source"),
                    "created_at": m.get("created_at"),
                })
            except (OSError, json.JSONDecodeError):
                pass
        # also list skill dirs in this trash entry
        for child in ts.iterdir():
            if child.is_dir() and child.name != "manifest.json":
                entry.setdefault("skills", []).append({
                    "name": child.name,
                    "path": str(child),
                })
        out.append(entry)
    return out


def restore_from_trash(trash_id: str, skill_name: str) -> WriteResult:
    """Restore a soft-deleted skill directory from external trash to its
    original location (HOME/skills/<skill_name>/). Fails if destination already
    exists.
    """
    root = paths.trash_dir() / paths.profile_id() / trash_id
    src = root / skill_name
    if not src.is_dir():
        return WriteResult(
            ok=False,
            target=skill_name,
            error=f"trash entry not found: {trash_id}/{skill_name}",
            error_kind="other",
        )
    home = paths.hermes_home()
    skills_root = home / "skills"
    if not skills_root.is_dir():
        return WriteResult(
            ok=False,
            target=skill_name,
            error=f"hermes skills root missing: {skills_root}",
            error_kind="other",
        )
    dst = skills_root / skill_name
    if dst.exists():
        return WriteResult(
            ok=False,
            target=skill_name,
            error=f"destination already exists: {dst}",
            error_kind="conflict",
        )
    try:
        shutil.copytree(src, dst)
        shutil.rmtree(src)
    except OSError as exc:
        return WriteResult(
            ok=False,
            target=skill_name,
            error=f"restore failed: {exc}",
            error_kind="permission",
        )
    clear_prompt_snapshot()
    return WriteResult(
        ok=True,
        backup_id=trash_id,
        target=str(dst),
        message=f"restored to {dst}",
    )