"""/schedule komutu — cron/loop/schedule yönetimi.

Alt komutlar:
  /schedule                        → aktif job listesi
  /schedule ekle <cron> <açıklama> → yeni cron job (Bridge'e prompt gönderir)
  /schedule mesaj <cron> <metin>   → yeni cron job (sabit metin gönderir)
  /schedule sil <id_prefix>        → job'ı kalıcı sil
  /schedule durdur <id_prefix>     → job'ı duraklat
  /schedule başlat <id_prefix>     → duraklatılmış job'ı devam ettir

Cron formatı (5 alan):
  dakika saat gün ay haftanın-günü
  ör: "0 9 * * *"   → her sabah 09:00
      "0 9 * * 1"   → her pazartesi 09:00
      "*/30 * * * *" → her 30 dakika
      "0 */2 * * *"  → her 2 saatte bir

Doğal dil ile oluşturma:
  WhatsApp'tan "Her sabah 9'da günlük brief hazırla" yazarsın →
  Claude bunu anlar ve POST /agent/schedule endpoint'ini çağırır.
"""
from __future__ import annotations

from .registry import registry
from ..permission import Perm


class ScheduleCommand:
    cmd_id      = "/schedule"
    perm        = Perm.OWNER
    button_id   = "cmd_schedule_list"
    label       = "Zamanlama Yönetimi"
    description = "Tekrarlayan görevler oluşturur, listeler, durdurur veya siler."
    usage       = "/schedule [ekle <cron> <açıklama> | sil | durdur | başlat <id>]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger

        from ...i18n import t
        lang  = session.get("lang", "tr")
        parts = arg.strip().split(None, 1)
        sub   = parts[0].lower() if parts else ""
        rest  = parts[1] if len(parts) > 1 else ""
        _send = get_messenger().send_text

        if sub in ("", "listele", "list"):
            await self._list(sender, lang, _send)
        elif sub == "ekle":
            await self._add(sender, rest, "run_bridge", lang, _send)
        elif sub == "mesaj":
            await self._add(sender, rest, "send_message", lang, _send)
        elif sub == "sil":
            await self._remove(sender, rest.strip(), lang, _send)
        elif sub in ("durdur", "pause"):
            await self._pause(sender, rest.strip(), lang, _send)
        elif sub in ("başlat", "devam", "resume"):
            await self._resume(sender, rest.strip(), lang, _send)
        else:
            await _send(sender, t("schedule.usage", lang))

    # ── Alt komutlar ──────────────────────────────────────────────

    @staticmethod
    async def _list(sender: str, lang: str, send_text) -> None:
        from ...features.scheduler import list_cron_jobs
        from ...i18n import t

        jobs = list_cron_jobs()
        if not jobs:
            await send_text(sender, t("schedule.empty", lang))
            return

        lines = [t("schedule.list_header", lang) + "\n"]
        for j in jobs:
            status  = "✅" if j.get("active") else "⏸"
            short   = j["id"][:6]
            cron    = j.get("cron_expr") or t("schedule.one_time", lang)
            tip     = "💬" if j.get("action_type") == "run_bridge" else "📢"
            nxt     = j.get("next_run_time", "")[:16].replace("T", " ") if j.get("next_run_time") else "—"
            lines.append(f"{status} {tip} `{short}` [{cron}]\n   {j['description']}\n   {t('schedule.next_run_label', lang)}: {nxt}")

        lines.append("\n" + t("schedule.list_footer", lang))
        await send_text(sender, "\n".join(lines))

    @staticmethod
    async def _add(sender: str, rest: str, action_type: str, lang: str, send_text) -> None:
        from ...features.scheduler import add_cron_job
        from ...store import sqlite_store as db
        from ...i18n import t

        # Format: "<cron_5_alan> <açıklama>"  — cron 5 boşluklu alan
        parts = rest.split(None, 5)
        if len(parts) < 6:
            await send_text(sender, t("schedule.add_format_error", lang))
            return

        cron_expr   = " ".join(parts[:5])
        description = parts[5]

        # Cron geçerliliğini kontrol et
        try:
            from ...features.scheduler import _parse_cron
            _parse_cron(cron_expr)
        except ValueError as e:
            await send_text(sender, t("schedule.cron_error", lang, error=e))
            return

        task    = await db.task_create(
            description  = description,
            action_type  = action_type,
            action_payload = {"message": description},
            cron_expr    = cron_expr,
        )
        # task_create farklı id üretir — job'ı o id ile ekle
        await add_cron_job(task["id"], cron_expr, description, action_type, {"message": description})

        tip_label = t("schedule.tip_bridge" if action_type == "run_bridge" else "schedule.tip_message", lang)
        await send_text(
            sender,
            t("schedule.add_ok", lang, id=task["id"][:6], cron=cron_expr, tip=tip_label, desc=description),
        )

    @staticmethod
    async def _remove(sender: str, prefix: str, lang: str, send_text) -> None:
        from ...i18n import t
        if not prefix:
            await send_text(sender, t("schedule.remove_usage", lang))
            return

        from ...store import sqlite_store as db
        from ...features.scheduler import remove_cron_job

        task = await db.task_find_by_prefix(prefix)
        if not task:
            await send_text(sender, t("schedule.not_found", lang, prefix=prefix))
            return

        remove_cron_job(task["id"])
        await send_text(sender, t("schedule.remove_ok", lang, id=task["id"][:6], desc=task["description"]))

    @staticmethod
    async def _pause(sender: str, prefix: str, lang: str, send_text) -> None:
        from ...i18n import t
        if not prefix:
            await send_text(sender, t("schedule.pause_usage", lang))
            return

        from ...store import sqlite_store as db
        from ...features.scheduler import pause_cron_job

        task = await db.task_find_by_prefix(prefix)
        if not task:
            await send_text(sender, t("schedule.not_found", lang, prefix=prefix))
            return

        pause_cron_job(task["id"])
        await send_text(sender, t("schedule.pause_ok", lang, id=task["id"][:6], desc=task["description"]))

    @staticmethod
    async def _resume(sender: str, prefix: str, lang: str, send_text) -> None:
        from ...i18n import t
        if not prefix:
            await send_text(sender, t("schedule.resume_usage", lang))
            return

        from ...store import sqlite_store as db
        from ...features.scheduler import resume_cron_job

        task = await db.task_find_by_prefix(prefix)
        if not task:
            await send_text(sender, t("schedule.not_found", lang, prefix=prefix))
            return

        resume_cron_job(task["id"])
        await send_text(sender, t("schedule.resume_ok", lang, id=task["id"][:6], desc=task["description"]))


registry.register(ScheduleCommand())
