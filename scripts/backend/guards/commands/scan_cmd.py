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
    """active_context.json'dan aktif root project bilgisini döndürür.

    Tek doğruluk kaynağı: _root_project_helpers.get_active_root_project()
    cascading lookup yapar (active_root_project → active_project fallback).
    """
    from ._root_project_helpers import get_active_root_project
    return get_active_root_project()


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

        # /scan pause [run_id]
        if arg.startswith("pause"):
            parts = arg.split(maxsplit=1)
            run_id_hint = parts[1] if len(parts) > 1 else None
            await self._handle_pause(sender, lang, messenger, run_id_hint)
            return

        # /scan resume [run_id]
        if arg.startswith("resume"):
            parts = arg.split(maxsplit=1)
            run_id_hint = parts[1] if len(parts) > 1 else None
            await self._handle_resume(sender, lang, messenger, run_id_hint)
            return

        # /scan list
        if arg == "list":
            await self._handle_list(sender, lang, messenger)
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

        is_running     = bool(data.get("running_agent_run"))
        completed      = data.get("findings_count", 0)
        total          = data.get("total_chunks", 0)
        stype          = data.get("scan_type") or "?"
        started_at     = data.get("started_at")
        cancelled      = data.get("cancel_requested", False)
        paused         = data.get("pause_requested", False)
        phase          = data.get("phase") or "scanner"
        done_chunks    = data.get("completed_chunks", completed)
        done_batches   = data.get("completed_batches", 0)
        total_batches  = int(data.get("total_batches", 0) or 0)

        if is_running or paused:
            elapsed = int((time.time() - started_at) / 60) if started_at else 0

            if phase == "reviewer":
                header = t("scan.status_reviewer_header", lang, scan_type=stype)
                # Reviewer fazı progress bar — total_batches state.json'a yazılıyor
                # (reviewer_agent.py batches hesaplandıktan sonra). Eski run'lar
                # için total=0 olabilir → fallback olarak yalnızca count gösterilir.
                if total_batches > 0:
                    pct    = int(done_batches / total_batches * 100)
                    filled = pct // 10
                    bar    = "▓" * filled + "░" * (10 - filled)
                    progress_line = f"[{bar}] {done_batches}/{total_batches} batch (%{pct})"
                    eta_str = ""
                    if done_batches and started_at:
                        rate    = (time.time() - started_at) / done_batches
                        eta_sec = int(rate * (total_batches - done_batches))
                        eta_str = t("scan.status_eta", lang, minutes=max(1, eta_sec // 60))
                else:
                    progress_line = t("scan.status_reviewer_progress", lang, done=done_batches)
                    eta_str = ""
            else:
                pct    = int(done_chunks / total * 100) if total else 0
                filled = pct // 10
                bar    = "▓" * filled + "░" * (10 - filled)
                header = t("scan.status_scanner_header", lang, scan_type=stype)
                progress_line = f"[{bar}] {done_chunks}/{total} chunk (%{pct})"
                eta_str = ""
                if done_chunks and started_at:
                    rate    = (time.time() - started_at) / done_chunks
                    eta_sec = int(rate * (total - done_chunks))
                    eta_str = t("scan.status_eta", lang, minutes=max(1, eta_sec // 60))

            lines = [header, progress_line]
            if eta_str:
                lines.append(t("scan.status_elapsed", lang, minutes=elapsed) + eta_str)
            else:
                lines.append(t("scan.status_elapsed", lang, minutes=elapsed))

            if cancelled:
                lines.append(t("scan.status_cancelling", lang))
            elif paused:
                lines.append(t("scan.status_paused", lang))

            text = "\n".join(lines)
            if cancelled or paused:
                await messenger.send_text(sender, text)
            else:
                await messenger.send_buttons(
                    sender,
                    text,
                    [
                        {"id": "scan_pause",  "title": t("scan.btn_pause",  lang)},
                        {"id": "scan_cancel", "title": t("scan.btn_cancel", lang)},
                    ],
                )
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
    async def _handle_pause(
        sender: str, lang: str, messenger, run_id_hint: str | None
    ) -> None:
        """Pause isteğini /internal/scanner/pause endpoint'ine iletir."""
        import httpx as _httpx
        from ...i18n import t as _t
        from ...guards.runtime_state import get_active_scan_run_id, is_scan_running

        # run_id_hint belirtilmişse ama aktif run_id farklıysa uyar — minimal MVP
        if not is_scan_running():
            await messenger.send_text(sender, _t("scan.pause_none", lang))
            return

        try:
            async with _httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post("http://localhost:8010/internal/scanner/pause")
                if resp.status_code == 200:
                    await messenger.send_text(sender, _t("scan.pause_ok", lang))
                    return
        except Exception as _exc:
            log.warning("scan_cmd: pause endpoint erişilemedi — %s", _exc)
        await messenger.send_text(sender, _t("scan.pause_fail", lang))

    @staticmethod
    async def _handle_resume(
        sender: str, lang: str, messenger, run_id_hint: str | None
    ) -> None:
        """Resume isteğini /internal/scanner/resume endpoint'ine iletir.

        run_id_hint verilmişse o run_id'nin ScanPauseStore'unu da temizler
        (process restart sonrası manuel resume için).
        """
        import httpx as _httpx
        from ...i18n import t as _t
        from ...guards.runtime_state import is_scan_pause_requested

        if not is_scan_pause_requested():
            await messenger.send_text(sender, _t("scan.resume_none", lang))
            return

        # İsteğe bağlı: belirtilen run_id için ScanPauseStore'u da temizle
        if run_id_hint:
            try:
                from ...features.scan_pipeline.scan_pause_store import ScanPauseStore
                ScanPauseStore.request_resume(run_id_hint)
            except Exception as _exc:  # noqa: BLE001
                log.warning("scan_cmd: ScanPauseStore resume hatası — %s", _exc)

        try:
            async with _httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post("http://localhost:8010/internal/scanner/resume")
                if resp.status_code == 200:
                    await messenger.send_text(sender, _t("scan.resume_ok", lang))
                    return
        except Exception as _exc:
            log.warning("scan_cmd: resume endpoint erişilemedi — %s", _exc)
        await messenger.send_text(sender, _t("scan.resume_fail", lang))

    async def _handle_list(self, sender: str, lang: str, messenger) -> None:
        """Son 10 scan run_id'sini faz ve verdict özetiyle gösterir."""
        from ...i18n import t as _t

        runs = self._load_recent_runs(limit=10)
        if not runs:
            await messenger.send_text(sender, _t("scan.list_empty", lang))
            return

        lines = [_t("scan.list_header", lang)]
        for run in runs:
            run_id   = run.get("run_id", "?")
            stype    = run.get("scan_type", "?")
            status   = run.get("status", "?")
            # Kısa run_id (ilk 8 karakter)
            short_id = run_id[:8] if len(run_id) > 8 else run_id

            # state.json'dan faz bilgisi
            phase = "?"
            try:
                from ...features.scan_pipeline.scan_pause_store import ScanPauseStore
                state = ScanPauseStore.get_state(run_id)
                phase = state.get("phase") or status
            except Exception:  # noqa: BLE001
                pass

            lines.append(
                _t("scan.list_row", lang,
                   run_id=short_id, scan_type=stype, phase=phase, status=status)
            )
        await messenger.send_text(sender, "\n".join(lines))

    @staticmethod
    def _load_recent_runs(limit: int) -> list[dict]:
        """Son scan run'larını scan_runs/ dizinindeki meta.json dosyalarından döndürür.

        Hem düz (`scan_runs/<run_id>/`) hem nested (`scan_runs/<project_id>/<run_id>/`)
        yerleşimini destekler.
        """
        from ...features.scan_pipeline.pipeline import iter_run_dirs  # noqa: PLC0415

        runs_dir = _SCAN_CONFIGS_DIR.parent / "scan_runs"
        if not runs_dir.exists():
            return []
        runs: list[dict] = []
        try:
            for d in sorted(
                iter_run_dirs(runs_dir),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            ):
                try:
                    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                    runs.append(meta)
                except Exception:  # noqa: BLE001
                    pass
                if len(runs) >= limit:
                    break
        except Exception:  # noqa: BLE001
            pass
        return runs


registry.register(ScanCommand())
