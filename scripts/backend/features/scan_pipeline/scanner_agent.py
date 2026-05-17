"""ScannerAgent — sadece tarama fazını çalıştırır (reviewer ayrı).

ScanRunner ile fark: Reviewer çağrılmaz; bulgular disk'e yazılır.
auto_review=True ise tamamlanınca ReviewerAgent otomatik tetiklenir.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

from .config_loader import ScanConfigLoader
from .pipeline import ScanPipeline

logger = logging.getLogger(__name__)

# Dosya başına maksimum karakter — token bütçesini korumak için
_MAX_CHARS_PER_FILE = 4_000


class ScannerAgent:
    """Scan pipeline'ının yalnızca tarama (scanner) fazını çalıştırır.

    DIP: get_llm() fabrikası üzerinden abstract LLMProvider kullanır.
    SRP: Yalnızca scanner koordinasyonu — reviewer ayrı ReviewerAgent'ta.
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
        auto_review: bool = True,
        dry_run: bool = False,
    ) -> str:
        """Tarama fazını başlatır, bulgular diske yazılır, run_id döndürür.

        Args:
            scan_type:   data/scan_configs/{scan_type}.json ile eşleşen tip.
            project_id:  DB'deki proje ID'si; project_root yolu buradan alınır.
            auto_review: True ise scanner bittikten sonra ReviewerAgent otomatik tetiklenir.
            dry_run:     True ise BACKLOG.md'ye yazma — ReviewerAgent'a iletilir.

        Returns:
            run_id (str) — caller veya ReviewerAgent bu ID ile bulguları okur.

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

        lifecycle = AgentLifecycleManager()
        agent_run_id: str | None = None

        try:
            agent_run_id = await lifecycle.start_run(
                agent_type="scanner",
                session_id=f"scanner_{scan_type}_{project_id}",
                project_id=project_id,
                source="internal",
                prompt=f"scan_type={scan_type}",
            )
            await lifecycle.mark_running(agent_run_id)
        except Exception as _err:
            logger.warning("ScannerAgent: agent run kaydedilemedi: %s", _err)

        pipeline = self._get_pipeline()
        llm = get_llm()

        try:
            # Phase 1 — prompt listesi üret
            config, chunk_prompts, run_dir = pipeline.build_scanner_prompts(
                scan_type, project_root, run_id
            )

            if not chunk_prompts:
                logger.info("ScannerAgent: taranacak dosya bulunamadı — boş sonuç")
                meta = {
                    "run_id": run_id,
                    "scan_type": scan_type,
                    "project_id": project_id,
                    "project_path": project_root,
                    "status": "scanned",
                    "started_at": started_at,
                    "dry_run": dry_run,
                }
                run_dir.mkdir(parents=True, exist_ok=True)
                (run_dir / "meta.json").write_text(
                    json.dumps(meta, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if agent_run_id:
                    await lifecycle.mark_completed(
                        agent_run_id, output="scanner tamamlandı run_id=" + run_id
                    )
                return run_id

            # Phase 1 — chunk'ları paralel LLM çağrısıyla çalıştır
            await self._run_scanner_chunks(chunk_prompts, llm, run_dir)

            # Ara meta bilgisini yaz (ReviewerAgent tarafından okunur)
            findings_count = len(list(run_dir.glob("findings/*.jsonl")))
            meta = {
                "run_id": run_id,
                "scan_type": scan_type,
                "project_id": project_id,
                "project_path": project_root,
                "status": "scanned",
                "started_at": started_at,
                "dry_run": dry_run,
                "findings_count_approx": findings_count,
            }
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

            logger.info(
                "ScannerAgent: scanner tamamlandı run_id=%s findings_approx=%d",
                run_id, findings_count,
            )

            if agent_run_id:
                await lifecycle.mark_completed(
                    agent_run_id, output=f"scanner tamamlandı run_id={run_id}"
                )

            if auto_review:
                # Lazy import — circular import riski yok (ayrı modül)
                from .reviewer_agent import ReviewerAgent  # noqa: PLC0415
                await ReviewerAgent().run(run_id, dry_run=dry_run)

            return run_id

        except Exception as exc:
            logger.error("ScannerAgent: başarısız run_id=%s hata=%s", run_id, exc)
            if agent_run_id:
                try:
                    await lifecycle.mark_failed(agent_run_id, error_msg=str(exc))
                except Exception as _mark_err:
                    logger.warning("ScannerAgent: mark_failed başarısız: %s", _mark_err)
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
                logger.error("ScannerAgent: chunk %d başarısız — %s", i, res)

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
            "ScannerAgent: chunk %d — %d dosya, %d karakter prompt",
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
            "ScannerAgent: chunk %d tamamlandı — %d output token",
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
