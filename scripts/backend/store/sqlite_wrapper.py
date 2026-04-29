"""SqliteStoreWrapper — sqlite_store modülünü StoreProtocol'e uyumlu sınıfa sarar.

DIP-1: Feature fonksiyonlarına `db: StoreProtocol` inject etmek için kullanılır.
Singleton `store` bu modülden import edilir.

Kullanım (feature veya test kodu):
    from ..store.sqlite_wrapper import store   # production singleton

    # Test izolasyonu:
    from ..store.protocol import StoreProtocol
    class MockStore:
        async def project_list(self) -> list[dict]: return []
        ...
    result = await some_feature(db=MockStore())
"""
from __future__ import annotations

from . import sqlite_store as _db
from .protocol import (  # noqa: F401 — re-export
    StoreProtocol,
    ProjectStoreProtocol,
    PlanStoreProtocol,
    EventStoreProtocol,
    TaskStoreProtocol,
    MessageStoreProtocol,
    SessionStoreProtocol,
    BridgeStoreProtocol,
    TotpStoreProtocol,
    DedupStoreProtocol,
)


class SqliteStoreWrapper:
    """sqlite_store modülündeki async fonksiyonları örnek metotları olarak sunar.

    Yeni bir metot eklendiğinde:
      1. sqlite_store.py'e async fonksiyon ekle (asıl iş orada)
      2. Burada wrapper metodu ekle (tek satır delegation)
      3. protocol.py'e imzayı ekle
    """

    # ── Proje ────────────────────────────────────────────────────────

    async def project_create(
        self,
        name: str,
        description: str = "",
        source_pdf: str | None = None,
        metadata: str = "{}",
        path: str | None = None,
    ) -> dict:
        return await _db.project_create(name, description, source_pdf, metadata, path)

    async def project_get(self, project_id: str) -> dict | None:
        return await _db.project_get(project_id)

    async def project_list(self) -> list[dict]:
        return await _db.project_list()

    async def project_update_status(self, project_id: str, status: str) -> None:
        return await _db.project_update_status(project_id, status)

    async def project_delete(self, project_id: str) -> bool:
        return await _db.project_delete(project_id)

    # ── İş planı ─────────────────────────────────────────────────────

    async def plan_create(
        self,
        title: str,
        description: str = "",
        priority: int = 2,
        due_date: float | None = None,
        project_id: str | None = None,
    ) -> dict:
        return await _db.plan_create(title, description, priority, due_date, project_id)

    async def plan_get(self, plan_id: str) -> dict | None:
        return await _db.plan_get(plan_id)

    async def plan_list(self, status: str = "active") -> list[dict]:
        return await _db.plan_list(status)

    async def plan_complete(self, plan_id: str) -> None:
        return await _db.plan_complete(plan_id)

    async def plan_delete(self, plan_id: str) -> None:
        return await _db.plan_delete(plan_id)

    # ── Takvim ───────────────────────────────────────────────────────

    async def event_create(
        self,
        title: str,
        event_time: float,
        description: str = "",
        remind_before_minutes: int = 30,
        recurring: str | None = None,
    ) -> dict:
        return await _db.event_create(
            title, event_time, description, remind_before_minutes, recurring
        )

    async def event_get(self, event_id: str) -> dict | None:
        return await _db.event_get(event_id)

    async def event_list_upcoming(self, limit: int = 10) -> list[dict]:
        return await _db.event_list_upcoming(limit)

    async def event_mark_notified(self, event_id: str) -> None:
        return await _db.event_mark_notified(event_id)

    async def event_delete(self, event_id: str) -> None:
        return await _db.event_delete(event_id)

    async def events_due_for_reminder(self) -> list[dict]:
        return await _db.events_due_for_reminder()

    # ── Zamanlanmış görev ─────────────────────────────────────────────

    async def task_create(
        self,
        description: str,
        action_type: str,
        action_payload: dict,
        cron_expr: str | None = None,
        next_run: float | None = None,
    ) -> dict:
        return await _db.task_create(
            description, action_type, action_payload, cron_expr, next_run
        )

    async def task_get(self, task_id: str) -> dict | None:
        return await _db.task_get(task_id)

    async def task_list_active(self) -> list[dict]:
        return await _db.task_list_active()

    async def task_list_all(self) -> list[dict]:
        return await _db.task_list_all()

    async def task_find_by_prefix(self, prefix: str) -> dict | None:
        return await _db.task_find_by_prefix(prefix)

    async def task_deactivate(self, task_id: str) -> None:
        return await _db.task_deactivate(task_id)

    async def task_activate(self, task_id: str) -> None:
        return await _db.task_activate(task_id)

    async def task_delete(self, task_id: str) -> None:
        return await _db.task_delete(task_id)

    async def task_update_last_run(self, task_id: str) -> None:
        return await _db.task_update_last_run(task_id)

    # ── Mesaj geçmişi ─────────────────────────────────────────────────

    async def message_log(
        self,
        msg_id: str,
        direction: str,
        sender: str,
        msg_type: str,
        content: str = "",
        media_id: str | None = None,
        media_path: str | None = None,
        mime_type: str | None = None,
        context_id: str = "main",
        raw_json: str = "{}",
    ) -> None:
        return await _db.message_log(
            msg_id, direction, sender, msg_type,
            content, media_id, media_path, mime_type, context_id, raw_json,
        )

    async def message_list(
        self, sender: str, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        return await _db.message_list(sender, limit, offset)

    async def message_count(self, sender: str) -> int:
        return await _db.message_count(sender)

    # ── Oturum özeti ──────────────────────────────────────────────────

    async def session_summary_save(
        self,
        sender: str,
        context_id: str,
        started_at: float,
        ended_at: float,
        msg_count: int,
        summary: str = "",
    ) -> dict:
        return await _db.session_summary_save(
            sender, context_id, started_at, ended_at, msg_count, summary
        )

    async def session_summaries_list(self, sender: str, limit: int = 20) -> list[dict]:
        return await _db.session_summaries_list(sender, limit)

    # ── Bridge çağrı logu ─────────────────────────────────────────────

    async def bridge_call_log(
        self,
        sender: str,
        session_id: str,
        prompt: str,
        response: str = "",
        latency_ms: int = 0,
        success: bool = True,
        error_msg: str = "",
    ) -> None:
        return await _db.bridge_call_log(
            sender, session_id, prompt, response, latency_ms, success, error_msg
        )

    async def bridge_calls_list(self, sender: str, limit: int = 20) -> list[dict]:
        return await _db.bridge_calls_list(sender, limit)

    # ── TOTP kilit ────────────────────────────────────────────────────

    async def totp_get_lockout(
        self, sender: str, totp_type: str
    ) -> tuple[int, float]:
        return await _db.totp_get_lockout(sender, totp_type)

    async def totp_record_failure(
        self,
        sender: str,
        totp_type: str,
        lockout_duration: float = 900.0,
    ) -> tuple[int, float]:
        return await _db.totp_record_failure(sender, totp_type, lockout_duration)

    async def totp_reset_lockout(self, sender: str, totp_type: str) -> None:
        return await _db.totp_reset_lockout(sender, totp_type)

    # ── Dedup ─────────────────────────────────────────────────────────

    async def dedup_is_seen(
        self, message_id: str, now: float, ttl: float = 300.0
    ) -> bool:
        return await _db.dedup_is_seen(message_id, now, ttl)

    async def dedup_load_recent(self, ttl: float = 300.0) -> set[str]:
        return await _db.dedup_load_recent(ttl)


# Production singleton — feature fonksiyonları bunu import eder
store: StoreProtocol = SqliteStoreWrapper()
