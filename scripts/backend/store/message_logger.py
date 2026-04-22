"""Mesaj loglama servisi — tüm mesajlar ve Bridge çağrıları kalıcı (SRP).

Bu modül yalnızca loglama yapar; iş mantığı taşımaz.
Hiçbir kayıt silinmez — veri kaybı yoktur.
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from . import sqlite_store as db

logger = logging.getLogger(__name__)


def _mask_phone(phone: str) -> str:
    """Telefon numarasının ortasını maskele: 905301083815 → 9053****3815"""
    s = str(phone)
    if len(s) > 8:
        return s[:4] + "****" + s[-4:]
    return "***"


def log_inbound(
    msg_id: str,
    sender: str,
    msg_type: str,
    content: str = "",
    media_id: str | None = None,
    media_path: str | None = None,
    mime_type: str | None = None,
    context_id: str = "main",
    raw_payload: dict | None = None,
) -> None:
    """Gelen WhatsApp mesajını kaydet."""
    raw_json = json.dumps(raw_payload or {}, ensure_ascii=False)
    db._sync_message_log(
        msg_id=msg_id,
        direction="in",
        sender=sender,
        msg_type=msg_type,
        content=content,
        media_id=media_id,
        media_path=media_path,
        mime_type=mime_type,
        context_id=context_id,
        raw_json=raw_json,
    )
    logger.info(
        "MSG_IN sender=%s type=%s context=%s media_id=%s len=%d",
        _mask_phone(sender), msg_type, context_id, media_id or "-", len(content),
    )


def log_outbound(
    sender: str,
    msg_type: str,
    content: str = "",
    context_id: str = "main",
    msg_id: str | None = None,
) -> None:
    """Gönderilen WhatsApp mesajını kaydet."""
    db._sync_message_log(
        msg_id=msg_id or f"out_{uuid.uuid4()}",
        direction="out",
        sender=sender,
        msg_type=msg_type,
        content=content,
        context_id=context_id,
    )
    logger.info(
        "MSG_OUT sender=%s type=%s context=%s len=%d",
        _mask_phone(sender), msg_type, context_id, len(content),
    )


def log_bridge_call(
    sender: str,
    session_id: str,
    prompt: str,
    response: str = "",
    latency_ms: int = 0,
    success: bool = True,
    error_msg: str = "",
) -> None:
    """Bridge çağrısını kaydet."""
    db._sync_bridge_call_log(
        sender=sender,
        session_id=session_id,
        prompt=prompt[:5000],     # Prompt çok uzunsa kırp (forensik için yeterli)
        response=response[:10000],
        latency_ms=latency_ms,
        success=success,
        error_msg=error_msg,
    )
    status = "OK" if success else f"ERR:{error_msg[:60]}"
    logger.info(
        "BRIDGE sender=%s session=%s latency=%dms status=%s",
        _mask_phone(sender), session_id, latency_ms, status,
    )


def save_session_summary(
    sender: str,
    context_id: str,
    started_at: float,
    ended_at: float | None = None,
) -> dict:
    """Oturum kapandığında özet kaydet."""
    ended_at = ended_at or time.time()
    # Session içindeki mesaj sayısı (tüm zamanlardaki değil)
    msg_count = db._sync_message_count_since(sender, started_at)

    # Session içindeki son 5 mesajdan özet oluştur (R4: tüm zamanlar değil, session başından itibaren)
    recent = db._sync_message_list(sender, limit=5, since=started_at)
    lines = []
    for m in reversed(recent):
        direction = "→" if m["direction"] == "in" else "←"
        ts_str = _fmt_ts(m["ts"])
        preview = (m["content"] or f"[{m['msg_type']}]")[:60]
        lines.append(f"{ts_str} {direction} {preview}")
    summary = "\n".join(lines) if lines else "(mesaj yok)"

    record = db._sync_session_summary_save(
        sender=sender,
        context_id=context_id,
        started_at=started_at,
        ended_at=ended_at,
        msg_count=msg_count,
        summary=summary,
    )
    logger.info(
        "SESSION_END sender=%s context=%s msgs=%d duration=%.0fs",
        _mask_phone(sender), context_id, msg_count, ended_at - started_at,
    )
    return record


def _fmt_ts(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%d.%m %H:%M")
