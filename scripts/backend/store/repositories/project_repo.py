"""Proje repository — projects tablosu için tüm veri erişimi (SRP).

Sync implementasyonlar (_sync_*) ile run_in_thread() sarmalayıcıları içerir.
"""
from __future__ import annotations

import re

from ._thread_runner import run_in_thread
import sqlite3
import time
import unicodedata
from pathlib import Path

from .._connection import _conn

_PROJECT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,62}$")


def slugify_project_name(name: str) -> str:
    """Proje adından URL-güvenli proje ID'si türet.

    Türkçe ve diğer Unicode karakterleri ASCII karşılıklarına dönüştürür:
      "Müzik API"   → "muzik-api"
      "Şehir Planı" → "sehir-plani"
      "Hello World!" → "hello-world"
    """
    _TR_PRE = str.maketrans("ıİ", "iI")
    name = name.translate(_TR_PRE)
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = normalized.lower().replace(" ", "-")
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "proje"


def _sync_project_create(
    name: str,
    description: str = "",
    source_pdf: str | None = None,
    metadata: str = "{}",
    path: str | None = None,
) -> dict:
    project_id = slugify_project_name(name)
    if not _PROJECT_ID_RE.match(project_id):
        raise ValueError(
            f"Geçersiz proje ID'si: '{project_id}'. "
            "Yalnızca küçük harf, rakam ve tire kullanılabilir."
        )
    if path is None:
        from ...app_types import DEFAULT_PROJECTS_DIR
        path = str(DEFAULT_PROJECTS_DIR / project_id)
    now = time.time()
    try:
        with _conn() as con:
            con.execute(
                "INSERT INTO projects (id,name,description,path,created_at,updated_at,source_pdf,metadata) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (project_id, name, description, path, now, now, source_pdf, metadata),
            )
    except sqlite3.IntegrityError:
        raise ValueError(f"Proje zaten mevcut: {name!r}")
    return _sync_project_get(project_id)


def _sync_project_get(project_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None


def _sync_project_list() -> list[dict]:
    with _conn() as con:
        rows = con.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


def _sync_project_update_status(project_id: str, status: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE projects SET status=?, updated_at=? WHERE id=?",
            (status, time.time(), project_id),
        )


def _sync_project_delete(project_id: str) -> bool:
    """Projeyi DB'den siler. Dosya sistemi etkilenmez."""
    with _conn() as con:
        cur = con.execute("DELETE FROM projects WHERE id=?", (project_id,))
        return cur.rowcount > 0


# ── Async public API ──────────────────────────────────────────────

async def project_create(
    name: str,
    description: str = "",
    source_pdf: str | None = None,
    metadata: str = "{}",
    path: str | None = None,
) -> dict:
    return await run_in_thread(_sync_project_create, name, description, source_pdf, metadata, path)


async def project_get(project_id: str) -> dict | None:
    return await run_in_thread(_sync_project_get, project_id)


async def project_list() -> list[dict]:
    return await run_in_thread(_sync_project_list)


async def project_update_status(project_id: str, status: str) -> None:
    return await run_in_thread(_sync_project_update_status, project_id, status)


async def project_delete(project_id: str) -> bool:
    return await run_in_thread(_sync_project_delete, project_id)
