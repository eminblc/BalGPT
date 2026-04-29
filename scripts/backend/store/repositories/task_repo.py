"""Scheduled Tasks repository — scheduled_tasks tablosu için veri erişimi (SRP)."""
from __future__ import annotations

import json

from ._thread_runner import run_in_thread
import time
import uuid

from .._connection import _conn


def _sync_task_create(description: str, action_type: str, action_payload: dict,
                      cron_expr: str | None = None, next_run: float | None = None) -> dict:
    task_id = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            "INSERT INTO scheduled_tasks (id,description,cron_expr,next_run,action_type,action_payload) "
            "VALUES (?,?,?,?,?,?)",
            (task_id, description, cron_expr, next_run, action_type, json.dumps(action_payload)),
        )
    return _sync_task_get(task_id)


def _sync_task_get(task_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM scheduled_tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None


def _sync_task_list_active() -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM scheduled_tasks WHERE active=1 ORDER BY next_run",
        ).fetchall()
        return [dict(r) for r in rows]


def _sync_task_deactivate(task_id: str) -> None:
    with _conn() as con:
        con.execute("UPDATE scheduled_tasks SET active=0 WHERE id=?", (task_id,))


def _sync_task_activate(task_id: str) -> None:
    with _conn() as con:
        con.execute("UPDATE scheduled_tasks SET active=1 WHERE id=?", (task_id,))


def _sync_task_delete(task_id: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM scheduled_tasks WHERE id=?", (task_id,))


def _sync_task_list_all() -> list[dict]:
    """Aktif ve pasif tüm görevler."""
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM scheduled_tasks ORDER BY active DESC, next_run",
        ).fetchall()
        return [dict(r) for r in rows]


def _sync_task_find_by_prefix(prefix: str) -> dict | None:
    """ID'nin ilk karakterleriyle eşleşen ilk görevi döndürür."""
    escaped = prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    with _conn() as con:
        row = con.execute(
            "SELECT * FROM scheduled_tasks WHERE id LIKE ? ESCAPE '\\'", (f"{escaped}%",)
        ).fetchone()
        return dict(row) if row else None


def _sync_task_update_last_run(task_id: str) -> None:
    """APScheduler job çalıştıktan sonra last_run'ı güncelle."""
    with _conn() as con:
        con.execute(
            "UPDATE scheduled_tasks SET last_run=? WHERE id=?",
            (time.time(), task_id),
        )


def _sync_task_soft_delete(task_id: str) -> None:
    """Soft delete: active=0, status='deleted', deleted_at=now."""
    with _conn() as con:
        con.execute(
            "UPDATE scheduled_tasks SET active=0, status='deleted', deleted_at=? WHERE id=?",
            (time.time(), task_id),
        )


def _sync_task_update_status(task_id: str, status: str) -> None:
    """Job durumunu güncelle: 'scheduled' | 'running' | 'succeeded' | 'failed' | 'deleted'."""
    with _conn() as con:
        con.execute(
            "UPDATE scheduled_tasks SET status=? WHERE id=?",
            (status, task_id),
        )


# ── Async public API ──────────────────────────────────────────────

async def task_create(
    description: str,
    action_type: str,
    action_payload: dict,
    cron_expr: str | None = None,
    next_run: float | None = None,
) -> dict:
    return await run_in_thread(
        _sync_task_create, description, action_type, action_payload, cron_expr, next_run
    )


async def task_get(task_id: str) -> dict | None:
    return await run_in_thread(_sync_task_get, task_id)


async def task_list_active() -> list[dict]:
    return await run_in_thread(_sync_task_list_active)


async def task_deactivate(task_id: str) -> None:
    return await run_in_thread(_sync_task_deactivate, task_id)


async def task_activate(task_id: str) -> None:
    return await run_in_thread(_sync_task_activate, task_id)


async def task_delete(task_id: str) -> None:
    return await run_in_thread(_sync_task_delete, task_id)


async def task_list_all() -> list[dict]:
    return await run_in_thread(_sync_task_list_all)


async def task_find_by_prefix(prefix: str) -> dict | None:
    return await run_in_thread(_sync_task_find_by_prefix, prefix)


async def task_update_last_run(task_id: str) -> None:
    return await run_in_thread(_sync_task_update_last_run, task_id)


async def task_soft_delete(task_id: str) -> None:
    return await run_in_thread(_sync_task_soft_delete, task_id)


async def task_update_status(task_id: str, status: str) -> None:
    return await run_in_thread(_sync_task_update_status, task_id, status)
