"""/root-check komutu — bridge aktif bir istek işliyorsa göster, değilse boşta bildir."""
from __future__ import annotations

import asyncio
import datetime
import time as _time

from .registry import registry
from ..permission import Perm


def _fmt_time(ts: float) -> str:
    """Unix timestamp → HH:MM:SS formatı (yerel saat)."""
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _fmt_duration(delta_sec: float, lang: str) -> str:
    """Saniye → insan okunur format (i18n)."""
    from ...i18n import t
    if delta_sec < 60:
        return t("root_check.duration_sec", lang, n=int(delta_sec))
    if delta_sec < 3600:
        m = int(delta_sec / 60)
        s = int(delta_sec % 60)
        return t("root_check.duration_min", lang, m=m, s=s)
    h = int(delta_sec / 3600)
    m = int((delta_sec % 3600) / 60)
    return t("root_check.duration_hour", lang, h=h, m=m)


def _sync_get_summary() -> dict:
    """Son gelen istek ve son giden yanıt bilgilerini DB'den çek."""
    from ...store._connection import _conn  # type: ignore[attr-defined]

    with _conn() as con:
        last_in = con.execute(
            "SELECT ts, content, msg_type FROM messages"
            " WHERE direction='in' ORDER BY ts DESC LIMIT 1"
        ).fetchone()

        last_out = con.execute(
            "SELECT ts FROM messages WHERE direction='out' ORDER BY ts DESC LIMIT 1"
        ).fetchone()

    return {
        "last_in":  dict(last_in)  if last_in  else None,
        "last_out": dict(last_out) if last_out else None,
    }


class RootCheckCommand:
    cmd_id      = "/root-check"
    perm        = Perm.OWNER
    label       = "Root Durum Özeti"
    description = "Bridge aktif bir istek işliyorsa gösterir; boştaysa 'çalışmıyor' der."
    usage       = "/root-check"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        lang = session.get("lang", "tr")

        try:
            data = await asyncio.to_thread(_sync_get_summary)
        except Exception as e:
            await get_messenger().send_text(sender, t("root_check.error", lang, error=e))
            return

        last_in  = data["last_in"]
        last_out = data["last_out"]
        now = _time.time()

        in_ts  = last_in["ts"]  if last_in  else None
        out_ts = last_out["ts"] if last_out else None

        is_active = (
            in_ts is not None
            and (out_ts is None or in_ts > out_ts)
        )

        if not is_active:
            if in_ts:
                ago = _fmt_duration(now - in_ts, lang)
                msg = t("root_check.idle_with_history", lang, time=_fmt_time(in_ts), ago=ago)
            else:
                msg = t("root_check.idle_no_history", lang)
            await get_messenger().send_text(sender, msg)
            return

        duration = _fmt_duration(now - in_ts, lang)
        content  = (last_in.get("content") or "").strip()
        msg_type = last_in.get("msg_type", "text")

        lines = [
            t("root_check.active_header", lang, duration=duration),
            t("root_check.active_started", lang, time=_fmt_time(in_ts)),
            t("root_check.active_type", lang, msg_type=msg_type),
            "",
            t("root_check.active_request_label", lang),
            content if content else t("root_check.active_no_content", lang),
        ]
        await get_messenger().send_text(sender, "\n".join(lines))


registry.register(RootCheckCommand())
