"""/backlog komutu — BACKLOG executor'ı Telegram/WhatsApp'tan yönetir.

Alt komutlar:
  /backlog                           → proje seçim butonları göster
  /backlog run <proje> [prefix] [max] [parallel] → executor'ı başlat
  /backlog durum                     → son executor run'larını göster
  /backlog kuru <proje> [prefix]     → dry_run (BACKLOG'a yazma)
"""
from __future__ import annotations

import logging

from .registry import registry
from ..permission import Perm

log = logging.getLogger(__name__)


class BacklogCommand:
    """BACKLOG executor'ı başlatır ve durumunu gösterir."""

    cmd_id      = "/backlog"
    perm        = Perm.OWNER
    button_id   = "cmd_backlog"
    label       = "Backlog Executor"
    description = "BACKLOG item'larını otomatik implement eder."
    usage       = "/backlog [run <proje> [prefix] [max] [parallel] | durum | kuru <proje>]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        lang      = session.get("lang", "tr")
        messenger = get_messenger()
        parts     = arg.strip().split() if arg.strip() else []
        sub       = parts[0].lower() if parts else ""

        # /backlog → buton menüsü
        if not sub:
            from ._root_project_helpers import get_active_root_project
            root_project = get_active_root_project()

            if root_project:
                pid = root_project.get("id", "")
                buttons = [
                    {"id": f"backlog_run_{pid}", "title": t("backlog.btn_run", lang)},
                    {"id": "backlog_status",     "title": t("backlog.btn_status", lang)},
                ]
                await messenger.send_buttons(sender, t("backlog.select_action", lang), buttons)
            else:
                # Root project yok → 99-root onayı sor
                session["_pending_parallel"] = {
                    "cmd":              "backlog",
                    "_display_project": "99-root",
                    "_needs_root_confirm": True,
                    "params": {
                        "project_id": "",
                        "prefix":     "",
                        "max_items":  0,
                        "dry_run":    False,
                    },
                }
                await messenger.send_buttons(
                    sender,
                    t("noroot.confirm_ask", lang),
                    [
                        {"id": "noroot_y", "title": t("noroot.yes_btn", lang)},
                        {"id": "noroot_n", "title": t("noroot.no_btn",  lang)},
                    ],
                )
            return

        # /backlog run <proje> [prefix] [max]
        if sub in ("çalıştır", "run"):
            if len(parts) < 2:
                await messenger.send_text(sender, t("backlog.run_usage", lang))
                return
            project_id = parts[1]
            prefix     = parts[2] if len(parts) > 2 else ""
            max_items  = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

            await self._run_with_file_select(
                sender, session, lang, messenger,
                project_id=project_id, prefix=prefix,
                max_items=max_items, dry_run=False,
            )
            return

        # /backlog kuru <proje> [prefix]
        if sub in ("kuru", "dry"):
            if len(parts) < 2:
                await messenger.send_text(sender, t("backlog.dry_usage", lang))
                return
            project_id = parts[1]
            prefix     = parts[2] if len(parts) > 2 else ""

            await self._run_with_file_select(
                sender, session, lang, messenger,
                project_id=project_id, prefix=prefix,
                max_items=0, dry_run=True,
            )
            return

        # /backlog durum
        if sub in ("durum", "status"):
            await self._show_status(sender, lang, messenger)
            return

        await messenger.send_text(sender, t("backlog.usage", lang))

    @staticmethod
    async def _run_with_file_select(
        sender: str,
        session: dict,
        lang: str,
        messenger,
        *,
        project_id: str,
        prefix: str,
        max_items: int,
        dry_run: bool,
    ) -> None:
        """BACKLOG dosyalarını tarar; birden fazlaysa dosya seçim ekranı gösterir.

        Tek dosyada doğrudan paralel seçimine, sıfır dosyada hata mesajına geçer.
        Buton akışındaki _hp_backlog_button ile simetrik davranış sağlar.
        """
        from pathlib import Path as _Path
        from ...features.menu import _scan_backlog_files, _name_from_path
        from ...i18n import t

        backlog_files = await _scan_backlog_files(project_id)

        if len(backlog_files) == 0:
            await messenger.send_text(sender, t("backlog.no_file_found", lang))
            return

        base_params: dict = {
            "project_id": project_id,
            "prefix":     prefix,
            "max_items":  max_items,
            "dry_run":    dry_run,
        }

        if len(backlog_files) == 1:
            fpath = backlog_files[0]
            if _Path(fpath).name != "BACKLOG.md":
                base_params["backlog_path"] = fpath
            session["_pending_parallel"] = {"cmd": "backlog", "params": base_params}
            prefix_label = f" · prefix: {prefix}" if prefix else ""
            display_proj = f"{project_id}{t('parallel.dry_label', lang)}" if dry_run else project_id
            await messenger.send_buttons(
                sender,
                t("parallel.backlog_ask", lang, project=display_proj, prefix=prefix_label),
                [
                    {"id": "parallel_1", "title": t("parallel.btn_rec", lang, n=1)},
                    {"id": "parallel_2", "title": t("parallel.btn",     lang, n=2)},
                    {"id": "parallel_3", "title": t("parallel.btn",     lang, n=3)},
                ],
            )
            return

        # Birden fazla dosya → dosya seçim ekranı
        session["_backlog_files"]   = backlog_files
        session["_pending_parallel"] = {"cmd": "backlog", "params": base_params}
        buttons = [
            {"id": f"backlogfile_{i}", "title": _name_from_path(f)}
            for i, f in enumerate(backlog_files[:3])
        ]
        buttons.append({"id": "backlogfile_all", "title": t("backlog.file_all", lang)})
        await messenger.send_buttons(
            sender,
            t("backlog.select_file", lang),
            buttons,
        )

    @staticmethod
    async def _show_status(sender: str, lang: str, messenger) -> None:
        """Backlog executor durumunu gösterir: aktifse canlı ilerleme, değilse son run özeti."""
        import time
        import httpx as _httpx
        from ...i18n import t

        data: dict = {}
        try:
            async with _httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("http://localhost:8010/internal/backlog/status")
                if resp.status_code == 200:
                    data = resp.json()
        except Exception as _exc:
            log.warning("backlog_cmd: status endpoint erişilemedi — %s", _exc)

        status         = data.get("status", "")
        total          = data.get("total_items", 0)
        completed      = data.get("completed", 0)
        failed         = data.get("failed", 0)
        started_at     = data.get("started_at")
        project_id     = data.get("project_id", "?")
        backlog_file   = data.get("backlog_file", "")
        queued_pending = int(data.get("queued_pending", 0))

        if status == "running":
            pct    = int(completed / total * 100) if total else 0
            filled = min(pct // 10, 10)
            bar    = "▓" * filled + "░" * (10 - filled)
            elapsed = int((time.time() - started_at) / 60) if started_at else 0
            eta_str = ""
            if completed and started_at:
                rate    = (time.time() - started_at) / completed
                eta_sec = int(rate * (total - completed))
                eta_str = t("backlog.status_eta", lang, minutes=max(1, eta_sec // 60))
            file_line = f"\n📄 {backlog_file}" if backlog_file and backlog_file != "BACKLOG.md" else ""
            lines = [
                t("backlog.status_running_header", lang, project=project_id) + file_line,
                f"[{bar}] {completed}/{total} item (%{pct})",
                t("backlog.status_elapsed", lang, minutes=elapsed) + eta_str,
            ]
            if queued_pending > 0:
                lines.append(t("backlog.status_queue", lang, n=queued_pending))
            await messenger.send_buttons(
                sender,
                "\n".join(lines),
                [{"id": "backlog_cancel", "title": t("backlog.btn_stop", lang)}],
            )
            return

        if status == "completed":
            lines = [
                t("backlog.status_header", lang),
                t(
                    "backlog.status_done_row",
                    lang,
                    project=project_id,
                    completed=completed,
                    total=total,
                    failed=failed,
                ),
            ]
            await messenger.send_text(sender, "\n".join(lines))
            return

        await messenger.send_text(sender, t("backlog.status_empty", lang))


registry.register(BacklogCommand())
