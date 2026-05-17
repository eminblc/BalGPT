"""ScanRunner — scan pipeline'ını doğrudan LLM adapter üzerinden yürütür.

Bridge / Agent tool overhead'i olmadan FastAPI endpoint veya scheduler tarafından
tetiklenebilen koordinasyon sınıfı. SRP: yalnızca koordinasyon; parsing/writing
mantığı ilgili sınıflarda kalır.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path

from .config_loader import ScanConfigLoader
from .models import ScanResult
from .pipeline import ScanPipeline
from .scanner import ScannerOrchestrator

logger = logging.getLogger(__name__)

# Proje kök dizini göre BACKLOG yolu
_PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
_BACKLOG_PATH = _PROJECT_ROOT / "BACKLOG.md"

# Dosya başına maksimum karakter — token bütçesini korumak için
_MAX_CHARS_PER_FILE = 4_000


class ScanRunner:
    """Scan pipeline'ı LLM adapter üzerinden doğrudan çalıştırır.

    DIP: get_llm() fabrikası üzerinden abstract LLMProvider kullanır.
    SRP: Yalnızca çalıştırma koordinasyonu — parsing/writing pipeline sınıflarında.
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
        scan_type: str,
        project_id: str,
        dry_run: bool = False,
    ) -> ScanResult:
        """Taramayı başlatır, LLM çağrıları yapar, ScanResult döndürür.

        Args:
            scan_type:  data/scan_configs/{scan_type}.json ile eşleşen tip.
            project_id: DB'deki proje ID'si; project_root yolu buradan alınır.
            dry_run:    True ise BACKLOG.md'ye yazma, yalnızca analiz yap.

        Returns:
            Tamamlanan veya başarısız ScanResult.

        Raises:
            ValueError: Proje DB'de bulunamazsa (agent run işaretlenmeden önce).
        """
        from ...store.repositories.project_repo import project_get
        from ...features.orchestrator.core import AgentLifecycleManager
        from ...adapters.llm.llm_factory import get_llm

        # Proje doğrulama — erken hata, agent run kaydedilmeden önce
        project = await project_get(project_id)
        if project is None:
            raise ValueError(f"Proje bulunamadı: {project_id!r}")

        project_root = project.get("path", "")
        if not project_root:
            raise ValueError(f"Proje yolu boş: {project_id!r}")

        run_id = str(uuid.uuid4())
        started_at = time.time()
        session_id = f"scan_{scan_type}_{project_id}"

        lifecycle = AgentLifecycleManager()
        agent_run_id: str | None = None

        try:
            agent_run_id = await lifecycle.start_run(
                agent_type="scan_pipeline",
                session_id=session_id,
                project_id=project_id,
                source="internal",
                prompt=f"scan_type={scan_type} dry_run={dry_run}",
            )
            await lifecycle.mark_running(agent_run_id)
        except Exception as _err:
            logger.warning("ScanRunner: agent run kaydedilemedi: %s", _err)

        pipeline = self._get_pipeline()
        llm = get_llm()

        try:
            # Phase 1 — prompt listesi üret
            config, chunk_prompts, run_dir = pipeline.build_scanner_prompts(
                scan_type, project_root, run_id
            )

            if not chunk_prompts:
                logger.info("ScanRunner: taranacak dosya bulunamadı — boş sonuç")
                result = self._empty_result(run_id, scan_type, project_id, project_root, started_at)
                pipeline._write_meta(run_dir, result)
                if agent_run_id:
                    await lifecycle.mark_completed(agent_run_id, output="0 dosya, 0 bulgu")
                return result

            # Phase 1 — chunk'ları paralel LLM çağrısıyla çalıştır
            await self._run_scanner_chunks(chunk_prompts, llm, run_dir)

            # Phase 2 — findings topla, reviewer prompt üret
            findings, reviewer_prompt = pipeline.collect_and_build_reviewer_prompt(
                config, run_dir, project_root, _BACKLOG_PATH
            )

            reviewer_output = ""
            if findings:
                reviewer_result = await llm.complete(
                    messages=[{"role": "user", "content": reviewer_prompt}],
                    model=None,
                    max_tokens=4096,
                )
                reviewer_output = reviewer_result.text
                logger.info(
                    "ScanRunner: reviewer tamamlandı — %d bulgu incelendi",
                    len(findings),
                )
            else:
                logger.info("ScanRunner: bulgu yok — reviewer atlanıyor")

            # Phase 3 — finalize (parse, backlog yaz, ScanResult)
            result = pipeline.finalize(
                config=config,
                run_dir=run_dir,
                findings=findings,
                reviewer_output=reviewer_output,
                backlog_path=_BACKLOG_PATH,
                run_id=run_id,
                project_id=project_id,
                project_path=project_root,
                started_at=started_at,
                dry_run=dry_run,
            )

            summary = (
                f"accepted={result['accepted']} rejected={result['rejected']} "
                f"duplicate={result['duplicate']} total={result['total_findings']}"
            )
            logger.info("ScanRunner: tamamlandı run_id=%s %s", run_id, summary)

            if agent_run_id:
                await lifecycle.mark_completed(agent_run_id, output=summary)

            return result

        except Exception as exc:
            logger.error("ScanRunner: başarısız run_id=%s hata=%s", run_id, exc)
            if agent_run_id:
                try:
                    await lifecycle.mark_failed(agent_run_id, error_msg=str(exc))
                except Exception as _mark_err:
                    logger.warning("ScanRunner: mark_failed başarısız: %s", _mark_err)
            raise

    async def _run_scanner_chunks(
        self,
        chunk_prompts: list[dict],
        llm,
        run_dir: Path,
    ) -> None:
        """Chunk prompt'larını paralel LLM çağrılarıyla çalıştırır.

        Her chunk için dosya içeriklerini okur, LLM'e gönderir, çıktıyı kaydeder.
        Tek bir chunk'ın başarısızlığı diğerlerini durdurmaz.
        """
        tasks = [
            self._run_single_chunk(chunk, llm)
            for chunk in chunk_prompts
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(
                    "ScanRunner: chunk %d başarısız — %s", i, res
                )

    async def _run_single_chunk(self, chunk: dict, llm) -> None:
        """Tek bir chunk'ı LLM ile çalıştırır ve sonucu kaydeder.

        chunk dict anahtarları:
          - chunk_index: int
          - files:       list[str]  — taranacak dosya yolları
          - prompt:      str        — scanner sistem prompt'u
          - output_file: str        — sonucun yazılacağı .jsonl yolu
        """
        chunk_index: int = chunk["chunk_index"]
        files: list[str] = chunk["files"]
        base_prompt: str = chunk["prompt"]
        output_file: str = chunk["output_file"]

        # Dosya içeriklerini oku ve prompt'a ekle
        file_sections = await asyncio.get_event_loop().run_in_executor(
            None, self._read_files_sync, files
        )
        full_prompt = base_prompt + "\n\n## Dosya İçerikleri\n" + file_sections

        logger.debug(
            "ScanRunner: chunk %d — %d dosya, %d karakter prompt",
            chunk_index, len(files), len(full_prompt),
        )

        result = await llm.complete(
            messages=[{"role": "user", "content": full_prompt}],
            model=None,
            max_tokens=2048,
        )

        # output_file dizinini oluştur ve sonucu kaydet
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(result.text, encoding="utf-8")

        logger.debug(
            "ScanRunner: chunk %d tamamlandı — %d output token",
            chunk_index, result.output_tokens,
        )

    @staticmethod
    def _read_files_sync(files: list[str]) -> str:
        """Dosya içeriklerini okur, her dosyayı _MAX_CHARS_PER_FILE ile sınırlar.

        Executor üzerinden çağrılır (sync I/O → asyncio uyumu).
        """
        parts: list[str] = []
        for file_path in files:
            path = Path(file_path)
            if not path.exists():
                parts.append(f"=== {file_path} ===\n(dosya bulunamadı)\n")
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
                if len(content) > _MAX_CHARS_PER_FILE:
                    content = content[:_MAX_CHARS_PER_FILE] + "\n... (kesildi)"
                parts.append(f"=== {file_path} ===\n{content}\n")
            except OSError as exc:
                parts.append(f"=== {file_path} ===\n(okuma hatası: {exc})\n")
        return "\n".join(parts)

    @staticmethod
    def _empty_result(
        run_id: str,
        scan_type: str,
        project_id: str,
        project_path: str,
        started_at: float,
    ) -> ScanResult:
        return {
            "run_id": run_id,
            "scan_type": scan_type,
            "project_id": project_id,
            "project_path": project_path,
            "started_at": started_at,
            "completed_at": time.time(),
            "status": "completed",
            "total_findings": 0,
            "accepted": 0,
            "rejected": 0,
            "duplicate": 0,
            "output_dir": "",
        }
