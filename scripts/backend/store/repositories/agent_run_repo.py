"""AgentRun repository — agent_runs tablosu için veri erişim katmanı (SRP)."""
from __future__ import annotations

import asyncio
import json
import time
import uuid

from ._thread_runner import run_in_thread
from .._connection import _conn


# ── Sync implementasyonlar (_sync_* prefix) ───────────────────────


def _sync_agent_run_create(
    agent_type: str,
    session_id: str,
    project_id: str | None,
    task_id: str | None,
    source: str,
    sender: str | None,
    prompt: str | None,
    metadata: dict | None,
) -> str:
    """Yeni agent run kaydı oluştur, id döndür."""
    run_id = str(uuid.uuid4())
    created_at = time.time()
    meta_json = json.dumps(metadata or {})
    with _conn() as con:
        con.execute(
            """
            INSERT INTO agent_runs
              (id, agent_type, session_id, project_id, task_id,
               source, sender, prompt, status, metadata, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                run_id, agent_type, session_id, project_id, task_id,
                source, sender, prompt, "pending", meta_json, created_at,
            ),
        )
    return run_id


def _sync_agent_run_update_status(
    run_id: str,
    status: str,
    duration_ms: int | None,
    output: str | None,
    error_msg: str | None,
    exit_code: int | None,
) -> None:
    """Agent run durumunu güncelle.

    status='running'                              → started_at=now
    status in ('completed','failed','cancelled')  → completed_at=now;
      duration_ms sağlanmadıysa started_at'dan hesaplanır.
    """
    now = time.time()
    with _conn() as con:
        if status == "running":
            con.execute(
                "UPDATE agent_runs SET status=?, started_at=? WHERE id=?",
                (status, now, run_id),
            )
        elif status in ("completed", "failed", "cancelled"):
            if duration_ms is None:
                row = con.execute(
                    "SELECT started_at FROM agent_runs WHERE id=?", (run_id,)
                ).fetchone()
                if row and row["started_at"]:
                    duration_ms = int((now - row["started_at"]) * 1000)
            con.execute(
                """
                UPDATE agent_runs
                   SET status=?, completed_at=?, duration_ms=?,
                       output=?, error_msg=?, exit_code=?
                 WHERE id=?
                """,
                (status, now, duration_ms, output, error_msg, exit_code, run_id),
            )
        else:
            # Generic status update (e.g. 'queued')
            con.execute(
                "UPDATE agent_runs SET status=? WHERE id=?",
                (status, run_id),
            )


def _sync_agent_run_get(run_id: str) -> dict | None:
    """Tek agent run getir."""
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM agent_runs WHERE id=?", (run_id,)
        ).fetchone()
        return dict(row) if row else None


def _sync_agent_run_list(
    project_id: str | None,
    session_id: str | None,
    status: str | None,
    limit: int,
    offset: int,
) -> list[dict]:
    """Agent run'ları filtreli listele (en yeni önce)."""
    clauses: list[str] = []
    params: list[object] = []

    if project_id is not None:
        clauses.append("project_id=?")
        params.append(project_id)
    if session_id is not None:
        clauses.append("session_id=?")
        params.append(session_id)
    if status is not None:
        clauses.append("status=?")
        params.append(status)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.extend([limit, offset])

    with _conn() as con:
        rows = con.execute(
            f"SELECT * FROM agent_runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def _sync_agent_run_cancel(run_id: str) -> None:
    """status='cancelled', completed_at=now yap."""
    now = time.time()
    with _conn() as con:
        con.execute(
            "UPDATE agent_runs SET status='cancelled', completed_at=? WHERE id=?",
            (now, run_id),
        )


def _sync_agent_run_list_active() -> list[dict]:
    """status='pending' veya 'running' olan tüm run'lar (en eski önce)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM agent_runs WHERE status IN ('pending','running') "
            "ORDER BY created_at ASC",
        ).fetchall()
        return [dict(r) for r in rows]


# ── Async public API ──────────────────────────────────────────────


async def agent_run_create(
    agent_type: str,
    session_id: str,
    *,
    project_id: str | None = None,
    task_id: str | None = None,
    source: str = "internal",
    sender: str | None = None,
    prompt: str | None = None,
    metadata: dict | None = None,
) -> str:
    """Yeni agent run kaydı oluştur, id döndür."""
    return await run_in_thread(
        _sync_agent_run_create,
        agent_type,
        session_id,
        project_id,
        task_id,
        source,
        sender,
        prompt,
        metadata,
    )


async def agent_run_update_status(
    run_id: str,
    status: str,
    *,
    duration_ms: int | None = None,
    output: str | None = None,
    error_msg: str | None = None,
    exit_code: int | None = None,
) -> None:
    """Agent run durumunu güncelle."""
    return await run_in_thread(
        _sync_agent_run_update_status,
        run_id,
        status,
        duration_ms,
        output,
        error_msg,
        exit_code,
    )


async def agent_run_get(run_id: str) -> dict | None:
    """Tek agent run getir."""
    return await run_in_thread(_sync_agent_run_get, run_id)


async def agent_run_list(
    *,
    project_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Agent run'ları filtreli listele."""
    return await run_in_thread(
        _sync_agent_run_list,
        project_id,
        session_id,
        status,
        limit,
        offset,
    )


async def agent_run_cancel(run_id: str) -> None:
    """Agent run'ı iptal et."""
    return await run_in_thread(_sync_agent_run_cancel, run_id)


async def agent_run_list_active() -> list[dict]:
    """status='pending' veya 'running' olan tüm run'lar."""
    return await run_in_thread(_sync_agent_run_list_active)


def _sync_agent_run_list_by_project(project_id: str, limit: int = 10) -> list[dict]:
    """Belirli bir projeye ait son run'ları döndürür."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM agent_runs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


async def agent_run_list_by_project(project_id: str, limit: int = 10) -> list[dict]:
    """Belirli bir projeye ait son run'ları döndürür (async)."""
    return await run_in_thread(_sync_agent_run_list_by_project, project_id, limit)
