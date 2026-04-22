"""Takvim özelliği — etkinlik yönetimi ve hatırlatıcı tetikleyici (SRP).

Veri: store/sqlite_store.py
Zamanlama: scheduler.py
Bu modül: iş mantığı + NLP tarih parse + WhatsApp format
"""
from __future__ import annotations

import logging
import time

from ..store.sqlite_wrapper import store as db  # REFAC-16: StoreProtocol uyumlu wrapper

logger = logging.getLogger(__name__)


async def create_event(title: str, event_time: float, description: str = "",
                       remind_before_minutes: int = 30, recurring: str | None = None) -> dict:
    return await db.event_create(title, event_time, description, remind_before_minutes, recurring)


async def list_upcoming(limit: int = 10) -> list[dict]:
    return await db.event_list_upcoming(limit)


async def delete_event(event_id: str) -> None:
    await db.event_delete(event_id)


def parse_datetime_from_text(text: str) -> float | None:
    """Türkçe doğal dil ifadesinden Unix timestamp parse et.

    Önce dateparser dener, başarısız olunca None döner (Bridge'e düşer).
    """
    try:
        import dateparser
        dt = dateparser.parse(
            text,
            languages=["tr", "en"],
            settings={"PREFER_DATES_FROM": "future", "RETURN_AS_TIMEZONE_AWARE": False},
        )
        if dt:
            return dt.timestamp()
    except Exception as e:
        logger.warning("dateparser hatası: %s", e)
    return None


def format_event_list(events: list[dict], lang: str = "tr") -> str:
    """WhatsApp mesaj formatında takvim listesi."""
    from ..i18n import t
    if not events:
        return t("calendar.empty", lang)
    lines = [t("calendar.list_header", lang)]
    for e in events:
        dt = _format_ts(e["event_time"])
        lines.append(f"• {e['title']} — {dt}")
    return "\n".join(lines)


def _format_ts(ts: float) -> str:
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")


async def check_and_notify_reminders(send_fn, lang: str = "tr") -> None:
    """Hatırlatma zamanı gelmiş etkinlikleri bildir. Scheduler tarafından çağrılır."""
    from ..i18n import t
    due = await db.events_due_for_reminder()
    for event in due:
        msg = t("calendar.reminder", lang, title=event["title"], time=_format_ts(event["event_time"]))
        try:
            await send_fn(msg)
            await db.event_mark_notified(event["id"])
        except Exception as e:
            logger.error("Hatırlatıcı gönderilemedi: %s", e)
