"""!root-check komutu — son request ve root işlem zamanlarını özet olarak göster."""
from __future__ import annotations

import asyncio
import datetime
import time as _time

from .registry import registry
from ..permission import Perm


def _fmt_time(ts: float) -> str:
    """Unix timestamp → HH:MM formatı (yerel saat)."""
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M")


def _fmt_time_detailed(ts: float) -> str:
    """Unix timestamp → HH:MM:SS formatı."""
    return datetime.datetime.fromtimestamp(ts).strftime("%H:%M:%S")


def _fmt_duration(delta_sec: float) -> str:
    """Saniye → insan okunur format (dakika, saat vb)."""
    if delta_sec < 60:
        return f"{int(delta_sec)}s"
    elif delta_sec < 3600:
        return f"{int(delta_sec / 60)}m"
    else:
        return f"{int(delta_sec / 3600)}h"


def _sync_get_summary() -> dict:
    """Son request ve bridge call bilgilerini DB'den çek."""
    from ...store._connection import _conn  # type: ignore[attr-defined]

    with _conn() as con:
        last_in = con.execute(
            "SELECT ts, content, msg_type FROM messages"
            " WHERE direction='in' ORDER BY ts DESC LIMIT 1"
        ).fetchone()

        last_bridge = con.execute(
            "SELECT ts, success FROM bridge_calls ORDER BY ts DESC LIMIT 1"
        ).fetchone()

        last_out = con.execute(
            "SELECT ts FROM messages WHERE direction='out' ORDER BY ts DESC LIMIT 1"
        ).fetchone()

    return {
        "last_in":     dict(last_in)     if last_in     else None,
        "last_bridge": dict(last_bridge) if last_bridge else None,
        "last_out":    dict(last_out)    if last_out    else None,
    }


class RootCheckCommand:
    cmd_id      = "!root-check"
    perm        = Perm.OWNER
    label       = "Root Durum Özeti"
    description = "Son request ve root işlem zamanlarını insan okunur formatta gösterir."
    usage       = "!root-check"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        lang = session.get("lang", "tr")

        try:
            data = await asyncio.to_thread(_sync_get_summary)
        except Exception as e:
            await get_messenger().send_text(sender, t("root_check.error", lang, error=e))
            return

        last_in     = data["last_in"]
        last_bridge = data["last_bridge"]
        last_out    = data["last_out"]

        if not last_in and not last_bridge:
            await get_messenger().send_text(sender, t("root_check.no_data", lang))
            return

        # Zaman bilgileri
        now = _time.time()
        in_time = _fmt_time(last_in["ts"]) if last_in else "—"
        in_ago = _fmt_duration(now - last_in["ts"]) if last_in else "—"

        # Root'un son işlemi: bridge call veya outbound mesaj — hangisi daha yeni
        root_ts: float | None = None
        root_type: str = ""
        if last_bridge:
            root_ts = last_bridge["ts"]
            root_type = "🌉 Bridge" if last_bridge.get("success") else "🌉 Bridge (❌)"
        if last_out and (root_ts is None or last_out["ts"] > root_ts):
            root_ts = last_out["ts"]
            root_type = "📤 Çıktı"

        root_time = _fmt_time(root_ts) if root_ts else "—"
        root_ago = _fmt_duration(now - root_ts) if root_ts else "—"

        # Süreç devam ediyor mu?
        ongoing = False
        if last_in and last_bridge and last_in["ts"] > last_bridge["ts"]:
            ongoing = True
        if last_bridge and (now - last_bridge["ts"]) < 300:
            ongoing = True

        status_emoji = "🟢" if ongoing else "⚫"
        status_text = t("root_check.ongoing", lang) if ongoing else t("root_check.idle", lang)

        # Request content preview (ilk 100 karakter)
        content_preview = ""
        if last_in and last_in.get("content"):
            content = last_in["content"][:100].replace("\n", " ")
            if len(str(last_in.get("content", ""))) > 100:
                content += "…"
            content_preview = f"\n💬 Son istek: {content}"

        msg = f"""📊 **Root Durum Özeti**

⏰ Son gelen istek: {in_time} ({in_ago} önce){content_preview}
{root_type}: {root_time} ({root_ago} önce)
{status_emoji} Durum: {status_text}"""

        await get_messenger().send_text(sender, msg)


registry.register(RootCheckCommand())
