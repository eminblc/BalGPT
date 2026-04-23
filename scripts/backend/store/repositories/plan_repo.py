"""Work Plans repository — work_plans tablosu için veri erişimi (SRP)."""
from __future__ import annotations

import time
import uuid

from .._connection import _conn
from ._thread_runner import run_in_thread


def _sync_plan_create(title: str, description: str = "", priority: int = 2,
                      due_date: float | None = None, project_id: str | None = None) -> dict:
    plan_id = str(uuid.uuid4())
    now = time.time()
    with _conn() as con:
        con.execute(
            "INSERT INTO work_plans (id,title,description,priority,due_date,created_at,project_id) "
            "VALUES (?,?,?,?,?,?,?)",
            (plan_id, title, description, priority, due_date, now, project_id),
        )
    return _sync_plan_get(plan_id)


def _sync_plan_get(plan_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM work_plans WHERE id=?", (plan_id,)).fetchone()
        return dict(row) if row else None


def _sync_plan_list(status: str = "active") -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM work_plans WHERE status=? ORDER BY priority, created_at",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]


def _sync_plan_complete(plan_id: str) -> None:
    with _conn() as con:
        con.execute(
            "UPDATE work_plans SET status='completed', completed_at=? WHERE id=?",
            (time.time(), plan_id),
        )


def _sync_plan_delete(plan_id: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM work_plans WHERE id=?", (plan_id,))


# ── Async public API ──────────────────────────────────────────────

async def plan_create(
    title: str,
    description: str = "",
    priority: int = 2,
    due_date: float | None = None,
    project_id: str | None = None,
) -> dict:
    return await run_in_thread(_sync_plan_create, title, description, priority, due_date, project_id)


async def plan_get(plan_id: str) -> dict | None:
    return await run_in_thread(_sync_plan_get, plan_id)


async def plan_list(status: str = "active") -> list[dict]:
    return await run_in_thread(_sync_plan_list, status)


async def plan_complete(plan_id: str) -> None:
    return await run_in_thread(_sync_plan_complete, plan_id)


async def plan_delete(plan_id: str) -> None:
    return await run_in_thread(_sync_plan_delete, plan_id)
