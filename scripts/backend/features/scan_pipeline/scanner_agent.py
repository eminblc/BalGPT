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
from .scan_pause_store import ScanPauseStore

logger = logging.getLogger(__name__)

# Bridge'e eş zamanlı gidecek maksimum chunk sayısı
_BRIDGE_CONCURRENCY = 3


def _strip_json_fence(text: str) -> str:
    """LLM çıktısındaki markdown code fence'i soyar (```json...``` → içerik)."""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1:]
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


class FileContentCache:
    """Dosya içeriklerini belleğe alır.

    AllScansRunner gibi çoklu tarama senaryolarında aynı dosyanın
    her scan tipi için diskten tekrar okunmasını önler.
    Thread-safe: GIL, dict get/set operasyonlarını korur.
    """

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def read(self, file_path: str, max_chars: int) -> str:
        """Dosyayı cache'den döndürür; cache miss ise diskten okuyup saklar."""
        if file_path in self._cache:
            return self._cache[file_path]

        path = Path(file_path)
        if not path.exists():
            result = "(dosya bulunamadı)"
        else:
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
                result = (raw[:max_chars] + "\n... (kesildi)") if len(raw) > max_chars else raw
            except OSError as exc:
                result = f"(okuma hatası: {exc})"

        self._cache[file_path] = result
        return result


class ScannerAgent:
    """Scan pipeline'ının yalnızca tarama (scanner) fazını çalıştırır.

    DIP: get_llm() fabrikası üzerinden abstract LLMProvider kullanır.
    SRP: Yalnızca scanner koordinasyonu — reviewer ayrı ReviewerAgent'ta.
    """

    def __init__(self, file_cache: FileContentCache | None = None) -> None:
        # Lazy-load — servis başlarken import hatası vermemek için
        self._pipeline: ScanPipeline | None = None
        self._config_loader: ScanConfigLoader | None = None
        self._file_cache: FileContentCache = file_cache or FileContentCache()

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
        parallel: int | None = None,
        include_third_party: bool = False,
        notify_on_review: bool = True,
        scan_model: str | None = None,
        review_model: str | None = None,
        scan_effort: str | None = None,
        review_effort: str | None = None,
        scan_thinking: bool = False,
        review_thinking: bool = False,
        run_id: str | None = None,
    ) -> str:
        """Tarama fazını başlatır, bulgular diske yazılır, run_id döndürür.

        Args:
            scan_type:            data/scan_configs/{scan_type}.json ile eşleşen tip.
            project_id:           DB'deki proje ID'si; project_root yolu buradan alınır.
            auto_review:          True ise scanner bittikten sonra ReviewerAgent otomatik tetiklenir.
            dry_run:              True ise BACKLOG.md'ye yazma — ReviewerAgent'a iletilir.
            parallel:             Eş zamanlı LLM chunk çağrısı (kullanıcı seçimi).
                                  None → config'deki concurrency, o da yoksa 3.
            include_third_party:  True ise node_modules/venv/.venv/vendor exclude edilmez.
            notify_on_review:     False ise ReviewerAgent tamamlanma bildirimi göndermez.
                                  AllScansRunner gibi orchestrator'lar False geçer; özeti
                                  kendileri gönderir.
            scan_model:           Opsiyonel model alias ("haiku", "sonnet", "sonnet5", "opus", "fable")
                                  veya tam ad. Verilmezse get_scan_llm() varsayılan modeli kullanır.
            review_model:         Opsiyonel reviewer model alias ("haiku", "sonnet", "sonnet5", "opus", "fable").
                                  Verilmezse ReviewerAgent varsayılan modeli kullanır.
            scan_effort:          Opsiyonel scanner effort seviyesi
                                  ("low" | "medium" | "high" | "max").
            review_effort:        Opsiyonel reviewer effort seviyesi.
                                  ReviewerAgent.run() üzerinden iletilir.
            scan_thinking:        Scanner için Extended Thinking on/off toggle.
                                  False (varsayılan) iken effort seçili olsa bile
                                  gönderilmez (VS Code UX'iyle birebir aynı).
            review_thinking:      Reviewer için Extended Thinking on/off toggle.
            run_id:               Opsiyonel run ID. Verilirse mevcut state.json'dan resume edilir
                                  (restart-safe resume senaryosu). None ise yeni ID üretilir.

        Returns:
            run_id (str) — caller veya ReviewerAgent bu ID ile bulguları okur.

        Raises:
            ValueError: Proje DB'de bulunamazsa (agent run işaretlenmeden önce).
        """
        from ...store.repositories.project_repo import project_get
        from ...features.orchestrator.core import AgentLifecycleManager
        from ...adapters.llm.llm_factory import get_scan_llm
        from ...guards.runtime_state import set_active_scan_run_id

        # Proje doğrulama — erken hata, agent run kaydedilmeden önce
        project = await project_get(project_id)
        if project is None:
            raise ValueError(f"Proje bulunamadı: {project_id!r}")

        project_root = project.get("path", "")
        if not project_root:
            raise ValueError(f"Proje yolu boş: {project_id!r}")

        run_id = run_id or str(uuid.uuid4())
        started_at = time.time()
        set_active_scan_run_id(run_id)

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
        llm = get_scan_llm(model=scan_model, effort=scan_effort, thinking=scan_thinking)

        try:
            # Pause/checkpoint state dosyasını başlat (mevcut ise resume, değilse yeni)
            ScanPauseStore.init_state(
                run_id=run_id,
                scan_type=scan_type,
                project_id=project_id,
                started_at=started_at,
                phase="scanner",
            )

            # Phase 1 — prompt listesi üret
            config, chunk_prompts, run_dir = pipeline.build_scanner_prompts(
                scan_type, project_root, run_id,
                include_third_party=include_third_party,
                project_id=project_id,
            )

            # Resume: tamamlanan chunk'ları filtrele (restart-safe)
            completed_chunks = ScanPauseStore.get_completed_chunks(run_id)
            if completed_chunks:
                original_count = len(chunk_prompts)
                chunk_prompts = [
                    c for c in chunk_prompts
                    if c["chunk_index"] not in completed_chunks
                ]
                logger.info(
                    "ScannerAgent: resume — %d chunk tamamlanmış, %d chunk kaldı",
                    len(completed_chunks), len(chunk_prompts),
                )

            total_chunks = len(chunk_prompts)
            logger.info(
                "ScannerAgent: tarama başladı — toplam %d chunk, proje=%s, scan_type=%s",
                total_chunks, project_id, scan_type,
            )

            # İlerleme takibi için progress.json yaz (status endpoint okur)
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "progress.json").write_text(
                json.dumps({
                    "total_chunks": total_chunks,
                    "scan_type":    scan_type,
                    "project_id":   project_id,
                    "started_at":   started_at,
                }, ensure_ascii=False),
                encoding="utf-8",
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
            # Kullanıcının seçtiği parallel değeri (UI'daki 1/2/4/8/... seçimi)
            # config'deki concurrency'yi ezer; parallel verilmemişse (None)
            # config değeri, o da yoksa modül varsayılanı kullanılır.
            # (Önceki davranış tersti: tüm config'lerde concurrency=5 tanımlı
            # olduğu için kullanıcı seçimi hiçbir zaman etkili olmuyordu.)
            concurrency = (
                parallel if parallel is not None
                else config.get("concurrency", _BRIDGE_CONCURRENCY)
            )
            await self._run_scanner_chunks(
                chunk_prompts, llm, run_dir, concurrency,
                max_chars_per_file=config.get("max_chars_per_file", 8_000),
                max_output_tokens=config.get("max_output_tokens", 2_048),
                run_id=run_id,
            )

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
                await ReviewerAgent().run(
                    run_id, dry_run=dry_run, notify=notify_on_review,
                    review_model=review_model,
                    review_effort=review_effort,
                    review_thinking=review_thinking,
                )

            # Aktif run_id review fazı da bittikten sonra temizlenir — daha erken
            # temizlenirse /scan pause reviewer fazında ScanPauseStore'a run_id
            # iletemez ve pause sessizce etkisiz kalır.
            set_active_scan_run_id(None)

            return run_id

        except Exception as exc:
            logger.error("ScannerAgent: başarısız run_id=%s hata=%s", run_id, exc)
            set_active_scan_run_id(None)
            if agent_run_id:
                try:
                    await lifecycle.mark_failed(agent_run_id, error_msg=str(exc))
                except Exception as _mark_err:
                    logger.warning("ScannerAgent: mark_failed başarısız: %s", _mark_err)
            try:
                from ...adapters.messenger import get_messenger
                from ...config import settings
                owner = settings.owner_id
                await get_messenger().send_text(
                    owner,
                    f"❌ Scan başarısız — {scan_type} / {project_id}\n{exc}",
                )
            except Exception as _notify_err:
                logger.warning("ScannerAgent: bildirim gönderilemedi: %s", _notify_err)
            raise

    async def _run_scanner_chunks(
        self,
        chunk_prompts: list[dict],
        llm,
        run_dir: Path,
        parallel: int = _BRIDGE_CONCURRENCY,
        max_chars_per_file: int = 8_000,
        max_output_tokens: int = 2_048,
        run_id: str = "",
    ) -> None:
        """Chunk prompt'larını sınırlı paralellikte Bridge üzerinden çalıştırır.

        parallel semaphore'u ile eş zamanlı Bridge çağrısı kısıtlanır.
        Tüm chunk'lar başarısızsa ilk hatayı yeniden fırlatır.
        İptal flag'i set edilmişse kalan chunk'lar atlanır.
        Pause flag'i set edilmişse mevcut chunk biter, sonraki başlamaz (wait loop).
        """
        from ...guards.runtime_state import is_scan_cancel_requested

        total = len(chunk_prompts)
        sem = asyncio.Semaphore(parallel)
        completed = 0
        start_time = time.time()
        lock = asyncio.Lock()

        async def _guarded(chunk: dict, idx: int) -> None:
            nonlocal completed
            # Pause bekle — semaphore almadan önce; cancel gelirse çık
            while run_id and ScanPauseStore.is_paused(run_id):
                if is_scan_cancel_requested():
                    logger.info("ScannerAgent: iptal istendi (pause beklerken)")
                    return
                logger.debug(
                    "ScannerAgent: chunk %d pause bekliyor run_id=%s", idx, run_id
                )
                await asyncio.sleep(2.0)

            # İptal kontrolü — semaphore'a girmeden önce
            if is_scan_cancel_requested():
                logger.info(
                    "ScannerAgent: iptal istendi, kalan %d chunk atlanıyor",
                    total - idx,
                )
                return
            async with sem:
                if is_scan_cancel_requested():
                    logger.info(
                        "ScannerAgent: iptal istendi, kalan %d chunk atlanıyor",
                        total - idx,
                    )
                    return
                await self._run_single_chunk(
                    chunk, llm,
                    max_chars_per_file=max_chars_per_file,
                    max_output_tokens=max_output_tokens,
                    run_id=run_id,
                )
                if run_id:
                    ScanPauseStore.mark_chunk_done(run_id, chunk["chunk_index"])
                async with lock:
                    completed += 1
                    elapsed = time.time() - start_time
                    estimated_remaining = (
                        (elapsed / completed) * (total - completed)
                        if completed > 0 else 0.0
                    )
                    logger.info(
                        "ScannerAgent: ilerleme %d/%d chunk — geçen %.1fs, tahmini %.1fs kaldı",
                        completed, total, elapsed, estimated_remaining,
                    )

        tasks = [_guarded(chunk, i) for i, chunk in enumerate(chunk_prompts)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        errors: list[Exception] = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error("ScannerAgent: chunk %d başarısız — %s", i, res)
                errors.append(res)

        if errors and len(errors) == len(chunk_prompts):
            raise errors[0]

    async def _run_single_chunk(
        self,
        chunk: dict,
        llm,
        max_chars_per_file: int = 8_000,
        max_output_tokens: int = 2_048,
        run_id: str = "",
    ) -> None:
        """Tek bir chunk'ı LLM ile çalıştırır ve sonucu kaydeder.

        chunk dict anahtarları:
          - chunk_index: int
          - files:       list[str]  — taranacak dosya yolları
          - prompt:      str        — scanner sistem prompt'u
          - output_file: str        — sonucun yazılacağı .jsonl yolu
        """
        chunk_index: int = chunk["chunk_index"]
        rel_files: list[str] = chunk["files"]
        project_path: str = chunk.get("project_path", "")
        base_prompt: str = chunk["prompt"]
        output_file: str = chunk["output_file"]

        # Relative path'leri absolute'a çevir — FastAPI CWD proje kökü değil
        if project_path:
            root = Path(project_path)
            files = [str(root / f) for f in rel_files]
        else:
            files = rel_files

        # Dosya içeriklerini oku — prompt'tan ayrı tut (cache için)
        file_sections = await asyncio.get_event_loop().run_in_executor(
            None, self._read_files_sync, files, max_chars_per_file
        )
        user_content = "## Dosya İçerikleri\n" + file_sections

        logger.debug(
            "ScannerAgent: chunk %d — %d dosya, %d+%d karakter (system+user)",
            chunk_index, len(files), len(base_prompt), len(user_content),
        )

        # Prompt caching: base_prompt (wrapper+scanner_prompt) tüm chunk'larda
        # aynı → system role'üne taşı + cache_system=True ile ephemeral cache
        # marker ekle. İlk chunk cache yazar, sonraki ~300 chunk %10 fiyat öder.
        result = await llm.complete(
            messages=[
                {"role": "system", "content": base_prompt},
                {"role": "user", "content": user_content},
            ],
            model=None,
            max_tokens=max_output_tokens,
            cache_system=True,
        )

        # output_file dizinini oluştur ve sonucu kaydet
        # LLM bazen JSON'u markdown code fence içine sarar — temizle
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(_strip_json_fence(result.text), encoding="utf-8")

        logger.debug(
            "ScannerAgent: chunk %d tamamlandı — %d output token",
            chunk_index, result.output_tokens,
        )

        # TOKEN-PER-ITEM-1: per-chunk token kullanımını kaydet
        if run_id and result.input_tokens > 0:
            try:
                from ...store.repositories import token_stat_repo
                await token_stat_repo.record_task_usage(
                    task_id=f"{run_id}_{chunk_index}",
                    task_type="scanner_chunk",
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
                    "ScannerAgent: per-chunk token kaydı başarısız (chunk=%d): %s",
                    chunk_index, _te,
                )

    def _read_files_sync(self, files: list[str], max_chars_per_file: int = 8_000) -> str:
        """Dosya içeriklerini cache üzerinden okur, her dosyayı max_chars_per_file ile sınırlar.

        Executor üzerinden çağrılır (sync I/O → asyncio uyumu).
        """
        parts: list[str] = []
        for file_path in files:
            content = self._file_cache.read(file_path, max_chars_per_file)
            parts.append(f"=== {file_path} ===\n{content}\n")
        return "\n".join(parts)
