"""Calendar Events repository — calendar_events tablosu için veri erişimi (SRP)."""
from __future__ import annotations

import time

from ._thread_runner import run_in_thread
import uuid

from .._connection import _conn


def _sync_event_create(title: str, event_time: float, description: str = "",
                       remind_before_minutes: int = 30, recurring: str | None = None) -> dict:
    event_id = str(uuid.uuid4())
    now = time.time()
    with _conn() as con:
        con.execute(
            "INSERT INTO calendar_events "
            "(id,title,description,event_time,remind_before_minutes,recurring,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (event_id, title, description, event_time, remind_before_minutes, recurring, now),
        )
    return _sync_event_get(event_id)


def _sync_event_get(event_id: str) -> dict | None:
    with _conn() as con:
        row = con.execute("SELECT * FROM calendar_events WHERE id=?", (event_id,)).fetchone()
        return dict(row) if row else None


def _sync_event_list_upcoming(limit: int = 10) -> list[dict]:
    now = time.time()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM calendar_events WHERE event_time > ? ORDER BY event_time LIMIT ?",
            (now, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def _sync_event_mark_notified(event_id: str) -> None:
    with _conn() as con:
        con.execute("UPDATE calendar_events SET notified=1 WHERE id=?", (event_id,))


def _sync_event_delete(event_id: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM calendar_events WHERE id=?", (event_id,))


def _sync_events_due_for_reminder() -> list[dict]:
    """Hatırlatma zamanı gelmiş, henüz bildirilmemiş etkinlikleri döndür."""
    now = time.time()
    with _conn() as con:
        rows = con.execute(
            """SELECT * FROM calendar_events
               WHERE notified=0
               AND (event_time - remind_before_minutes * 60) <= ?
               AND event_time > ?""",
            (now, now - 60),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Async public API ──────────────────────────────────────────────

async def event_create(
    title: str,
    event_time: float,
    description: str = "",
    remind_before_minutes: int = 30,
    recurring: str | None = None,
) -> dict:
    return await run_in_thread(
        _sync_event_create, title, event_time, description, remind_before_minutes, recurring
    )


async def event_get(event_id: str) -> dict | None:
    return await run_in_thread(_sync_event_get, event_id)


async def event_list_upcoming(limit: int = 10) -> list[dict]:
    return await run_in_thread(_sync_event_list_upcoming, limit)


async def event_mark_notified(event_id: str) -> None:
    return await run_in_thread(_sync_event_mark_notified, event_id)


async def event_delete(event_id: str) -> None:
    return await run_in_thread(_sync_event_delete, event_id)


async def events_due_for_reminder() -> list[dict]:
    return await run_in_thread(_sync_events_due_for_reminder)
