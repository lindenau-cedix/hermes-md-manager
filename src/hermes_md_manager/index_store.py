"""Derived index (sqlite FTS5) over the HERMES_HOME tree.

Always rebuildable from disk — deleting this file loses nothing.

Tables:
  files(path TEXT PRIMARY KEY, kind TEXT, category TEXT, name TEXT, bytes INT,
        sha256 TEXT, badge TEXT, fm_json TEXT, body TEXT, updated_at TEXT)
  files_fts(path, kind, category, name, body) — FTS5

The index is read-mostly. On any write we wipe the affected row and re-insert
(the mutation chokepoint is the only writer).
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable

from . import paths


_LOCK = threading.Lock()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(paths.index_db_path()))
    conn.row_factory = sqlite3.Row
    return conn


@contextlib.contextmanager
def cursor(commit: bool = False) -> Iterable[sqlite3.Cursor]:
    with _LOCK:
        conn = _connect()
        try:
            cur = conn.cursor()
            yield cur
            if commit:
                conn.commit()
        finally:
            conn.close()


def ensure_schema() -> None:
    with cursor(commit=True) as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                kind TEXT,
                category TEXT,
                name TEXT,
                bytes INTEGER,
                sha256 TEXT,
                badge TEXT,
                fm_json TEXT,
                body TEXT,
                updated_at TEXT
            )
        """)
        # FTS5 virtual table (contentless — we mirror body text here)
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
                path UNINDEXED, kind, category, name, body
            )
        """)


def reset() -> None:
    with cursor(commit=True) as cur:
        cur.execute("DELETE FROM files")
        cur.execute("DELETE FROM files_fts")


def upsert(report: Any) -> None:
    """Upsert one FileReport dataclass."""
    from datetime import datetime, timezone
    category = ""
    name = ""
    fm = report.parsed or {}
    if isinstance(fm, dict):
        name = str(fm.get("name", "") or "")
    if report.kind == "skill":
        # category = top-level segment(s) before the skill's own dir
        p = Path(report.path)
        try:
            rel = p.relative_to(paths.hermes_home() / "skills")
        except ValueError:
            rel = p
        parts = rel.parts  # (...<skill>, "SKILL.md")
        if len(parts) >= 3:
            # nested category/skill/SKILL.md
            category = "/".join(parts[:-2]) or ""
        elif len(parts) == 2:
            category = "general"
    with cursor(commit=True) as cur:
        cur.execute(
            "REPLACE INTO files (path, kind, category, name, bytes, sha256, badge, fm_json, body, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                report.path,
                report.kind,
                category,
                name,
                report.bytes,
                report.sha256,
                report.badge,
                json.dumps(report.parsed, ensure_ascii=False) if isinstance(report.parsed, dict) else "",
                report.body or "",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        cur.execute(
            "DELETE FROM files_fts WHERE path = ?",
            (report.path,),
        )
        cur.execute(
            "INSERT INTO files_fts (path, kind, category, name, body) VALUES (?, ?, ?, ?, ?)",
            (report.path, report.kind, category, name, report.body or ""),
        )


def rebuild_from_reports(reports: Iterable[Any]) -> int:
    ensure_schema()
    reset()
    n = 0
    for r in reports:
        upsert(r)
        n += 1
    return n


def search(query: str, *, kind: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    ensure_schema()
    if not query.strip():
        return []
    with cursor() as cur:
        sql = (
            "SELECT path, kind, category, name, snippet(files_fts, 4, '«', '»', '…', 12) AS snip "
            "FROM files_fts WHERE files_fts MATCH ?"
        )
        params: list[Any] = [query]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " LIMIT ?"
        params.append(limit)
        rows = cur.execute(sql, params).fetchall()
        return [dict(r) for r in rows]


def list_files(*, kind: str | None = None) -> list[dict[str, Any]]:
    ensure_schema()
    with cursor() as cur:
        if kind:
            rows = cur.execute(
                "SELECT path, kind, category, name, bytes, sha256, badge FROM files WHERE kind = ? ORDER BY path",
                (kind,),
            ).fetchall()
        else:
            rows = cur.execute(
                "SELECT path, kind, category, name, bytes, sha256, badge FROM files ORDER BY path"
            ).fetchall()
        return [dict(r) for r in rows]


def get_file(path: str) -> dict[str, Any] | None:
    ensure_schema()
    with cursor() as cur:
        row = cur.execute(
            "SELECT path, kind, category, name, bytes, sha256, badge, fm_json, body FROM files WHERE path = ?",
            (path,),
        ).fetchone()
        if not row:
            return None
        out = dict(row)
        if out.get("fm_json"):
            try:
                out["parsed"] = json.loads(out["fm_json"])
            except json.JSONDecodeError:
                out["parsed"] = None
        return out