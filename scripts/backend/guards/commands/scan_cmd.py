"""/scan komutu — proje tarama pipeline'ını yönetir."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .registry import registry
from ..permission import Perm

log = logging.getLogger(__name__)

# data/scan_configs/ dizini (proje kökü / data / scan_configs)
_SCAN_CONFIGS_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "scan_configs"

# active_context.json yolu
_CTX_FILE = Path(__file__).parent.parent.parent.parent.parent / "data" / "active_context.json"


def _load_scan_configs() -> dict[str, dict]:
    """scan_configs/ dizinindeki tüm JSON dosyalarını yükler. {type: config}"""
    configs: dict[str, dict] = {}
    if not _SCAN_CONFIGS_DIR.exists():
        return configs
    for path in sorted(_SCAN_CONFIGS_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            scan_type = data.get("type")
            if scan_type:
                configs[scan_type] = data
        except Exception as exc:  # noqa: BLE001
            log.warning("scan_cmd: config yüklenemedi %s — %s", path.name, exc)
    return configs


def _get_root_project() -> dict | None:
    """active_context.json'dan aktif root project bilgisini döndürür."""
    try:
        ctx = json.loads(_CTX_FILE.read_text(encoding="utf-8"))
        return ctx.get("active_root_project")
    except Exception:  # noqa: BLE001
        return None


class ScanCommand:
    """Proje tarama pipeline'ı başlatır ve durumunu gösterir."""

    cmd_id      = "/scan"
    perm        = Perm.OWNER
    button_id   = "cmd_scan"
    label       = "Kod Tarama"
    description = "Proje güvenlik/bug taraması başlatır."
    usage       = "/scan [security|bugfix|status|history] [--dry]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:  # noqa: PLR0911
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        lang      = session.get("lang", "tr")
        messenger = get_messenger()
        arg       = (arg or "").strip()

        # /scan → mevcut tipleri listele
        if not arg:
            configs  = _load_scan_configs()
            buttons  = [
                {"id": f"scan_{stype}", "title": t(f"scan.btn_{stype}", lang)}
                for stype in configs
            ]
            buttons += [{"id": "scan_status",  "title": t("scan.btn_status", lang)}]
            await messenger.send_buttons(sender, t("scan.select_type", lang), buttons)
            return

        # /scan status
        if arg == "status":
            await self._handle_status(sender, lang, messenger, limit=1)
            return

        # /scan history
        if arg == "history":
            await self._handle_status(sender, lang, messenger, limit=5)
            return

        # /scan <tip> [--dry]
        dry_run   = "--dry" in arg
        scan_type = arg.replace("--dry", "").strip()

        configs = _load_scan_configs()
        if scan_type not in configs:
            available = ", ".join(configs.keys()) or "—"
            await messenger.send_text(
                sender,
                t("scan.invalid_type", lang, type=scan_type, available=available),
            )
            return

        # Root project kontrolü
        root_project = _get_root_project()
        if not root_project:
            await messenger.send_text(sender, t("scan.no_root_project", lang))
            return

        config       = configs[scan_type]
        scan_name    = config.get("name", scan_type)
        project_name = root_project.get("name") or root_project.get("id", "?")
        mode_key     = "scan.mode_dry" if dry_run else "scan.mode_full"
        mode_label   = t(mode_key, lang)

        await messenger.send_text(
            sender,
            t(
                "scan.starting",
                lang,
                name=scan_name,
                project=project_name,
                mode=mode_label,
            ),
        )

        # Gerçek tetikleme — arka planda scanner başlat
        import httpx as _httpx
        try:
            async with _httpx.AsyncClient(timeout=5.0) as _client:
                await _client.post(
                    "http://localhost:8010/internal/scanner/trigger",
                    json={
                        "scan_type": scan_type,
                        "project_id": root_project.get("id", ""),
                        "auto_review": True,
                        "dry_run": dry_run,
                    },
                )
        except Exception as _exc:
            log.warning("scan_cmd: trigger başarısız — %s", _exc)

    # ------------------------------------------------------------------
    # Yardımcı metotlar
    # ------------------------------------------------------------------

    async def _handle_status(
        self,
        sender: str,
        lang: str,
        messenger,
        limit: int,
    ) -> None:
        """Scan geçmişini gösterir (limit=1 → son durum, limit=5 → history)."""
        from ...i18n import t

        runs = self._load_recent_runs(limit)

        if limit == 1:
            if not runs:
                await messenger.send_text(sender, t("scan.status_none", lang))
                return
            run = runs[0]
            lines = [
                t("scan.status_header", lang),
                t(
                    "scan.status_row",
                    lang,
                    scan_type=run.get("scan_type", "?"),
                    status=run.get("status", "?"),
                    accepted=run.get("accepted", 0),
                    total=run.get("total", 0),
                ),
            ]
            await messenger.send_text(sender, "\n".join(lines))
        else:
            if not runs:
                await messenger.send_text(sender, t("scan.history_empty", lang))
                return
            lines = [t("scan.history_header", lang)]
            for run in runs:
                lines.append(
                    t(
                        "scan.history_row",
                        lang,
                        scan_type=run.get("scan_type", "?"),
                        status=run.get("status", "?"),
                        accepted=run.get("accepted", 0),
                        rejected=run.get("rejected", 0),
                        duplicate=run.get("duplicate", 0),
                    )
                )
            await messenger.send_text(sender, "\n".join(lines))

    @staticmethod
    def _load_recent_runs(limit: int) -> list[dict]:
        """
        Son scan run'larını döndürür.

        Gerçek pipeline entegrasyonu yapılana kadar boş liste döner;
        pipeline, kendi çalışma sonuçlarını burada okunacak bir JSON/DB
        kaydına yazmalıdır.
        """
        runs_file = _SCAN_CONFIGS_DIR.parent / "scan_runs.json"
        if not runs_file.exists():
            return []
        try:
            all_runs: list[dict] = json.loads(runs_file.read_text(encoding="utf-8"))
            return all_runs[-limit:] if limit else all_runs
        except Exception:  # noqa: BLE001
            return []


registry.register(ScanCommand())
