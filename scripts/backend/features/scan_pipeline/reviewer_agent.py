"""ReviewerAgent — mevcut bir scan run_id üzerinden review yapar.

ScannerAgent tamamlandıktan sonra auto_review=True ile otomatik,
veya /internal/reviewer/trigger ile manuel tetiklenir.
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from .config_loader import ScanConfigLoader
from .pipeline import ScanPipeline, resolve_run_dir
from .scan_pause_store import ScanPauseStore

logger = logging.getLogger(__name__)

_RUNS_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "scan_runs"

# Tek LLM çağrısına gönderilecek maksimum bulgu sayısı
_REVIEW_BATCH_SIZE = 50

_SEVERITY_EMOJI: dict[str, str] = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
    "low": "🟢",
    "info": "⚪",
}


def _build_severity_breakdown(reviewed: list) -> str:
    """Kabul edilen bulgulardan şiddet dağılımı özeti üretir (ör. '🔴1 🟠2')."""
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


def _collect_backlog_ids(reviewed: list) -> str:
    """Kabul edilen bulgulardan backlog ID listesi döndürür (ör. 'SEC-001, SEC-002')."""
    ids = [
        r["backlog_id"]
        for r in reviewed
        if r.get("verdict") == "accepted" and r.get("backlog_id")
    ]
    return ", ".join(ids)


class ReviewerAgent:
    """Mevcut bir scan run_id üzerinden review fazını çalıştırır.

    DIP: get_llm() fabrikası üzerinden abstract LLMProvider kullanır.
    SRP: Yalnızca reviewer koordinasyonu — scanner fazı ScannerAgent'ta.
    """

    def __init__(self) -> None:
        # Lazy-load — servis başlarken import hatası vermemek için
        self._pipeline: ScanPipeline | None = None
        self._config_loader: ScanConfigLoader | None = None

    def _get_pipeline(self) -> ScanPipeline:
        if self._pipeline is None:
            self._pipeline = ScanPipeline()
        return self._pipeline

    def _get_config_loader(self) -> ScanConfigLoader:
        if self._config_loader is None:
            self._config_loader = ScanConfigLoader()
        return self._config_loader

    async def run(
        self,
        run_id: str,
        dry_run: bool = False,
        notify: bool = True,
        review_model: str | None = None,
        review_effort: str | None = None,
        review_thinking: bool = False,
    ) -> dict:
        """Verilen run_id için review fazını çalıştırır.

        Args:
            run_id:  ScannerAgent tarafından oluşturulan run ID.
            dry_run: True ise BACKLOG.md'ye yazma, yalnızca analiz yap.
                     meta.json'daki dry_run değeri ile override edilir.
            notify:  False ise tamamlanma bildirimi gönderilmez.
                     AllScansRunner gibi orchestrator'lar bunu False geçer;
                     sonunda tek bir özet bildirimi kendileri gönderir.

        Returns:
            {"accepted": N, "rejected": N, "duplicate": N, "run_id": run_id}

        Raises:
            FileNotFoundError: run_dir veya meta.json bulunamazsa.
            ValueError: Proje DB'de bulunamazsa.
        """
        from ...store.repositories.project_repo import project_get
        from ...features.orchestrator.core import AgentLifecycleManager
        from ...adapters.llm.llm_factory import get_scan_llm

        run_dir = resolve_run_dir(run_id, _RUNS_DIR)
        meta_path = run_dir / "meta.json"

        if not meta_path.exists():
            raise FileNotFoundError(
                f"ReviewerAgent: meta.json bulunamadı run_id={run_id!r}"
            )

        # meta.json'u oku
        meta: dict = json.loads(meta_path.read_text(encoding="utf-8"))
        scan_type: str = meta["scan_type"]
        project_id: str = meta["project_id"]
        # dry_run: meta'daki değer geçerli; caller override edebilir
        effective_dry_run: bool = meta.get("dry_run", dry_run) or dry_run
        started_at = time.time()

        # Proje doğrulama
        project = await project_get(project_id)
        if project is None:
            raise ValueError(f"Proje bulunamadı: {project_id!r}")

        project_root: str = project.get("path", meta.get("project_path", ""))
        if not project_root:
            raise ValueError(
                f"ReviewerAgent: proje yolu boş — backlog yazımı yapılamaz "
                f"project_id={project_id!r}"
            )
        backlog_path = Path(project_root) / "BACKLOG.md"

        lifecycle = AgentLifecycleManager()
        agent_run_id: str | None = None

        try:
            agent_run_id = await lifecycle.start_run(
                agent_type="reviewer",
                session_id=f"reviewer_{run_id[:8]}",
                project_id=project_id,
                source="internal",
            )
            await lifecycle.mark_running(agent_run_id)
        except Exception as _err:
            logger.warning("ReviewerAgent: agent run kaydedilemedi: %s", _err)

        pipeline = self._get_pipeline()
        llm = get_scan_llm(model=review_model, effort=review_effort, thinking=review_thinking)

        try:
            config = self._get_config_loader().load(scan_type)

            # Findings topla, reviewer prompt üret
            findings, reviewer_prompt = pipeline.collect_and_build_reviewer_prompt(
                config, run_dir, project_root, backlog_path
            )

            if not findings:
                logger.info(
                    "ReviewerAgent: bulgu yok — review atlanıyor run_id=%s", run_id
                )
                review_result: dict = {
                    "run_id": run_id,
                    "accepted": 0,
                    "rejected": 0,
                    "duplicate": 0,
                }
                (run_dir / "review.jsonl").write_text(
                    json.dumps([], ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if agent_run_id:
                    await lifecycle.mark_completed(agent_run_id, output="0 bulgu")
                return review_result

            # Bulgular batch'lere bölünür; her batch için ayrı LLM çağrısı
            from .reviewer import FindingReviewer
            reviewer_obj = FindingReviewer(run_dir, backlog_path)
            all_reviewed = await self._run_batch_review(
                findings, config, reviewer_obj, llm,
                run_id=run_id, run_dir=run_dir,
            )

            # Finalize — backlog yaz, ScanResult döndür
            scan_result = pipeline.finalize_from_reviewed(
                config=config,
                run_dir=run_dir,
                findings=findings,
                reviewed=all_reviewed,
                backlog_path=backlog_path,
                run_id=run_id,
                project_id=project_id,
                project_path=project_root,
                started_at=started_at,
                dry_run=effective_dry_run,
            )

            # meta.json'u güncelle: status ve verdict sayıları
            meta.update(
                {
                    "status": "reviewed",
                    "accepted": scan_result["accepted"],
                    "rejected": scan_result["rejected"],
                    "duplicate": scan_result["duplicate"],
                    "reviewed_at": time.time(),
                }
            )
            meta_path.write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            output_summary = (
                f"accepted={scan_result['accepted']} "
                f"rejected={scan_result['rejected']}"
            )
            logger.info("ReviewerAgent: tamamlandı run_id=%s %s", run_id, output_summary)

            if agent_run_id:
                await lifecycle.mark_completed(agent_run_id, output=output_summary)

            # Kullanıcıya tamamlanma bildirimi gönder (orchestrator'lar bunu kapatır)
            if notify:
                try:
                    from ...adapters.messenger import get_messenger
                    from ...config import settings
                    from ...i18n import t
                    lang = "tr"
                    owner = settings.owner_id
                    project_name = project.get("name", project_id)
                    severity_breakdown = _build_severity_breakdown(all_reviewed)
                    backlog_ids = _collect_backlog_ids(all_reviewed)
                    await get_messenger().send_text(
                        owner,
                        t(
                            "scan.reviewer_done_rich",
                            lang,
                            scan_type=scan_type,
                            project=project_name,
                            accepted=scan_result["accepted"],
                            rejected=scan_result["rejected"],
                            severity_breakdown=severity_breakdown,
                            backlog_ids=backlog_ids or "—",
                        ),
                    )
                except Exception as _notify_err:
                    logger.warning("ReviewerAgent: bildirim gönderilemedi: %s", _notify_err)

            return {
                "accepted": scan_result["accepted"],
                "rejected": scan_result["rejected"],
                "duplicate": scan_result["duplicate"],
                "run_id": run_id,
            }

        except Exception as exc:
            logger.error("ReviewerAgent: başarısız run_id=%s hata=%s", run_id, exc)
            if agent_run_id:
                try:
                    await lifecycle.mark_failed(agent_run_id, error_msg=str(exc))
                except Exception as _mark_err:
                    logger.warning(
                        "ReviewerAgent: mark_failed başarısız: %s", _mark_err
                    )
            raise

    async def _run_batch_review(
        self,
        findings: list,
        config,
        reviewer_obj,
        llm,
        batch_size: int = _REVIEW_BATCH_SIZE,
        run_id: str = "",
        run_dir: Path | None = None,
    ) -> list:
        """Bulgular batch_size'lık gruplara bölünerek her grup için ayrı LLM çağrısı yapar.

        Her batch bağımsız parse edilir; başarısız batch'ler uyarı loglanır, atlanmaz.
        Tüm batch sonuçları birleştirilerek döndürülür.
        Pause: her batch sonrasında pause flag'i kontrol edilir; o ana kadar işlenen
        bulgular review_partial.jsonl'a yazılır ve beklenir.
        Resume: tamamlanan batch'ler (checkpoint) atlanır; kalan batch'ler işlenir.
        """
        import asyncio  # noqa: PLC0415 — zaten üst scope'ta ama içeride güvenli

        all_reviewed: list = []
        # Cross-batch duplicate tespiti: kabul edilen bulguların (file, title) fingerprint'leri
        seen_accepted: list[tuple[str, str]] = []
        total = len(findings)
        batches = [findings[i:i + batch_size] for i in range(0, total, batch_size)]

        # Toplam batch sayısını state'e yaz — UI (dashboard / /scan durum)
        # progress bar bu değeri kullanır. mark_batch_done() phase'i "reviewer"
        # yapsa da total bilgisi sadece burada hesaplanıyor.
        if run_id:
            try:
                ScanPauseStore.set_total_batches(run_id, len(batches))
            except Exception as _stp_err:  # noqa: BLE001
                logger.debug(
                    "ReviewerAgent: set_total_batches başarısız (%s) — UI progress yine completed sayar.",
                    _stp_err,
                )

        # Resume: tamamlanan batch'leri yükle
        completed_batches: set[int] = (
            ScanPauseStore.get_completed_batches(run_id) if run_id else set()
        )
        # Resolve run_dir for partial/raw file paths (legacy + nested layout)
        if run_dir is None and run_id:
            run_dir = resolve_run_dir(run_id, _RUNS_DIR)

        if completed_batches:
            # Partial sonuçları yükle ve fingerprint'leri yeniden oluştur
            partial_path = (run_dir / "review_partial.jsonl") if run_dir else None
            if partial_path and partial_path.exists():
                try:
                    loaded = json.loads(partial_path.read_text(encoding="utf-8"))
                    all_reviewed.extend(loaded)
                    for rv in loaded:
                        if rv.get("verdict") == "accepted":
                            f = rv["finding"]
                            fp = (f.get("file", ""), f.get("title", ""))
                            if fp not in seen_accepted:
                                seen_accepted.append(fp)
                    logger.info(
                        "ReviewerAgent: resume — %d tamamlanmış batch, %d bulgu yüklendi",
                        len(completed_batches), len(all_reviewed),
                    )
                except Exception as _load_err:
                    logger.warning(
                        "ReviewerAgent: review_partial.jsonl yüklenemedi: %s", _load_err
                    )

        logger.info(
            "ReviewerAgent: %d bulgu → %d batch (batch_size=%d)",
            total, len(batches), batch_size,
        )

        for batch_idx, batch in enumerate(batches):
            # Resume: tamamlanmış batch'leri atla (0-indexed batch_idx)
            if batch_idx in completed_batches:
                logger.debug("ReviewerAgent: batch %d zaten tamamlandı, atlanıyor", batch_idx)
                continue

            idx = batch_idx + 1  # Log için 1-indexed
            logger.info(
                "ReviewerAgent: batch %d/%d — %d bulgu işleniyor",
                idx, len(batches), len(batch),
            )
            try:
                prompt = reviewer_obj.build_reviewer_prompt(
                    config, batch,
                    already_accepted=seen_accepted if seen_accepted else None,
                )
                # Her 50 bulgu için ~50×25=1250 token output yeterli; 2048 güvenli üst sınır
                result = await llm.complete(
                    messages=[{"role": "user", "content": prompt}],
                    model=None,
                    max_tokens=2048,
                )
                # Diagnostik: raw LLM çıktısını diske yaz — parse fail durumunda geriye dönük inceleme için
                if run_dir:
                    try:
                        raw_path = run_dir / f"review_raw_batch_{batch_idx:03d}.txt"
                        raw_path.write_text(result.text, encoding="utf-8")
                    except Exception as _raw_err:
                        logger.warning(
                            "ReviewerAgent: raw çıktı yazılamadı batch=%d: %s",
                            batch_idx, _raw_err,
                        )
                # TOKEN-PER-ITEM-1: per-batch token kullanımını kaydet
                if run_id and result.input_tokens > 0:
                    try:
                        from ...store.repositories import token_stat_repo
                        await token_stat_repo.record_task_usage(
                            task_id=f"{run_id}_b{batch_idx:03d}",
                            task_type="reviewer_batch",
                            run_id=run_id,
                            model_id=result.model_id,
                            model_name=result.model_name,
                            backend=result.backend,
                            input_tokens=result.input_tokens,
                            output_tokens=result.output_tokens,
                            cache_read=result.cache_read_input_tokens,
                            cache_write=result.cache_creation_input_tokens,
                        )
                    except Exception as _te:
                        logger.warning(
                            "ReviewerAgent: per-batch token kaydı başarısız (batch=%d): %s",
                            batch_idx, _te,
                        )

                reviewed_batch = reviewer_obj.parse_review_output(result.text, batch)
                # Parse edilemeyen bulguları logla
                unparsed = [
                    r for r in reviewed_batch if r.get("reason") == "(parse edilemedi)"
                ]
                if unparsed:
                    logger.warning(
                        "ReviewerAgent: batch %d/%d — %d/%d bulgu parse edilemedi "
                        "(raw: review_raw_batch_%03d.txt)",
                        idx, len(batches), len(unparsed), len(reviewed_batch), batch_idx,
                    )
                all_reviewed.extend(reviewed_batch)

                # Kabul edilen bulguların fingerprint'lerini bir sonraki batch için kaydet
                for rv in reviewed_batch:
                    if rv.get("verdict") == "accepted":
                        f = rv["finding"]
                        fp = (f.get("file", ""), f.get("title", ""))
                        if fp not in seen_accepted:
                            seen_accepted.append(fp)

                if run_id:
                    ScanPauseStore.mark_batch_done(run_id, batch_idx)

                logger.info(
                    "ReviewerAgent: batch %d/%d tamamlandı — %d verdict",
                    idx, len(batches), len(reviewed_batch),
                )
            except Exception as exc:
                logger.error(
                    "ReviewerAgent: batch %d/%d başarısız — %s", idx, len(batches), exc
                )

            # Pause kontrolü — batch sonrasında; duraklatıldığında kısmi sonuçları kaydet
            if run_id and run_dir and ScanPauseStore.is_paused(run_id):
                partial_path = run_dir / "review_partial.jsonl"
                try:
                    partial_path.write_text(
                        json.dumps(all_reviewed, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    logger.info(
                        "ReviewerAgent: pause — %d review sonucu review_partial.jsonl'a kaydedildi",
                        len(all_reviewed),
                    )
                except Exception as _save_err:
                    logger.warning(
                        "ReviewerAgent: review_partial.jsonl kaydedilemedi: %s", _save_err
                    )
                # Resume olana kadar bekle
                while ScanPauseStore.is_paused(run_id):
                    await asyncio.sleep(2.0)
                logger.info("ReviewerAgent: resume — batch işlemeye devam ediliyor")

        return all_reviewed
