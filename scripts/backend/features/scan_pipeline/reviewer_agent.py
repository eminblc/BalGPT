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
from .pipeline import ScanPipeline

logger = logging.getLogger(__name__)

_RUNS_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "scan_runs"
_BACKLOG_PATH = Path(__file__).parent.parent.parent.parent.parent / "BACKLOG.md"


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
    ) -> dict:
        """Verilen run_id için review fazını çalıştırır.

        Args:
            run_id:  ScannerAgent tarafından oluşturulan run ID.
            dry_run: True ise BACKLOG.md'ye yazma, yalnızca analiz yap.
                     meta.json'daki dry_run değeri ile override edilir.

        Returns:
            {"accepted": N, "rejected": N, "duplicate": N, "run_id": run_id}

        Raises:
            FileNotFoundError: run_dir veya meta.json bulunamazsa.
            ValueError: Proje DB'de bulunamazsa.
        """
        from ...store.repositories.project_repo import project_get
        from ...features.orchestrator.core import AgentLifecycleManager
        from ...adapters.llm.llm_factory import get_llm

        run_dir = _RUNS_DIR / run_id
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
        llm = get_llm()

        try:
            config = self._get_config_loader().load(scan_type)

            # Findings topla, reviewer prompt üret
            findings, reviewer_prompt = pipeline.collect_and_build_reviewer_prompt(
                config, run_dir, project_root, _BACKLOG_PATH
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

            # LLM çağrısı
            reviewer_result = await llm.complete(
                messages=[{"role": "user", "content": reviewer_prompt}],
                model=None,
                max_tokens=4096,
            )
            logger.info(
                "ReviewerAgent: reviewer tamamlandı — %d bulgu incelendi run_id=%s",
                len(findings), run_id,
            )

            # Finalize — parse, backlog yaz, ScanResult döndür
            scan_result = pipeline.finalize(
                config=config,
                run_dir=run_dir,
                findings=findings,
                reviewer_output=reviewer_result.text,
                backlog_path=_BACKLOG_PATH,
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
