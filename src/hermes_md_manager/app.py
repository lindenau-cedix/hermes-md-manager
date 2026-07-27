"""FastAPI app + REST routes for the Hermes MD Manager.

Routes:
    GET  /api/health
    GET  /api/tree                          — browse ledger
    GET  /api/file?path=                    — single file detail
    GET  /api/file/raw?path=                — raw text (for the editor)
    POST /api/validate                      — whole-tree lint
    POST /api/validate_one                  — single file
    GET  /api/budget                        — token budget summary
    GET  /api/backups                       — list backup manifests
    POST /api/backups/{id}/restore
    GET  /api/trash
    POST /api/trash/{id}/restore            — body: {skill_name}
    GET  /api/search?q=                     — full-text + structured (tag:foo)
    POST /api/write                         — content write (the chokepoint)
    POST /api/create                        — new SKILL.md / memory entry
    POST /api/rename                        — rename/move with reference integrity
    POST /api/duplicate
    POST /api/lock                          — toggle pinned
    POST /api/lifecycle                     — promote/archive/restore
    POST /api/import                        — import a skill archive
    GET  /api/export?path=                  — export a skill folder as tar.gz
    GET  /api/resolution?skill=             — which file wins, why

The HTML SPA is served at ``/``.
"""
from __future__ import annotations

import datetime as dt
import io
import json
import os
import secrets
import shutil
import tarfile
import time
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import (
    config as cfg_mod,
    hermes_vendor as hv,
    index_store,
    mutation,
    paths,
    validator,
)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title="Hermes MD Manager",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )

    # Serve the SPA
    static_dir = paths.static_dir()
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (static_dir / "index.html").read_text(encoding="utf-8")
        token = _session_token(app)
        # inject token + boot metadata
        meta = {
            "token": token,
            "version": app.version,
            "read_only": hv.state().read_only,
            "reasons": hv.state().reasons,
        }
        html = html.replace("<!--BOOT-META-->",
                            f'<script id="boot-meta" type="application/json">{json.dumps(meta)}</script>')
        return HTMLResponse(html)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        s = hv.state()
        return {
            "ok": True,
            "read_only": s.read_only,
            "reasons": s.reasons,
            "hermes_home": str(paths.hermes_home()),
            "state_dir": str(paths.state_dir()),
            "version": app.version,
        }

    @app.get("/api/tree")
    def tree() -> dict[str, Any]:
        reports = validator.scan_tree()
        # rebuild derived index for full-text search
        index_store.rebuild_from_reports(reports)
        return {
            "files": [
                {
                    "path": r.path,
                    "kind": r.kind,
                    "bytes": r.bytes,
                    "sha256": r.sha256,
                    "badge": r.badge,
                    "name": (r.parsed or {}).get("name") if isinstance(r.parsed, dict) else None,
                    "findings": [
                        {"severity": f.severity.value, "rule": f.rule, "message": f.message}
                        for f in r.findings
                    ],
                    "category": _category_of(r.path),
                }
                for r in reports
            ]
        }

    @app.get("/api/file")
    def file_detail(path: str = Query(...)) -> dict[str, Any]:
        p = Path(path)
        if not p.exists():
            raise HTTPException(404, f"file not found: {path}")
        home = paths.hermes_home()
        kind = validator.classify(p, hermes_home=home)
        report = validator.validate_skill_md(p, hermes_home=home) if kind in ("skill", "category_description") else None
        if kind == "memory":
            limit = _memory_limit(p.name)
            report = validator.validate_memory_file(p, char_limit=limit)
        if kind == "persona":
            report = validator.FileReport(
                path=str(p),
                kind="persona",
                bytes=p.stat().st_size,
                sha256=mutation.sha256_of(p),
                parsed=None,
                body=p.read_text(encoding="utf-8", errors="replace").strip(),
                findings=[],
                badge="green",
            )
        # attach .usage.json row if it's a skill
        usage = None
        if kind == "skill" and report and isinstance(report.parsed, dict):
            name = report.parsed.get("name")
            if isinstance(name, str):
                rec = hv.skill_usage_get_record()(name)
                usage = {
                    "state": rec.get("state"),
                    "pinned": rec.get("pinned"),
                    "use_count": rec.get("use_count"),
                    "view_count": rec.get("view_count"),
                    "patch_count": rec.get("patch_count"),
                    "last_used_at": rec.get("last_used_at"),
                    "last_viewed_at": rec.get("last_viewed_at"),
                    "last_patched_at": rec.get("last_patched_at"),
                    "created_by": rec.get("created_by"),
                    "archived_at": rec.get("archived_at"),
                }
        # lifecycle eligibility
        eligible = False
        if kind == "skill" and isinstance(report.parsed, dict):
            name = report.parsed.get("name")
            from tools import skill_usage  # vendored
            if isinstance(name, str):
                eligible = bool(skill_usage.is_curation_eligible(name))
        return {
            "report": (report.to_dict() if report else None),
            "usage": usage,
            "curation_eligible": eligible if kind == "skill" else None,
            "kind": kind,
        }

    @app.get("/api/file/raw")
    def file_raw(path: str = Query(...)) -> Response:
        p = Path(path)
        if not p.exists():
            raise HTTPException(404, f"file not found: {path}")
        return Response(
            content=p.read_bytes(),
            media_type="text/markdown; charset=utf-8",
            headers={"X-Sha256": mutation.sha256_of(p)},
        )

    @app.post("/api/validate")
    def validate_all() -> dict[str, Any]:
        reports = validator.scan_tree()
        counts = {"green": 0, "amber": 0, "red": 0}
        all_findings: list[dict[str, Any]] = []
        for r in reports:
            counts[r.badge] = counts.get(r.badge, 0) + 1
            for f in r.findings:
                all_findings.append({
                    "path": r.path,
                    "severity": f.severity.value,
                    "rule": f.rule,
                    "message": f.message,
                    "fix": f.fix,
                })
        return {"counts": counts, "findings": all_findings}

    @app.post("/api/validate_one")
    def validate_one(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        path = payload.get("path")
        if not path:
            raise HTTPException(400, "path required")
        p = Path(path)
        if not p.exists():
            raise HTTPException(404, f"file not found: {path}")
        kind = validator.classify(p, hermes_home=paths.hermes_home())
        if kind == "memory":
            r = validator.validate_memory_file(p, char_limit=_memory_limit(p.name))
        elif kind in ("skill", "category_description"):
            r = validator.validate_skill_md(p, hermes_home=paths.hermes_home())
        elif kind == "persona":
            r = validator.FileReport(
                path=str(p), kind="persona", bytes=p.stat().st_size,
                sha256=mutation.sha256_of(p), parsed=None,
                body=p.read_text(encoding="utf-8", errors="replace").strip(),
                findings=[], badge="green",
            )
        else:
            raise HTTPException(400, f"unsupported file kind for validate: {kind}")
        return r.to_dict()

    @app.get("/api/budget")
    def budget() -> dict[str, Any]:
        reports = validator.scan_tree()
        persona = 0
        memory_total = 0
        index_chars = 0
        breakdown: list[dict[str, Any]] = []
        chars_per_token = cfg_mod.load().get("token_chars_per_token", 4)
        for r in reports:
            if r.kind == "persona":
                persona = r.bytes
                breakdown.append({"path": r.path, "kind": "persona", "chars": r.bytes, "tokens_est": r.bytes // chars_per_token})
            elif r.kind == "memory":
                memory_total += r.bytes
                breakdown.append({"path": r.path, "kind": "memory", "chars": r.bytes, "tokens_est": r.bytes // chars_per_token})
            elif r.kind == "skill":
                # index line for this skill = name + truncated description
                fm = r.parsed if isinstance(r.parsed, dict) else {}
                name = str(fm.get("name", "") or "")
                desc = str(fm.get("description", "") or "")
                # extract_skill_description truncates at 60 chars
                desc = desc.strip().strip("'\"")
                if len(desc) > 60:
                    desc = desc[:57] + "..."
                line = f"    - {name}: {desc}"
                index_chars += len(line)
            elif r.kind == "category_description":
                # category header in the index
                fm = r.parsed if isinstance(r.parsed, dict) else {}
                desc = str(fm.get("description", "") or "")
                cat = _category_of(r.path)
                line = f"  {cat}: {desc}"
                index_chars += len(line)
        always_loaded_chars = persona + memory_total + index_chars
        breakdown.append({"path": "<skills index>", "kind": "index", "chars": index_chars, "tokens_est": index_chars // chars_per_token})
        return {
            "chars_per_token": chars_per_token,
            "always_loaded_chars": always_loaded_chars,
            "tokens_est": always_loaded_chars // chars_per_token,
            "persona_chars": persona,
            "memory_chars": memory_total,
            "index_chars": index_chars,
            "breakdown": breakdown,
        }

    @app.post("/api/write")
    def write_file(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if hv.state().read_only:
            raise HTTPException(503, f"source-parity check tripped: {hv.state().reasons}")
        path = payload.get("path")
        content = payload.get("content")
        baseline = payload.get("baseline_sha256")
        approved = payload.get("approved", False)
        if not path or content is None:
            raise HTTPException(400, "path and content required")
        p = Path(path)
        if isinstance(content, str):
            content_bytes = content.encode("utf-8")
        else:
            content_bytes = bytes(content)
        result = mutation.write_atomically(
            target=p,
            content=content_bytes,
            baseline_sha256=baseline,
            op="write",
            approved=bool(approved),
            relative_to=paths.hermes_home(),
        )
        if result.ok:
            mutation.clear_prompt_snapshot()
        return _result_dict(result)

    @app.post("/api/create")
    def create(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if hv.state().read_only:
            raise HTTPException(503, f"source-parity check tripped: {hv.state().reasons}")
        kind = payload.get("kind")  # "skill" | "memory_entry"
        if kind == "skill":
            name = payload.get("name")
            category = payload.get("category")
            content = payload.get("content")  # full SKILL.md text
            if not name or not content:
                raise HTTPException(400, "name and content required")
            cat = (category or "").strip()
            if cat:
                skill_dir = paths.hermes_home() / "skills" / cat / name
            else:
                skill_dir = paths.hermes_home() / "skills" / name
            if skill_dir.exists():
                raise HTTPException(409, f"destination already exists: {skill_dir}")
            skill_dir.mkdir(parents=True, exist_ok=True)
            target = skill_dir / "SKILL.md"
            # baseline = None (creating)
            result = mutation.write_atomically(
                target=target,
                content=content.encode("utf-8"),
                baseline_sha256=None,
                op="create_skill",
                approved=True,
                relative_to=paths.hermes_home(),
            )
            if result.ok:
                mutation.clear_prompt_snapshot()
            return _result_dict(result)
        elif kind == "memory_entry":
            target_name = payload.get("file")  # "MEMORY.md" | "USER.md"
            entry = (payload.get("content") or "").strip()
            if target_name not in ("MEMORY.md", "USER.md"):
                raise HTTPException(400, "file must be MEMORY.md or USER.md")
            if not entry:
                raise HTTPException(400, "content required")
            target = paths.hermes_home() / "memories" / target_name
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            new_content = existing.rstrip() + ("\n§\n" if existing.strip() else "") + entry + "\n"
            # round-trip pre-flight
            limit = _memory_limit(target_name)
            preflight = validator.validate_memory_file(_simulated_path(target, new_content), char_limit=limit)
            if preflight.findings and any(f.severity == validator.Severity.REJECT for f in preflight.findings):
                raise HTTPException(400, f"memory validation failed: {[f.message for f in preflight.findings]}")
            baseline = mutation.sha256_of(target) if target.exists() else None
            result = mutation.write_atomically(
                target=target,
                content=new_content.encode("utf-8"),
                baseline_sha256=baseline,
                op="memory_add_entry",
                approved=True,
                relative_to=paths.hermes_home(),
            )
            return _result_dict(result)
        raise HTTPException(400, f"unknown kind: {kind}")

    @app.post("/api/rename")
    def rename(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if hv.state().read_only:
            raise HTTPException(503, "read-only mode")
        src = Path(payload.get("path") or "")
        new_name = (payload.get("new_name") or "").strip()
        approved = bool(payload.get("approved"))
        if not src.exists():
            raise HTTPException(404, f"path not found: {src}")
        if not new_name:
            raise HTTPException(400, "new_name required")
        # The path must be a skill dir or SKILL.md
        skill_dir = src if src.is_dir() else src.parent
        # parse current frontmatter name
        report = validator.validate_skill_md(skill_dir / "SKILL.md", hermes_home=paths.hermes_home())
        old_name = (report.parsed or {}).get("name") if isinstance(report.parsed, dict) else None
        # integrity scan
        refs = _scan_references(old_name or "", skill_dir.name, new_name)
        if not approved:
            return {"ok": False, "requires_approval": True, "references": refs,
                    "message": "approve with approved=true to apply rename"}
        new_dir = skill_dir.parent / new_name
        if new_dir.exists():
            raise HTTPException(409, f"destination already exists: {new_dir}")
        try:
            shutil.move(str(skill_dir), str(new_dir))
        except OSError as exc:
            raise HTTPException(500, f"rename failed: {exc}")
        # if frontmatter name changed, re-key .usage.json under flock
        if old_name and old_name != new_name:
            from tools import skill_usage
            with skill_usage._usage_file_lock():
                data = skill_usage.load_usage()
                if old_name in data:
                    rec = data.pop(old_name)
                    rec["name"] = new_name
                    data[new_name] = rec
                    skill_usage.save_usage(data)
        mutation.clear_prompt_snapshot()
        return {"ok": True, "new_path": str(new_dir / "SKILL.md"), "references": refs}

    @app.post("/api/duplicate")
    def duplicate(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if hv.state().read_only:
            raise HTTPException(503, "read-only mode")
        src = Path(payload.get("path") or "")
        new_name = (payload.get("new_name") or "").strip()
        if not src.exists():
            raise HTTPException(404, f"path not found: {src}")
        if not new_name:
            raise HTTPException(400, "new_name required")
        skill_dir = src if src.is_dir() else src.parent
        new_dir = skill_dir.parent / new_name
        if new_dir.exists():
            raise HTTPException(409, f"destination already exists: {new_dir}")
        try:
            shutil.copytree(skill_dir, new_dir)
        except OSError as exc:
            raise HTTPException(500, f"duplicate failed: {exc}")
        # rewrite frontmatter name in the copy to avoid identity collision
        target_skill_md = new_dir / "SKILL.md"
        if target_skill_md.exists():
            text = target_skill_md.read_text(encoding="utf-8")
            try:
                loader = hv.parse_frontmatter()
                fm, body = loader(text)
                if isinstance(fm, dict) and fm.get("name") != new_name:
                    # simple sed-style replacement of the first `name:` line
                    lines = text.split("\n")
                    new_lines: list[str] = []
                    replaced = False
                    in_fm = False
                    fence_count = 0
                    for line in lines:
                        if line.strip() == "---":
                            fence_count += 1
                            new_lines.append(line)
                            in_fm = (fence_count % 2 == 1)
                            continue
                        if in_fm and not replaced and line.startswith("name:"):
                            new_lines.append(f"name: {new_name}")
                            replaced = True
                        else:
                            new_lines.append(line)
                    new_text = "\n".join(new_lines)
                    baseline = mutation.sha256_of(target_skill_md)
                    mutation.write_atomically(
                        target=target_skill_md,
                        content=new_text.encode("utf-8"),
                        baseline_sha256=baseline,
                        op="duplicate_rewrite_name",
                        approved=True,
                        relative_to=paths.hermes_home(),
                    )
            except Exception:
                pass
        mutation.clear_prompt_snapshot()
        return {"ok": True, "new_path": str(new_dir / "SKILL.md")}

    @app.post("/api/lock")
    def set_lock(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if hv.state().read_only:
            raise HTTPException(503, "read-only mode")
        name = payload.get("name")
        pinned = bool(payload.get("pinned"))
        if not name:
            raise HTTPException(400, "name required")
        from tools import skill_usage  # vendored
        if not skill_usage.is_curation_eligible(name):
            raise HTTPException(400, "skill is not curation-eligible (hub-installed / external / protected)")
        skill_usage.set_pinned(name, pinned)
        return {"ok": True, "name": name, "pinned": pinned}

    @app.post("/api/lifecycle")
    def lifecycle(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if hv.state().read_only:
            raise HTTPException(503, "read-only mode")
        action = payload.get("action")
        name = payload.get("name")
        if action not in ("archive", "restore", "promote_active", "promote_stale") or not name:
            raise HTTPException(400, "action and name required")
        if action == "archive":
            ok, msg = mutation.lifecycle_archive_skill(name)
        elif action == "restore":
            ok, msg = mutation.lifecycle_restore_skill(name)
        else:
            target_state = {"promote_active": "active", "promote_stale": "stale"}[action]
            from tools import skill_usage
            try:
                skill_usage.set_state(name, target_state)
                ok, msg = True, f"state set to {target_state}"
            except Exception as exc:
                ok, msg = False, str(exc)
        return {"ok": ok, "message": msg}

    @app.get("/api/backups")
    def list_backups() -> dict[str, Any]:
        return {"backups": mutation.list_backups()}

    @app.post("/api/backups/{backup_id}/restore")
    def restore_backup(backup_id: str) -> dict[str, Any]:
        return _result_dict(mutation.restore_backup(backup_id))

    @app.get("/api/trash")
    def list_trash() -> dict[str, Any]:
        return {"trash": mutation.list_trash()}

    @app.post("/api/trash/{trash_id}/restore")
    def restore_trash(trash_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        skill_name = payload.get("skill_name") or payload.get("name")
        if not skill_name:
            raise HTTPException(400, "skill_name required")
        return _result_dict(mutation.restore_from_trash(trash_id, skill_name))

    @app.get("/api/search")
    def search(q: str = Query(""), kind: str | None = None) -> dict[str, Any]:
        return {"hits": index_store.search(q, kind=kind)}

    @app.get("/api/resolution")
    def resolution(skill: str = Query(...)) -> dict[str, Any]:
        from tools import skill_usage
        # find local matches
        home = paths.hermes_home()
        skills_root = home / "skills"
        local = []
        for p in iter_local_skill_md(skills_root):
            r = validator.validate_skill_md(p, hermes_home=home)
            if isinstance(r.parsed, dict) and r.parsed.get("name") == skill:
                local.append(r.path)
        # external matches
        external = []
        try:
            ext_dirs = hv.get_external_skills_dirs()()
        except Exception:
            ext_dirs = []
        for d in ext_dirs:
            if not d.is_dir():
                continue
            for p in hv.iter_skill_index_files()(d, "SKILL.md"):
                r = validator.validate_skill_md(p, hermes_home=home)
                if isinstance(r.parsed, dict) and r.parsed.get("name") == skill:
                    external.append(r.path)
        return {
            "skill": skill,
            "local": local,
            "external": external,
            "winner": local[0] if local else (external[0] if external else None),
            "rule": "local root always wins; external with already-seen frontmatter name is skipped (prompt_builder.py:1575)",
            "provenance": skill_usage.provenance(skill),
        }

    @app.post("/api/import")
    def import_skill(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if hv.state().read_only:
            raise HTTPException(503, "read-only mode")
        # payload: {archive_b64: str} | {tar_path: str} — but we accept a base64 tar.gz string for simplicity
        import base64
        b64 = payload.get("archive_b64") or ""
        if not b64:
            raise HTTPException(400, "archive_b64 required")
        try:
            blob = base64.b64decode(b64)
        except Exception as exc:
            raise HTTPException(400, f"base64 decode failed: {exc}")
        # validate archive first
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            members = tar.getmembers()
            skill_md_member = None
            for m in members:
                if m.name.endswith("SKILL.md"):
                    skill_md_member = m
                    break
            if not skill_md_member:
                raise HTTPException(400, "archive must contain SKILL.md")
            skill_text = tar.extractfile(skill_md_member).read().decode("utf-8")
            # loud pass
            report = validator._loud_check_skill(skill_text) if False else None
            loud = validator._loud_check_skill(skill_text)
            if loud and any(f.severity == validator.Severity.REJECT for f in loud):
                raise HTTPException(400, f"validator refused: {[f.message for f in loud]}")
        # dry-run: if dry_run=True, return preview
        if payload.get("dry_run"):
            return {"dry_run": True, "ok": True, "members": len(members), "skill_md_size": len(skill_text)}
        # extract to a fresh dir under skills/<name>/
        name = payload.get("name")
        if not name:
            raise HTTPException(400, "name required for import")
        dest = paths.hermes_home() / "skills" / name
        if dest.exists():
            raise HTTPException(409, f"destination already exists: {dest}")
        dest.mkdir(parents=True, exist_ok=False)
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            # strip the top-level dir from the archive to land files directly in dest
            for m in members:
                if m.name.startswith("./"):
                    tail = m.name[2:]
                else:
                    tail = m.name
                # find first '/' — strip top dir
                idx = tail.find("/")
                if idx == -1:
                    continue
                tail = tail[idx + 1:]
                if not tail:
                    continue
                target = dest / tail
                if m.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    f = tar.extractfile(m)
                    if f is None:
                        continue
                    target.write_bytes(f.read())
                elif m.isdir():
                    target.mkdir(parents=True, exist_ok=True)
        mutation.clear_prompt_snapshot()
        return {"ok": True, "path": str(dest / "SKILL.md")}

    @app.get("/api/export")
    def export(path: str = Query(...)) -> Response:
        p = Path(path)
        if not p.exists():
            raise HTTPException(404, f"path not found: {path}")
        skill_dir = p if p.is_dir() else p.parent
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            tar.add(str(skill_dir), arcname=f"./{skill_dir.name}/")
        return Response(
            content=buf.getvalue(),
            media_type="application/gzip",
            headers={
                "Content-Disposition": f'attachment; filename="{skill_dir.name}.tar.gz"',
            },
        )

    @app.post("/api/delete")
    def delete(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if hv.state().read_only:
            raise HTTPException(503, "read-only mode")
        path = payload.get("path")
        mode = payload.get("mode", "soft")  # "soft" | "archive"
        approved = bool(payload.get("approved"))
        if not path:
            raise HTTPException(400, "path required")
        p = Path(path)
        skill_dir = p if p.is_dir() else p.parent
        if mode == "archive":
            if not approved:
                return {"ok": False, "requires_approval": True,
                        "message": "archive moves skill to Hermes' .archive/; approve to proceed"}
            # extract frontmatter name for lifecycle
            r = validator.validate_skill_md(skill_dir / "SKILL.md", hermes_home=paths.hermes_home())
            name = (r.parsed or {}).get("name") if isinstance(r.parsed, dict) else None
            if not isinstance(name, str):
                raise HTTPException(400, "skill has no parseable name")
            ok, msg = mutation.lifecycle_archive_skill(name)
            return {"ok": ok, "message": msg, "mode": "archive"}
        # default soft
        if not approved:
            return {"ok": False, "requires_approval": True,
                    "message": "soft-delete moves skill to external trash; approve to proceed"}
        result = mutation.soft_delete_skill(skill_dir)
        if result.ok:
            mutation.clear_prompt_snapshot()
        return _result_dict(result)

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _memory_limit(filename: str) -> int:
    if filename == "USER.md":
        return 1375
    return 2200


def _category_of(path: str) -> str:
    p = Path(path)
    home = paths.hermes_home()
    try:
        rel = p.relative_to(home / "skills")
    except ValueError:
        return ""
    parts = rel.parts
    if len(parts) >= 3:
        return "/".join(parts[:-2]) or "general"
    return "general"


def _simulated_path(target: Path, content: str) -> Path:
    """Helper for pre-flight validation: write content to a temp file and
    return that path so the validator can read it.
    """
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".md", prefix=".mem_preflight_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return Path(tmp)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return target


def _result_dict(result: mutation.WriteResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "backup_id": result.backup_id,
        "target": result.target,
        "sha256_after": result.sha256_after,
        "bytes_written": result.bytes_written,
        "message": result.message,
        "error": result.error,
        "error_kind": result.error_kind,
    }


def _scan_references(old_name: str, old_dir_name: str, new_name: str) -> dict[str, Any]:
    """Lightweight reference-integrity scan. Reports what we found; the caller
    must approve each update.
    """
    home = paths.hermes_home()
    hits: list[dict[str, str]] = []
    # 1. .usage.json
    usage_path = home / "skills" / ".usage.json"
    if usage_path.exists():
        try:
            data = json.loads(usage_path.read_text(encoding="utf-8"))
            for key in list(data.keys()):
                if key == old_name:
                    hits.append({"where": ".usage.json", "kind": "key", "ref": key})
                if isinstance(data[key], dict):
                    related = data[key].get("related_skills") or []
                    if isinstance(related, list) and old_name in related:
                        hits.append({"where": f".usage.json[{key}].related_skills", "kind": "value", "ref": old_name})
        except (OSError, json.JSONDecodeError):
            pass
    # 2. .bundled_manifest
    bm = home / "skills" / ".bundled_manifest"
    if bm.exists():
        text = bm.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            name = line.split(":", 1)[0].strip()
            if name == old_name:
                hits.append({"where": ".bundled_manifest", "kind": "key", "ref": name})
    # 3. all SKILL.md frontmatter related_skills
    for p in iter_local_skill_md(home / "skills"):
        try:
            loader = hv.parse_frontmatter()
            text = p.read_text(encoding="utf-8")
            fm, _ = loader(text)
            if isinstance(fm, dict):
                related = fm.get("related_skills") or []
                if isinstance(related, list) and old_name in related:
                    hits.append({"where": str(p), "kind": "related_skills", "ref": old_name})
        except OSError:
            continue
    # 4. config.yaml — external_dirs list (mention only)
    cfg = home / "config.yaml"
    if cfg.exists():
        try:
            text = cfg.read_text(encoding="utf-8", errors="replace")
            if old_name in text:
                hits.append({"where": "config.yaml", "kind": "text-mention", "ref": old_name})
        except OSError:
            pass
    return {
        "old_name": old_name,
        "old_dir_name": old_dir_name,
        "new_name": new_name,
        "hits": hits,
        "n": len(hits),
    }


def iter_local_skill_md(skills_root: Path):
    if not skills_root.is_dir():
        return
    for p in hv.iter_skill_index_files()(skills_root, "SKILL.md"):
        yield p


# ---------------------------------------------------------------------------
# Per-boot random token (CSRF defense for the loopback listener)
# ---------------------------------------------------------------------------


def _session_token(app: FastAPI) -> str:
    if not hasattr(app.state, "token"):
        app.state.token = secrets.token_urlsafe(16)
    return app.state.token