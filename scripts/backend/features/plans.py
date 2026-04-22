"""İş planları özelliği — CRUD ve WhatsApp formatları (SRP).

Veri erişimi: store/sqlite_store.py
Bu modül: iş mantığı + WhatsApp mesaj formatları
"""
from __future__ import annotations

from ..store.sqlite_wrapper import store as db  # REFAC-16: StoreProtocol uyumlu wrapper
from ..i18n import t

_PRIORITY_EMOJI = {1: "⭐", 2: "🔵", 3: "🟢"}
_PRIORITY_LABEL = {1: "Yüksek", 2: "Orta", 3: "Düşük"}


async def create_plan(title: str, description: str = "", priority: int = 2,
                      due_date: float | None = None, project_id: str | None = None) -> dict:
    return await db.plan_create(title, description, priority, due_date, project_id)


async def list_plans(status: str = "active") -> list[dict]:
    return await db.plan_list(status)


async def complete_plan(plan_id: str) -> None:
    await db.plan_complete(plan_id)


async def delete_plan(plan_id: str) -> None:
    await db.plan_delete(plan_id)


def format_plan_list(plans: list[dict], lang: str = "tr") -> str:
    """WhatsApp mesaj formatında iş planı listesi."""
    if not plans:
        return t("plan.empty", lang)
    lines = [t("plan.list_header", lang, count=len(plans))]
    for i, p in enumerate(plans, 1):
        emoji = _PRIORITY_EMOJI.get(p["priority"], "🔵")
        due = f" — {_format_date(p['due_date'])}" if p.get("due_date") else ""
        lines.append(f"{i}. {emoji} {p['title']}{due}")
    return "\n".join(lines)


def _format_date(ts: float | None) -> str:
    if not ts:
        return ""
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
