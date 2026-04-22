"""Konuşma geçmişi özelliği — sorgulama ve formatlama (SRP).

Veri: store/sqlite_store.py (messages, session_summaries, bridge_calls)
Bu modül: WhatsApp formatında sunum + session özet tetikleyici
"""
from __future__ import annotations

import logging
import time

from ..store import sqlite_store as db
from ..store.message_logger import save_session_summary
from ..i18n import t

logger = logging.getLogger(__name__)


async def get_recent_messages(sender: str, limit: int = 20) -> list[dict]:
    return await db.message_list(sender, limit=limit)


async def get_session_summaries(sender: str, limit: int = 10) -> list[dict]:
    return await db.session_summaries_list(sender, limit=limit)


async def get_bridge_calls(sender: str, limit: int = 10) -> list[dict]:
    return await db.bridge_calls_list(sender, limit=limit)


def format_history(messages: list[dict], lang: str = "tr") -> str:
    """Son mesajları WhatsApp mesajı olarak formatla."""
    if not messages:
        return t("history.empty", lang)

    lines = [t("history.header", lang, count=len(messages))]
    for m in reversed(messages):   # Eskiden yeniye sıra
        dt = _fmt_ts(m["ts"])
        arrow = "📥" if m["direction"] == "in" else "📤"
        preview = (m["content"] or f"[{m['msg_type']}]")[:80]
        if m.get("media_id"):
            preview += f" 📎"
        lines.append(f"{arrow} {dt}: {preview}")
    return "\n".join(lines)


def format_summaries(summaries: list[dict], lang: str = "tr") -> str:
    """Session özetlerini WhatsApp mesajı olarak formatla."""
    if not summaries:
        return t("history.summaries_empty", lang)

    lines = [t("history.summaries_header", lang)]
    for s in summaries:
        start = _fmt_ts(s["started_at"])
        end   = _fmt_ts(s["ended_at"])
        ctx   = s["context_id"]
        cnt   = s["msg_count"]
        lines.append(f"\n📅 {start} → {end} | {ctx} | {cnt} mesaj")
        if s.get("summary"):
            for line in s["summary"].split("\n")[:3]:
                lines.append(f"  {line}")
    return "\n".join(lines)


def end_session(sender: str, session: dict) -> None:
    """Session sıfırlanmadan önce özet kaydet.

    whatsapp_router veya session.py tarafından çağrılır.
    """
    started_at = session.get("started_at", time.time())
    context_id = session.get("active_context", "main")
    save_session_summary(
        sender=sender,
        context_id=context_id,
        started_at=started_at,
        ended_at=time.time(),
    )
    logger.info("end_session: sender=%s context=%s", sender, context_id)


def _fmt_ts(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
