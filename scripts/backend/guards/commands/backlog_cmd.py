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
            buttons = [
                {"id": "backlog_run_petekv5",  "title": t("backlog.btn_run", lang)},
                {"id": "backlog_status",        "title": t("backlog.btn_status", lang)},
            ]
            await messenger.send_buttons(sender, t("backlog.select_action", lang), buttons)
            return

        # /backlog run <proje> [prefix] [max]
        if sub in ("çalıştır", "run"):
            if len(parts) < 2:
                await messenger.send_text(sender, t("backlog.run_usage", lang))
                return
            project_id = parts[1]
            prefix     = parts[2] if len(parts) > 2 else ""
            max_items  = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0

            # Paralel seçim ekranı göster; tetikleme parallel_ handler'da yapılır
            session["_pending_parallel"] = {
                "cmd": "backlog",
                "params": {
                    "project_id": project_id,
                    "prefix":     prefix,
                    "max_items":  max_items,
                    "dry_run":    False,
                },
            }
            prefix_label = f" · prefix: {prefix}" if prefix else ""
            await messenger.send_buttons(
                sender,
                t("parallel.backlog_ask", lang, project=project_id, prefix=prefix_label),
                [
                    {"id": "parallel_1", "title": t("parallel.btn_rec", lang, n=1)},
                    {"id": "parallel_2", "title": t("parallel.btn",     lang, n=2)},
                    {"id": "parallel_3", "title": t("parallel.btn",     lang, n=3)},
                ],
            )
            return

        # /backlog kuru <proje> [prefix]
        if sub in ("kuru", "dry"):
            if len(parts) < 2:
                await messenger.send_text(sender, t("backlog.dry_usage", lang))
                return
            project_id = parts[1]
            prefix     = parts[2] if len(parts) > 2 else ""

            session["_pending_parallel"] = {
                "cmd": "backlog",
                "params": {
                    "project_id": project_id,
                    "prefix":     prefix,
                    "max_items":  0,
                    "dry_run":    True,
                },
            }
            prefix_label = f" · prefix: {prefix}" if prefix else ""
            dry_label    = t("parallel.dry_label", lang)
            await messenger.send_buttons(
                sender,
                t("parallel.backlog_ask", lang, project=f"{project_id}{dry_label}", prefix=prefix_label),
                [
                    {"id": "parallel_1", "title": t("parallel.btn_rec", lang, n=1)},
                    {"id": "parallel_2", "title": t("parallel.btn",     lang, n=2)},
                    {"id": "parallel_3", "title": t("parallel.btn",     lang, n=3)},
                ],
            )
            return

        # /backlog durum
        if sub in ("durum", "status"):
            await self._show_status(sender, lang, messenger)
            return

        await messenger.send_text(sender, t("backlog.usage", lang))

    @staticmethod
    async def _trigger(
        sender: str,
        project_id: str,
        prefix: str,
        max_items: int,
        parallel: int,
        dry_run: bool,
        lang: str,
        messenger,
    ) -> None:
        """Backlog executor'ı tetikler ve kullanıcıya bildirim gönderir."""
        from ...i18n import t
        import httpx as _httpx

        mode = t("backlog.mode_dry", lang) if dry_run else t("backlog.mode_full", lang)
        await messenger.send_text(
            sender,
            t(
                "backlog.starting",
                lang,
                project=project_id,
                prefix=prefix or t("backlog.prefix_all", lang),
                max_items=max_items,
                mode=mode,
            ),
        )

        try:
            async with _httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    "http://localhost:8010/internal/backlog/execute",
                    json={
                        "project_id": project_id,
                        "prefix":     prefix,
                        "max_items":  max_items,
                        "parallel":   parallel,
                        "dry_run":    dry_run,
                    },
                )
        except Exception as exc:
            log.warning("backlog_cmd: trigger başarısız — %s", exc)

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

        status     = data.get("status", "")
        total      = data.get("total_items", 0)
        completed  = data.get("completed", 0)
        failed     = data.get("failed", 0)
        started_at = data.get("started_at")
        project_id = data.get("project_id", "?")

        if status == "running":
            pct    = int(completed / total * 100) if total else 0
            filled = pct // 10
            bar    = "▓" * filled + "░" * (10 - filled)
            elapsed = int((time.time() - started_at) / 60) if started_at else 0
            eta_str = ""
            if completed and started_at:
                rate    = (time.time() - started_at) / completed
                eta_sec = int(rate * (total - completed))
                eta_str = t("backlog.status_eta", lang, minutes=max(1, eta_sec // 60))
            lines = [
                t("backlog.status_running_header", lang, project=project_id),
                f"[{bar}] {completed}/{total} item (%{pct})",
                t("backlog.status_elapsed", lang, minutes=elapsed) + eta_str,
            ]
            await messenger.send_text(sender, "\n".join(lines))
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
