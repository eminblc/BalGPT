"""AllScansRunner — tüm scan tiplerini sırayla çalıştırır ve özet gönderir.

SRP: Yalnızca orchestration ve bildirim — her scan ScannerAgent'a delege edilir.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_RUNS_DIR   = Path(__file__).parent.parent.parent.parent.parent / "data" / "scan_runs"
_CONFIGS_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "scan_configs"


class AllScansRunner:
    """Tüm konfigüre edilmiş scan tiplerini sırayla çalıştırır.

    DIP: ScannerAgent ve messenger factory üzerinden çalışır.
    SRP: Orchestration + özet bildirimi — tarama mantığı ScannerAgent'ta.
    """

    async def run(
        self,
        project_id: str,
        parallel: int = 3,
        dry_run: bool = False,
        include_third_party: bool = False,
        scan_model: str | None = None,
        review_model: str | None = None,
    ) -> None:
        """Tüm scan tiplerini sırayla çalıştır, sonunda özet gönder.

        Args:
            project_id:          DB'deki proje ID'si.
            parallel:            Her scanner için eş zamanlı Bridge chunk sayısı.
            dry_run:             True ise BACKLOG.md'ye yazma.
            include_third_party: True ise node_modules/venv/.venv/vendor taramaya dahil edilir.
            scan_model:          Opsiyonel model alias ("haiku", "sonnet", "opus") veya tam ad.
            review_model:        Opsiyonel reviewer model alias ("haiku", "sonnet", "opus").
        """
        from .config_loader import ScanConfigLoader
        from .scanner_agent import ScannerAgent
        from ...adapters.messenger import get_messenger
        from ...config import settings
        from ...i18n import t
        from ...guards.runtime_state import clear_scan_cancel, is_scan_cancel_requested

        lang      = "tr"
        messenger = get_messenger()
        owner     = settings.owner_id

        available = ScanConfigLoader().list_available()
        if not available:
            await messenger.send_text(owner, t("scan.no_configs", lang))
            return

        # Önceki stale iptal flag'ini temizle
        clear_scan_cancel()

        total_scans = len(available)
        results: list[dict] = []
        cancelled = False

        for idx, scan_type in enumerate(available, start=1):
            if is_scan_cancel_requested():
                logger.info(
                    "AllScansRunner: iptal istendi, kalan %d scan_type atlanıyor",
                    total_scans - idx + 1,
                )
                cancelled = True
                break

            logger.info(
                "AllScansRunner: [%d/%d] scan_type=%s başladı project_id=%s",
                idx, total_scans, scan_type, project_id,
            )
            try:
                run_id = await ScannerAgent().run(
                    scan_type, project_id,
                    auto_review=True, dry_run=dry_run, parallel=parallel,
                    include_third_party=include_third_party,
                    notify_on_review=False,  # özet sonunda AllScansRunner gönderir
                    scan_model=scan_model,
                    review_model=review_model,
                )
                meta = self._read_meta(run_id)
                accepted  = meta.get("accepted", 0)
                rejected  = meta.get("rejected", 0)
                duplicate = meta.get("duplicate", 0)
                results.append({
                    "scan_type": scan_type,
                    "run_id":    run_id,
                    "ok":        True,
                    "accepted":  accepted,
                    "rejected":  rejected,
                    "duplicate": duplicate,
                    "total":     meta.get("total_findings", 0),
                })
                logger.info(
                    "AllScansRunner: [%d/%d] scan_type=%s bitti — accepted=%d rejected=%d",
                    idx, total_scans, scan_type, accepted, rejected,
                )
            except Exception as exc:
                logger.error("AllScansRunner: başarısız scan_type=%s — %s", scan_type, exc)
                results.append({"scan_type": scan_type, "ok": False, "error": str(exc)})

        summary = self._build_summary(results, dry_run, lang, cancelled=cancelled)
        await messenger.send_text(owner, summary)

    @staticmethod
    def _read_meta(run_id: str) -> dict:
        """run_id'den meta.json okur; bulunamazsa boş dict döner."""
        meta_path = _RUNS_DIR / run_id / "meta.json"
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    @staticmethod
    def _build_summary(
        results: list[dict],
        dry_run: bool,
        lang: str,
        cancelled: bool = False,
    ) -> str:
        """Tüm scan sonuçlarını özet metin olarak formatlar."""
        from ...i18n import t

        total_accepted  = sum(r.get("accepted", 0)  for r in results if r["ok"])
        total_rejected  = sum(r.get("rejected", 0)  for r in results if r["ok"])
        total_duplicate = sum(r.get("duplicate", 0) for r in results if r["ok"])
        errors          = [r for r in results if not r["ok"]]

        dry_note = t("scan_all.dry_note", lang) if dry_run else ""
        cancel_note = " — iptal edildi" if cancelled else ""
        lines = [t("scan_all.summary_header", lang) + dry_note + cancel_note]

        for r in results:
            if r["ok"]:
                lines.append(
                    t(
                        "scan_all.summary_row",
                        lang,
                        scan_type=r["scan_type"],
                        accepted=r["accepted"],
                        rejected=r["rejected"],
                        duplicate=r["duplicate"],
                    )
                )
            else:
                lines.append(t("scan_all.summary_error", lang, scan_type=r["scan_type"]))

        lines.append("")
        lines.append(
            t(
                "scan_all.summary_total",
                lang,
                accepted=total_accepted,
                rejected=total_rejected,
                duplicate=total_duplicate,
                errors=len(errors),
            )
        )
        return "\n".join(lines)
