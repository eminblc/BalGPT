"""Store arayüz sözleşmesi — DIP-1 + ISP (SOLID-v2-7).

DIP-1: Feature modülleri bu Protocol'e bağımlıdır; concrete implementasyon (SQLite,
PostgreSQL, in-memory mock) dışarıdan inject edilebilir. Yeni backend = yeni sınıf.
Mevcut feature koduna dokunulmaz.

ISP (SOLID-v2-7): Monolitik StoreProtocol, domain-spesifik sub-protocol'lere
bölünmüştür. Feature modülleri yalnızca ihtiyaç duydukları arayüze bağımlı olabilir:

    from ..store.protocol import PlanStoreProtocol

    async def list_plans(db: PlanStoreProtocol) -> list[dict]:
        return await db.plan_list()

Geriye uyumluluk: `StoreProtocol` tüm sub-protocol'lerden kalıtır — mevcut
`db: StoreProtocol` anotasyonları çalışmaya devam eder.

Test izolasyonu (dar arayüz):
    class FakePlanStore:
        async def plan_create(self, title, **kw) -> dict: return {"id": "x"}
        async def plan_list(self, status="active") -> list[dict]: return []
        async def plan_complete(self, plan_id) -> None: pass
        async def plan_delete(self, plan_id) -> None: pass
        async def plan_get(self, plan_id) -> dict | None: return None
    await list_plans(db=FakePlanStore())

NOT: sqlite_store modülü bu Protocol'ü *implicitly* karşılar — runtime_checkable
     olduğu için isinstance(sqlite_store_wrapper, StoreProtocol) True döner.
     Bkz. store/sqlite_wrapper.py → SqliteStoreWrapper.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


# ── Domain-spesifik sub-protocol'ler (ISP) ───────────────────────────


@runtime_checkable
class ProjectStoreProtocol(Protocol):
    """Proje CRUD arayüzü."""

    async def project_create(
        self,
        name: str,
        description: str = ...,
        source_pdf: str | None = ...,
        metadata: str = ...,
        path: str | None = ...,
    ) -> dict: ...

    async def project_get(self, project_id: str) -> dict | None: ...

    async def project_list(self) -> list[dict]: ...

    async def project_update_status(self, project_id: str, status: str) -> None: ...

    async def project_delete(self, project_id: str) -> bool: ...


@runtime_checkable
class PlanStoreProtocol(Protocol):
    """İş planı CRUD arayüzü."""

    async def plan_create(
        self,
        title: str,
        description: str = ...,
        priority: int = ...,
        due_date: float | None = ...,
        project_id: str | None = ...,
    ) -> dict: ...

    async def plan_get(self, plan_id: str) -> dict | None: ...

    async def plan_list(self, status: str = ...) -> list[dict]: ...

    async def plan_complete(self, plan_id: str) -> None: ...

    async def plan_delete(self, plan_id: str) -> None: ...


@runtime_checkable
class EventStoreProtocol(Protocol):
    """Takvim etkinliği arayüzü."""

    async def event_create(
        self,
        title: str,
        event_time: float,
        description: str = ...,
        remind_before_minutes: int = ...,
        recurring: str | None = ...,
    ) -> dict: ...

    async def event_get(self, event_id: str) -> dict | None: ...

    async def event_list_upcoming(self, limit: int = ...) -> list[dict]: ...

    async def event_mark_notified(self, event_id: str) -> None: ...

    async def event_delete(self, event_id: str) -> None: ...

    async def events_due_for_reminder(self) -> list[dict]: ...


@runtime_checkable
class TaskStoreProtocol(Protocol):
    """Zamanlanmış görev arayüzü."""

    async def task_create(
        self,
        description: str,
        action_type: str,
        action_payload: dict,
        cron_expr: str | None = ...,
        next_run: float | None = ...,
    ) -> dict: ...

    async def task_get(self, task_id: str) -> dict | None: ...

    async def task_list_active(self) -> list[dict]: ...

    async def task_list_all(self) -> list[dict]: ...

    async def task_find_by_prefix(self, prefix: str) -> dict | None: ...

    async def task_deactivate(self, task_id: str) -> None: ...

    async def task_activate(self, task_id: str) -> None: ...

    async def task_delete(self, task_id: str) -> None: ...

    async def task_update_last_run(self, task_id: str) -> None: ...


@runtime_checkable
class MessageStoreProtocol(Protocol):
    """Mesaj geçmişi arayüzü."""

    async def message_log(
        self,
        msg_id: str,
        direction: str,
        sender: str,
        msg_type: str,
        content: str = ...,
        media_id: str | None = ...,
        media_path: str | None = ...,
        mime_type: str | None = ...,
        context_id: str = ...,
        raw_json: str = ...,
    ) -> None: ...

    async def message_list(
        self, sender: str, limit: int = ..., offset: int = ...
    ) -> list[dict]: ...

    async def message_count(self, sender: str) -> int: ...


@runtime_checkable
class SessionStoreProtocol(Protocol):
    """Oturum özeti arayüzü."""

    async def session_summary_save(
        self,
        sender: str,
        context_id: str,
        started_at: float,
        ended_at: float,
        msg_count: int,
        summary: str = ...,
    ) -> dict: ...

    async def session_summaries_list(
        self, sender: str, limit: int = ...
    ) -> list[dict]: ...


@runtime_checkable
class BridgeStoreProtocol(Protocol):
    """Bridge çağrı logu arayüzü."""

    async def bridge_call_log(
        self,
        sender: str,
        session_id: str,
        prompt: str,
        response: str = ...,
        latency_ms: int = ...,
        success: bool = ...,
        error_msg: str = ...,
    ) -> None: ...

    async def bridge_calls_list(
        self, sender: str, limit: int = ...
    ) -> list[dict]: ...


@runtime_checkable
class TotpStoreProtocol(Protocol):
    """TOTP kilit arayüzü."""

    async def totp_get_lockout(
        self, sender: str, totp_type: str
    ) -> tuple[int, float]: ...

    async def totp_record_failure(
        self,
        sender: str,
        totp_type: str,
        lockout_duration: float = ...,
    ) -> tuple[int, float]: ...

    async def totp_reset_lockout(self, sender: str, totp_type: str) -> None: ...


@runtime_checkable
class DedupStoreProtocol(Protocol):
    """Dedup arayüzü."""

    async def dedup_is_seen(
        self, message_id: str, now: float, ttl: float = ...
    ) -> bool: ...

    async def dedup_load_recent(self, ttl: float = ...) -> set[str]: ...


@runtime_checkable
class TokenStatStoreProtocol(Protocol):
    """Token kullanım istatistikleri arayüzü."""

    async def token_add_usage(
        self,
        model_id: str,
        model_name: str,
        backend: str,
        input_tokens: int,
        output_tokens: int,
        session_id: str | None = ...,
        context: str = ...,
    ) -> None: ...

    async def token_get_summary(self, timespan_hours: int = ...) -> list[dict]: ...

    async def token_get_totals(self, timespan_hours: int = ...) -> dict: ...


# ── Birleşik Protocol (geriye uyumlu) ────────────────────────────────


@runtime_checkable
class StoreProtocol(
    ProjectStoreProtocol,
    PlanStoreProtocol,
    EventStoreProtocol,
    TaskStoreProtocol,
    MessageStoreProtocol,
    SessionStoreProtocol,
    BridgeStoreProtocol,
    TotpStoreProtocol,
    DedupStoreProtocol,
    TokenStatStoreProtocol,
    Protocol,
):
    """Tüm domain arayüzlerini birleştiren üst Protocol.

    Mevcut `db: StoreProtocol` anotasyonları çalışmaya devam eder.
    Yeni feature'lar dar arayüzleri (ör. PlanStoreProtocol) tercih etmeli.
    """

    ...
