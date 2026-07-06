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


def _run_path(run_id: str, filename: str) -> Path:
    """Bir run dosyasının yolunu çözer — düz ve nested yerleşim desteklenir."""
    from .pipeline import resolve_run_dir  # noqa: PLC0415 — döngüsel import yok
    return resolve_run_dir(run_id, _RUNS_DIR) / filename


class AllScansRunner:
    """Tüm konfigüre edilmiş scan tiplerini sırayla çalıştırır.

    DIP: ScannerAgent ve messenger factory üzerinden çalışır.
    SRP: Orchestration + özet bildirimi — tarama mantığı ScannerAgent'ta.
    """

    async def run(
        self,
        project_id: str,
        parallel: int | None = None,
        dry_run: bool = False,
        include_third_party: bool = False,
        scan_model: str | None = None,
        review_model: str | None = None,
        scan_effort: str | None = None,
        review_effort: str | None = None,
        scan_thinking: bool = False,
        review_thinking: bool = False,
    ) -> None:
        """Tüm scan tiplerini sırayla çalıştır, sonunda özet gönder.

        Args:
            project_id:          DB'deki proje ID'si.
            parallel:            Her scanner için eş zamanlı chunk çağrısı (kullanıcı
                                 seçimi). None → scan config'indeki concurrency.
            dry_run:             True ise BACKLOG.md'ye yazma.
            include_third_party: True ise node_modules/venv/.venv/vendor taramaya dahil edilir.
            scan_model:          Opsiyonel model alias ("haiku", "sonnet", "sonnet5", "opus", "fable") veya tam ad.
            review_model:        Opsiyonel reviewer model alias ("haiku", "sonnet", "sonnet5", "opus", "fable").
            scan_effort:         Opsiyonel scanner effort seviyesi.
            review_effort:       Opsiyonel reviewer effort seviyesi.
            scan_thinking:       Scanner için Extended Thinking on/off toggle.
            review_thinking:     Reviewer için Extended Thinking on/off toggle.
        """
        from .config_loader import ScanConfigLoader
        from .scanner_agent import ScannerAgent, FileContentCache
        from ...adapters.messenger import get_messenger
        from ...config import settings
        from ...i18n import t
        from ...guards.runtime_state import (
            clear_scan_cancel, is_scan_cancel_requested,
            clear_scan_pause, is_scan_pause_requested,
        )

        lang      = "tr"
        messenger = get_messenger()
        owner     = settings.owner_id

        available = ScanConfigLoader().list_available()
        if not available:
            await messenger.send_text(owner, t("scan.no_configs", lang))
            return

        # Önceki stale iptal ve pause flag'lerini temizle
        clear_scan_cancel()
        clear_scan_pause()

        total_scans = len(available)
        results: list[dict] = []
        cancelled = False

        # Tüm scan tipleri arasında paylaşılan dosya içeriği cache'i —
        # aynı proje dosyaları her scan tipi için diskten yeniden okunmaz.
        shared_file_cache = FileContentCache()

        for idx, scan_type in enumerate(available, start=1):
            if is_scan_cancel_requested():
                logger.info(
                    "AllScansRunner: iptal istendi, kalan %d scan_type atlanıyor",
                    total_scans - idx + 1,
                )
                cancelled = True
                break

            # Pause bekle — scan_type döngüsü başında; cancel gelirse çık
            if is_scan_pause_requested():
                import asyncio  # noqa: PLC0415
                logger.info(
                    "AllScansRunner: pause istendi, scan_type=%s başlamadan bekleniyor",
                    scan_type,
                )
                while is_scan_pause_requested():
                    if is_scan_cancel_requested():
                        cancelled = True
                        break
                    await asyncio.sleep(2.0)
                if cancelled:
                    break
                logger.info("AllScansRunner: resume — scan_type=%s başlıyor", scan_type)

            logger.info(
                "AllScansRunner: [%d/%d] scan_type=%s başladı project_id=%s",
                idx, total_scans, scan_type, project_id,
            )
            try:
                run_id = await ScannerAgent(file_cache=shared_file_cache).run(
                    scan_type, project_id,
                    auto_review=True, dry_run=dry_run, parallel=parallel,
                    include_third_party=include_third_party,
                    notify_on_review=False,  # özet sonunda AllScansRunner gönderir
                    scan_model=scan_model,
                    review_model=review_model,
                    scan_effort=scan_effort,
                    review_effort=review_effort,
                    scan_thinking=scan_thinking,
                    review_thinking=review_thinking,
                )
                meta = self._read_meta(run_id)
                accepted  = meta.get("accepted", 0)
                rejected  = meta.get("rejected", 0)
                duplicate = meta.get("duplicate", 0)
                results.append({
                    "scan_type":          scan_type,
                    "run_id":             run_id,
                    "ok":                 True,
                    "accepted":           accepted,
                    "rejected":           rejected,
                    "duplicate":          duplicate,
                    "total":              meta.get("total_findings", 0),
                    "severity_breakdown": self._read_severity_breakdown(run_id),
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
    def _read_severity_breakdown(run_id: str) -> str:
        """review.jsonl'den kabul edilen bulgular için şiddet dağılımı döndürür."""
        _SEVERITY_EMOJI = {
            "critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢", "info": "⚪",
        }
        review_path = _run_path(run_id, "review.jsonl")
        if not review_path.exists():
            return "—"
        try:
            reviewed = json.loads(review_path.read_text(encoding="utf-8"))
            counts: dict[str, int] = {}
            for r in reviewed:
                if r.get("verdict") != "accepted":
                    continue
                sev = r.get("finding", {}).get("severity", "medium")
                counts[sev] = counts.get(sev, 0) + 1
            if not counts:
                return "—"
            order = ["critical", "high", "medium", "low", "info"]
            parts = [
                f"{_SEVERITY_EMOJI.get(s, '🟡')}{counts[s]}"
                for s in order
                if s in counts
            ]
            return " ".join(parts)
        except Exception:  # noqa: BLE001
            return "—"

    @staticmethod
    def _read_meta(run_id: str) -> dict:
        """run_id'den meta.json okur; bulunamazsa boş dict döner."""
        meta_path = _run_path(run_id, "meta.json")
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
                        severity_breakdown=r.get("severity_breakdown", "—"),
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
