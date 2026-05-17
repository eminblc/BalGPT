"""/backlog komutu — BACKLOG executor'ı Telegram/WhatsApp'tan yönetir.

Alt komutlar:
  /backlog                           → proje seçim butonları göster
  /backlog çalıştır <proje> [prefix] [max] → executor'ı başlat
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
    usage       = "/backlog [çalıştır <proje> [prefix] [max] | durum | kuru <proje>]"

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

        # /backlog çalıştır <proje> [prefix] [max]
        if sub in ("çalıştır", "run"):
            if len(parts) < 2:
                await messenger.send_text(sender, t("backlog.run_usage", lang))
                return
            project_id = parts[1]
            prefix     = parts[2] if len(parts) > 2 else ""
            max_items  = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 3
            await self._trigger(sender, project_id, prefix, max_items, False, lang, messenger)
            return

        # /backlog kuru <proje> [prefix]
        if sub in ("kuru", "dry"):
            if len(parts) < 2:
                await messenger.send_text(sender, t("backlog.dry_usage", lang))
                return
            project_id = parts[1]
            prefix     = parts[2] if len(parts) > 2 else ""
            await self._trigger(sender, project_id, prefix, 3, True, lang, messenger)
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
                        "parallel":   2,
                        "dry_run":    dry_run,
                    },
                )
        except Exception as exc:
            log.warning("backlog_cmd: trigger başarısız — %s", exc)

    @staticmethod
    async def _show_status(sender: str, lang: str, messenger) -> None:
        """Son backlog executor run'larını gösterir."""
        from ...i18n import t
        from pathlib import Path
        import json

        _STATUS_ICON = {
            "pending":   "⏳",
            "running":   "▶️",
            "completed": "✅",
            "failed":    "❌",
            "cancelled": "🛑",
        }

        runs_file = Path(__file__).parent.parent.parent.parent.parent / "data" / "backlog_runs.json"
        runs: list[dict] = []
        if runs_file.exists():
            try:
                all_runs: list[dict] = json.loads(runs_file.read_text(encoding="utf-8"))
                runs = [r for r in all_runs if r.get("agent_type") == "backlog_executor"][-5:]
            except Exception:  # noqa: BLE001
                pass

        if not runs:
            await messenger.send_text(sender, t("backlog.status_empty", lang))
            return

        lines = [t("backlog.status_header", lang)]
        for run in runs:
            icon   = _STATUS_ICON.get(run.get("status", ""), "▶️")
            rid    = str(run.get("id", "?"))[:6]
            output = run.get("output") or "—"
            lines.append(f"{icon} #{rid} {run.get('project_id', '?')} — {output}")
        await messenger.send_text(sender, "\n".join(lines))


registry.register(BacklogCommand())
