"""/schedule komutu — cron/loop/schedule yönetimi.

Alt komutlar:
  /schedule                        → aktif job listesi
  /schedule ekle <cron> <açıklama> → yeni cron job (Bridge'e prompt gönderir)
  /schedule mesaj <cron> <metin>   → yeni cron job (sabit metin gönderir)
  /schedule tarama <cron> <tip> <proje> [--no-review] → scanner cron job
  /schedule backlog <cron> <proje> [prefix] [max]      → backlog executor cron job
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
    usage       = "/schedule [ekle|mesaj|tarama|backlog|sil|durdur|başlat ...]"

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
        elif sub in ("scan", "tarama"):
            await self._add_scanner(sender, rest, lang, _send)
        elif sub == "backlog":
            await self._add_backlog(sender, rest, lang, _send)
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
            _TIP_ICONS = {
                "run_bridge": "💬",
                "send_message": "📢",
                "run_scan": "🔍",
                "run_scanner": "🔍",
                "run_backlog_executor": "🛠",
            }
            tip     = _TIP_ICONS.get(j.get("action_type", ""), "⚙️")
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

    @staticmethod
    async def _add_scanner(sender: str, rest: str, lang: str, send_text) -> None:
        from ...features.scheduler import add_cron_job, _parse_cron
        from ...store import sqlite_store as db
        from ...i18n import t

        parts = rest.split()
        # Minimum: 5 cron fields + scan_type + project_id = 7 parts
        if len(parts) < 7:
            await send_text(sender, t("schedule.scanner_format_error", lang))
            return

        cron_expr  = " ".join(parts[:5])
        scan_type  = parts[5]
        project_id = parts[6]
        auto_review = "--no-review" not in parts

        try:
            _parse_cron(cron_expr)
        except ValueError as e:
            await send_text(sender, t("schedule.cron_error", lang, error=e))
            return

        # Validate scan_type exists
        from ...features.scan_pipeline.config_loader import ScanConfigLoader
        available = ScanConfigLoader().list_available()
        if scan_type not in available:
            await send_text(sender, t("schedule.scanner_invalid_type", lang, type=scan_type, available=", ".join(available)))
            return

        payload = {"scan_type": scan_type, "project_id": project_id, "auto_review": auto_review}
        description = f"Tarama: {scan_type} → {project_id}" + ("" if auto_review else " (no-review)")

        task = await db.task_create(
            description=description,
            action_type="run_scanner",
            action_payload=payload,
            cron_expr=cron_expr,
        )
        await add_cron_job(task["id"], cron_expr, description, "run_scanner", payload)
        await send_text(sender, t("schedule.scanner_add_ok", lang,
            id=task["id"][:6], cron=cron_expr, scan_type=scan_type,
            project_id=project_id, auto_review="✅" if auto_review else "❌"))

    @staticmethod
    async def _add_backlog(sender: str, rest: str, lang: str, send_text) -> None:
        from ...features.scheduler import add_cron_job, _parse_cron
        from ...store import sqlite_store as db
        from ...i18n import t

        parts = rest.split()
        # Minimum: 5 cron fields + project_id = 6 parts
        if len(parts) < 6:
            await send_text(sender, t("schedule.backlog_format_error", lang))
            return

        cron_expr  = " ".join(parts[:5])
        project_id = parts[5]
        prefix     = parts[6] if len(parts) > 6 else ""
        max_items  = int(parts[7]) if len(parts) > 7 and parts[7].isdigit() else 3

        try:
            _parse_cron(cron_expr)
        except ValueError as e:
            await send_text(sender, t("schedule.cron_error", lang, error=e))
            return

        payload = {"project_id": project_id, "prefix": prefix, "max_items": max_items, "parallel": 2}
        prefix_label = f" [{prefix}]" if prefix else ""
        description = f"Backlog executor: {project_id}{prefix_label} max={max_items}"

        task = await db.task_create(
            description=description,
            action_type="run_backlog_executor",
            action_payload=payload,
            cron_expr=cron_expr,
        )
        await add_cron_job(task["id"], cron_expr, description, "run_backlog_executor", payload)
        await send_text(sender, t("schedule.backlog_add_ok", lang,
            id=task["id"][:6], cron=cron_expr, project_id=project_id,
            prefix=prefix or "tümü", max_items=max_items))


registry.register(ScheduleCommand())
