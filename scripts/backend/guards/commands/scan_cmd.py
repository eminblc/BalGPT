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

        # /scan → mevcut tipleri listele (send_list — 10+ seçenek olabilir)
        if not arg:
            configs = _load_scan_configs()
            root_project = _get_root_project()
            project_name = ""
            if root_project:
                project_name = root_project.get("name") or root_project.get("id", "")

            quick_rows = [
                {"id": "scan_all",    "title": t("scan.btn_all",    lang), "description": project_name},
                {"id": "scan_status", "title": t("scan.btn_status", lang), "description": ""},
            ]
            type_rows = [
                {
                    "id":          f"scan_{stype}",
                    "title":       t(f"scan.btn_{stype}", lang),
                    "description": project_name,
                }
                for stype in configs
            ]
            sections = [
                {"title": t("scan.section_quick", lang), "rows": quick_rows},
                {"title": t("scan.section_types", lang), "rows": type_rows},
            ]
            await messenger.send_list(sender, t("scan.select_type", lang), sections=sections)
            return

        # /scan status
        if arg == "status":
            await self._handle_status(sender, lang, messenger, limit=1)
            return

        # /scan history
        if arg == "history":
            await self._handle_status(sender, lang, messenger, limit=5)
            return

        # /scan cancel
        if arg == "cancel":
            await self._handle_cancel(sender, lang, messenger)
            return

        # /scan all [--dry] → tüm taramaları sırayla başlat
        dry_run = "--dry" in arg
        clean_arg = arg.replace("--dry", "").strip()

        if clean_arg == "all":
            root_project = _get_root_project()
            all_scan_name = t("scan.btn_all", lang)
            if not root_project:
                # Root project yok → 99-root onayı sor
                session["_pending_parallel"] = {
                    "cmd":              "all_scans",
                    "_display_name":    all_scan_name,
                    "_display_project": "99-root",
                    "_needs_root_confirm": True,
                    "params": {
                        "project_id": "",
                        "dry_run":    dry_run,
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
            project_name = root_project.get("name") or root_project.get("id", "?")
            session["_pending_parallel"] = {
                "cmd": "all_scans",
                "_display_name":    all_scan_name,
                "_display_project": project_name,
                "params": {
                    "project_id": root_project.get("id", ""),
                    "dry_run":    dry_run,
                },
            }
            await messenger.send_buttons(
                sender,
                t("scan.third_party_ask", lang),
                [
                    {"id": "scan3p_n", "title": t("scan.third_party_skip",    lang)},
                    {"id": "scan3p_y", "title": t("scan.third_party_include", lang)},
                ],
            )
            return

        # /scan <tip> [--dry]
        scan_type = clean_arg

        configs = _load_scan_configs()
        if scan_type not in configs:
            available = ", ".join(configs.keys()) or "—"
            await messenger.send_text(
                sender,
                t("scan.invalid_type", lang, type=scan_type, available=available),
            )
            return

        config    = configs[scan_type]
        scan_name = config.get("name", scan_type)

        # Root project kontrolü
        root_project = _get_root_project()
        if not root_project:
            # Root project yok → 99-root onayı sor
            session["_pending_parallel"] = {
                "cmd":              "scan",
                "_display_name":    scan_name,
                "_display_project": "99-root",
                "_needs_root_confirm": True,
                "params": {
                    "scan_type":   scan_type,
                    "project_id":  "",
                    "auto_review": True,
                    "dry_run":     dry_run,
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

        project_name = root_project.get("name") or root_project.get("id", "?")

        # Üçüncü taraf sorusu göster; paralel seçim scan3p_ handler'da yapılır
        session["_pending_parallel"] = {
            "cmd": "scan",
            "_display_name":    scan_name,
            "_display_project": project_name,
            "params": {
                "scan_type":   scan_type,
                "project_id":  root_project.get("id", ""),
                "auto_review": True,
                "dry_run":     dry_run,
            },
        }
        await messenger.send_buttons(
            sender,
            t("scan.third_party_ask", lang),
            [
                {"id": "scan3p_n", "title": t("scan.third_party_skip",    lang)},
                {"id": "scan3p_y", "title": t("scan.third_party_include", lang)},
            ],
        )

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
        """Scan durumunu gösterir: aktifse canlı ilerleme, değilse son tamamlanan taramalar."""
        import time
        import httpx as _httpx
        from ...i18n import t

        # /internal/scanner/status endpoint'ini çağır
        data: dict = {}
        try:
            async with _httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get("http://localhost:8010/internal/scanner/status")
                if resp.status_code == 200:
                    data = resp.json()
        except Exception as _exc:
            log.warning("scan_cmd: status endpoint erişilemedi — %s", _exc)

        is_running = bool(data.get("running_agent_run"))
        completed  = data.get("findings_count", 0)
        total      = data.get("total_chunks", 0)
        stype      = data.get("scan_type") or "?"
        started_at = data.get("started_at")
        cancelled  = data.get("cancel_requested", False)

        if is_running:
            pct     = int(completed / total * 100) if total else 0
            filled  = pct // 10
            bar     = "▓" * filled + "░" * (10 - filled)
            elapsed = int((time.time() - started_at) / 60) if started_at else 0
            eta_str = ""
            if completed and started_at:
                rate    = (time.time() - started_at) / completed
                eta_sec = int(rate * (total - completed))
                eta_str = t("scan.status_eta", lang, minutes=max(1, eta_sec // 60))
            cancel_note = t("scan.status_cancelling", lang) if cancelled else ""
            lines = [
                t("scan.status_running_header", lang, scan_type=stype),
                f"[{bar}] {completed}/{total} chunk (%{pct})",
                t("scan.status_elapsed", lang, minutes=elapsed) + eta_str,
            ]
            if cancel_note:
                lines.append(cancel_note)
            text = "\n".join(lines)
            if not cancelled:
                await messenger.send_buttons(
                    sender,
                    text,
                    [{"id": "scan_cancel", "title": t("scan.btn_cancel", lang)}],
                )
            else:
                await messenger.send_text(sender, text)
            return

        # Aktif scan yok — son tamamlanan run'ları scan_runs dizininden oku
        runs = self._load_recent_runs(limit)
        if not runs:
            await messenger.send_text(sender, t("scan.status_none", lang))
            return

        if limit == 1:
            run   = runs[0]
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
        else:
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
    async def _handle_cancel(sender: str, lang: str, messenger) -> None:
        """İptal isteğini /internal/scanner/cancel endpoint'ine iletir."""
        import httpx as _httpx
        from ...i18n import t as _t

        try:
            async with _httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post("http://localhost:8010/internal/scanner/cancel")
                if resp.status_code == 200:
                    await messenger.send_text(sender, _t("scan.cancel_ok", lang))
                    return
        except Exception as _exc:
            log.warning("scan_cmd: cancel endpoint erişilemedi — %s", _exc)
        await messenger.send_text(sender, _t("scan.cancel_fail", lang))

    @staticmethod
    def _load_recent_runs(limit: int) -> list[dict]:
        """Son scan run'larını scan_runs/ dizinindeki meta.json dosyalarından döndürür."""
        runs_dir = _SCAN_CONFIGS_DIR.parent / "scan_runs"
        if not runs_dir.exists():
            return []
        runs: list[dict] = []
        try:
            for d in sorted(runs_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                meta_file = d / "meta.json"
                if meta_file.exists():
                    try:
                        meta = json.loads(meta_file.read_text(encoding="utf-8"))
                        runs.append(meta)
                    except Exception:  # noqa: BLE001
                        pass
                if len(runs) >= limit:
                    break
        except Exception:  # noqa: BLE001
            pass
        return runs


registry.register(ScanCommand())
