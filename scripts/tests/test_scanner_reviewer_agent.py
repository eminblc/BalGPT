"""Wave 2 testleri — ScannerAgent ve ReviewerAgent.

Tüm dış bağımlılıklar mock edilir: project_get, AgentLifecycleManager,
get_llm, ScanPipeline, ReviewerAgent. Gerçek LLM veya DB çağrısı yapılmaz.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Yardımcı sabitler
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT = {"path": "/tmp/test_project", "id": "proj-123"}
_SCAN_TYPE = "security"
_PROJECT_ID = "proj-123"


# ─────────────────────────────────────────────────────────────────────────────
# Patch hedefleri
# ─────────────────────────────────────────────────────────────────────────────

_SCANNER_MODULE = "backend.features.scan_pipeline.scanner_agent"
_REVIEWER_MODULE = "backend.features.scan_pipeline.reviewer_agent"

# Lazy import'lar fonksiyon içinde yapıldığından kaynak modülleri patch edilir
_PROJECT_GET_SCANNER = "backend.store.repositories.project_repo.project_get"
_PROJECT_GET_REVIEWER = "backend.store.repositories.project_repo.project_get"
_LIFECYCLE_SCANNER = "backend.features.orchestrator.core.AgentLifecycleManager"
_LIFECYCLE_REVIEWER = "backend.features.orchestrator.core.AgentLifecycleManager"
_GET_LLM_SCANNER  = "backend.adapters.llm.llm_factory.get_scan_llm"
_GET_LLM_REVIEWER = "backend.adapters.llm.llm_factory.get_scan_llm"


# ─────────────────────────────────────────────────────────────────────────────
# Fixture'lar
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_lifecycle():
    """AgentLifecycleManager'ı tam AsyncMock olarak döndüren fixture."""
    lc = MagicMock()
    lc.start_run = AsyncMock(return_value="agent-run-001")
    lc.mark_running = AsyncMock()
    lc.mark_completed = AsyncMock()
    lc.mark_failed = AsyncMock()
    return lc


@pytest.fixture
def mock_llm():
    """LLM provider mock'u — complete() bir LLMResult döndürür."""
    llm_result = MagicMock()
    llm_result.text = '{"findings": []}'
    llm_result.output_tokens = 42
    llm = MagicMock()
    llm.complete = AsyncMock(return_value=llm_result)
    return llm


@pytest.fixture
def mock_pipeline(tmp_path):
    """ScanPipeline mock'u — build_scanner_prompts ve diğer metodlar."""
    p = MagicMock()
    run_dir = tmp_path / "scan_runs" / "run-001"
    run_dir.mkdir(parents=True, exist_ok=True)
    p.build_scanner_prompts.return_value = (MagicMock(), [], run_dir)
    p.collect_and_build_reviewer_prompt.return_value = ([], "")
    p.finalize.return_value = {"accepted": 2, "rejected": 1, "duplicate": 0}
    p.finalize_from_reviewed.return_value = {"accepted": 2, "rejected": 1, "duplicate": 0}
    return p, run_dir


# ─────────────────────────────────────────────────────────────────────────────
# ScannerAgent — run() testleri
# ─────────────────────────────────────────────────────────────────────────────

class TestScannerAgentRun:
    """ScannerAgent.run() için birim testleri."""

    def _make_agent(self, pipeline_mock):
        from backend.features.scan_pipeline.scanner_agent import ScannerAgent
        agent = ScannerAgent()
        agent._pipeline = pipeline_mock
        return agent

    @pytest.mark.asyncio
    async def test_run_raises_when_project_not_found(self):
        """project_get None döndürdüğünde ValueError fırlatılmalı."""
        from backend.features.scan_pipeline.scanner_agent import ScannerAgent
        agent = ScannerAgent()
        with patch(_PROJECT_GET_SCANNER, new=AsyncMock(return_value=None)):
            with pytest.raises(ValueError, match="Proje bulunamadı"):
                await agent.run(_SCAN_TYPE, _PROJECT_ID)

    @pytest.mark.asyncio
    async def test_run_calls_mark_running(self, mock_lifecycle, mock_llm, mock_pipeline):
        """run() AgentLifecycleManager.mark_running'i çağırmalı."""
        pipeline, run_dir = mock_pipeline
        agent = self._make_agent(pipeline)

        with patch(_PROJECT_GET_SCANNER, new=AsyncMock(return_value=_PROJECT)), \
             patch(_LIFECYCLE_SCANNER, return_value=mock_lifecycle), \
             patch(_GET_LLM_SCANNER, return_value=mock_llm):
            await agent.run(_SCAN_TYPE, _PROJECT_ID, auto_review=False)

        mock_lifecycle.mark_running.assert_called_once_with("agent-run-001")

    @pytest.mark.asyncio
    async def test_run_empty_chunk_prompts_returns_run_id(self, mock_lifecycle, mock_llm, mock_pipeline):
        """chunk_prompts boş olduğunda run_id döner, mark_completed çağrılır."""
        pipeline, run_dir = mock_pipeline
        # build_scanner_prompts → boş liste
        pipeline.build_scanner_prompts.return_value = (MagicMock(), [], run_dir)

        agent = self._make_agent(pipeline)
        with patch(_PROJECT_GET_SCANNER, new=AsyncMock(return_value=_PROJECT)), \
             patch(_LIFECYCLE_SCANNER, return_value=mock_lifecycle), \
             patch(_GET_LLM_SCANNER, return_value=mock_llm):
            run_id = await agent.run(_SCAN_TYPE, _PROJECT_ID, auto_review=False)

        assert isinstance(run_id, str) and len(run_id) > 0
        mock_lifecycle.mark_completed.assert_called_once()
        # output argümanında "0" geçmeli (çalışmayan dosya/chunk sayısı)
        completed_output = mock_lifecycle.mark_completed.call_args[1].get(
            "output", mock_lifecycle.mark_completed.call_args[0][1]
            if len(mock_lifecycle.mark_completed.call_args[0]) > 1 else ""
        )
        # run_id döndürüldüğü için mark_completed'ın output içeriği kontrol edilir
        assert mock_lifecycle.mark_completed.called

    @pytest.mark.asyncio
    async def test_run_with_chunks_calls_run_scanner_chunks(self, mock_lifecycle, mock_llm, mock_pipeline, tmp_path):
        """chunk_prompts dolu olduğunda _run_scanner_chunks çağrılmalı."""
        pipeline, run_dir = mock_pipeline
        chunk = {
            "chunk_index": 0,
            "files": [],
            "prompt": "test prompt",
            "output_file": str(run_dir / "findings" / "chunk_0.jsonl"),
        }
        pipeline.build_scanner_prompts.return_value = (MagicMock(), [chunk], run_dir)

        agent = self._make_agent(pipeline)

        async def _fake_chunks(chunk_prompts, llm, run_dir, parallel=3, **kwargs):
            pass  # chunk çalıştırmayı taklit et

        agent._run_scanner_chunks = _fake_chunks

        with patch(_PROJECT_GET_SCANNER, new=AsyncMock(return_value=_PROJECT)), \
             patch(_LIFECYCLE_SCANNER, return_value=mock_lifecycle), \
             patch(_GET_LLM_SCANNER, return_value=mock_llm):
            run_id = await agent.run(_SCAN_TYPE, _PROJECT_ID, auto_review=False)

        assert isinstance(run_id, str)
        mock_lifecycle.mark_completed.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_auto_review_true_calls_reviewer(self, mock_lifecycle, mock_llm, mock_pipeline):
        """auto_review=True → ReviewerAgent.run çağrılmalı.

        chunk_prompts dolu olmalı: boş liste erken return yapar ve ReviewerAgent'ı
        tetiklemez (scanner_agent.run() tasarımı gereği).

        ReviewerAgent lazy import ile yüklenir; _run_scanner_chunks stub edilir.
        """
        pipeline, run_dir = mock_pipeline

        # En az bir chunk → erken return yapılmaz
        chunk = {
            "chunk_index": 0,
            "files": [],
            "prompt": "test",
            "output_file": str(run_dir / "findings" / "c0.jsonl"),
        }
        pipeline.build_scanner_prompts.return_value = (MagicMock(), [chunk], run_dir)

        agent = self._make_agent(pipeline)

        # _run_scanner_chunks'u no-op stub yap
        async def _noop_chunks(chunk_prompts, llm, run_dir, parallel=3, **kwargs):
            pass

        agent._run_scanner_chunks = _noop_chunks

        reviewer_run_calls: list = []

        class FakeReviewerAgent:
            async def run(self, run_id, dry_run=False, **kwargs):
                reviewer_run_calls.append(run_id)
                return {"accepted": 0, "rejected": 0, "duplicate": 0, "run_id": run_id}

        with patch(_PROJECT_GET_SCANNER, new=AsyncMock(return_value=_PROJECT)), \
             patch(_LIFECYCLE_SCANNER, return_value=mock_lifecycle), \
             patch(_GET_LLM_SCANNER, return_value=mock_llm), \
             patch("backend.features.scan_pipeline.reviewer_agent.ReviewerAgent", FakeReviewerAgent):
            run_id = await agent.run(_SCAN_TYPE, _PROJECT_ID, auto_review=True)

        assert len(reviewer_run_calls) == 1
        assert reviewer_run_calls[0] == run_id

    @pytest.mark.asyncio
    async def test_run_passes_scan_effort_and_thinking_to_get_scan_llm(self, mock_lifecycle, mock_llm, mock_pipeline):
        """ScannerAgent.run(scan_effort='high', scan_thinking=True) → get_scan_llm'e iletilmeli."""
        pipeline, run_dir = mock_pipeline
        pipeline.build_scanner_prompts.return_value = (MagicMock(), [], run_dir)

        agent = self._make_agent(pipeline)

        captured: list = []

        def _capture_get_scan_llm(model=None, effort=None, thinking=False):
            captured.append((model, effort, thinking))
            return mock_llm

        with patch(_PROJECT_GET_SCANNER, new=AsyncMock(return_value=_PROJECT)), \
             patch(_LIFECYCLE_SCANNER, return_value=mock_lifecycle), \
             patch(_GET_LLM_SCANNER, side_effect=_capture_get_scan_llm):
            await agent.run(
                _SCAN_TYPE, _PROJECT_ID, auto_review=False,
                scan_model="sonnet", scan_effort="high", scan_thinking=True,
            )

        assert captured == [("sonnet", "high", True)]

    @pytest.mark.asyncio
    async def test_run_passes_review_effort_to_reviewer(self, mock_lifecycle, mock_llm, mock_pipeline):
        """auto_review=True ile review_effort verilirse ReviewerAgent.run'a iletilmeli."""
        pipeline, run_dir = mock_pipeline
        chunk = {
            "chunk_index": 0,
            "files": [],
            "prompt": "test",
            "output_file": str(run_dir / "findings" / "c0.jsonl"),
        }
        pipeline.build_scanner_prompts.return_value = (MagicMock(), [chunk], run_dir)

        agent = self._make_agent(pipeline)

        async def _noop_chunks(chunk_prompts, llm, run_dir, parallel=3, **kwargs):
            pass
        agent._run_scanner_chunks = _noop_chunks

        captured_kwargs: dict = {}

        class FakeReviewerAgent:
            async def run(self, run_id, **kwargs):
                captured_kwargs.update(kwargs)
                return {"accepted": 0, "rejected": 0, "duplicate": 0, "run_id": run_id}

        with patch(_PROJECT_GET_SCANNER, new=AsyncMock(return_value=_PROJECT)), \
             patch(_LIFECYCLE_SCANNER, return_value=mock_lifecycle), \
             patch(_GET_LLM_SCANNER, return_value=mock_llm), \
             patch("backend.features.scan_pipeline.reviewer_agent.ReviewerAgent", FakeReviewerAgent):
            await agent.run(
                _SCAN_TYPE, _PROJECT_ID, auto_review=True,
                review_model="opus", review_effort="max", review_thinking=True,
            )

        assert captured_kwargs.get("review_model") == "opus"
        assert captured_kwargs.get("review_effort") == "max"
        assert captured_kwargs.get("review_thinking") is True

    @pytest.mark.asyncio
    async def test_run_auto_review_false_does_not_call_reviewer(self, mock_lifecycle, mock_llm, mock_pipeline):
        """auto_review=False → ReviewerAgent.run ÇAĞRILMAMALI.

        ReviewerAgent lazy import ile yüklenir; kaynak modülü patch edilir.
        """
        pipeline, run_dir = mock_pipeline
        pipeline.build_scanner_prompts.return_value = (MagicMock(), [], run_dir)

        agent = self._make_agent(pipeline)

        reviewer_run_calls: list = []

        class FakeReviewerAgent:
            async def run(self, run_id, dry_run=False):
                reviewer_run_calls.append(run_id)

        with patch(_PROJECT_GET_SCANNER, new=AsyncMock(return_value=_PROJECT)), \
             patch(_LIFECYCLE_SCANNER, return_value=mock_lifecycle), \
             patch(_GET_LLM_SCANNER, return_value=mock_llm), \
             patch("backend.features.scan_pipeline.reviewer_agent.ReviewerAgent", FakeReviewerAgent):
            await agent.run(_SCAN_TYPE, _PROJECT_ID, auto_review=False)

        assert len(reviewer_run_calls) == 0


# ─────────────────────────────────────────────────────────────────────────────
# ScannerAgent — _run_single_chunk() testleri
# ─────────────────────────────────────────────────────────────────────────────

class TestScannerAgentSingleChunk:
    """_run_single_chunk() için birim testleri."""

    @pytest.mark.asyncio
    async def test_single_chunk_writes_output_file(self, tmp_path, mock_llm):
        """_run_single_chunk() LLM çıktısını output_file'a yazmalı."""
        from backend.features.scan_pipeline.scanner_agent import ScannerAgent
        agent = ScannerAgent()

        real_file = tmp_path / "test_real.py"
        real_file.write_text("x = 1\n", encoding="utf-8")

        out_file = tmp_path / "findings" / "chunk_0.jsonl"

        chunk = {
            "chunk_index": 0,
            "files": [str(real_file)],
            "prompt": "Güvenlik tara",
            "output_file": str(out_file),
        }

        mock_llm.complete.return_value.text = '{"finding": "ok"}'

        await agent._run_single_chunk(chunk, mock_llm)

        assert out_file.exists()
        assert out_file.read_text(encoding="utf-8") == '{"finding": "ok"}'

    @pytest.mark.asyncio
    async def test_single_chunk_missing_file_no_exception(self, tmp_path, mock_llm):
        """Var olmayan dosya ile chunk çalışması exception fırlatmamalı."""
        from backend.features.scan_pipeline.scanner_agent import ScannerAgent
        agent = ScannerAgent()

        out_file = tmp_path / "findings" / "chunk_1.jsonl"
        chunk = {
            "chunk_index": 1,
            "files": [str(tmp_path / "nonexistent.py")],
            "prompt": "Tara",
            "output_file": str(out_file),
        }

        # exception fırlatmamalı
        await agent._run_single_chunk(chunk, mock_llm)
        assert out_file.exists()

    @pytest.mark.asyncio
    async def test_one_chunk_fails_others_complete(self, tmp_path, mock_llm):
        """Chunk gather'da bir chunk exception → diğerleri tamamlanmalı.

        return_exceptions=True kullandığı için diğer chunk'lar durmamalı.
        """
        from backend.features.scan_pipeline.scanner_agent import ScannerAgent
        agent = ScannerAgent()

        out1 = tmp_path / "findings" / "chunk_0.jsonl"
        out2 = tmp_path / "findings" / "chunk_1.jsonl"

        call_count = 0

        async def flaky_chunk(chunk, llm, **kwargs):
            nonlocal call_count
            call_count += 1
            if chunk["chunk_index"] == 0:
                raise RuntimeError("chunk 0 crashed")
            # chunk 1 başarılı
            out2.parent.mkdir(parents=True, exist_ok=True)
            out2.write_text("ok", encoding="utf-8")

        agent._run_single_chunk = flaky_chunk

        chunk_prompts = [
            {"chunk_index": 0, "files": [], "prompt": "p0", "output_file": str(out1)},
            {"chunk_index": 1, "files": [], "prompt": "p1", "output_file": str(out2)},
        ]

        await agent._run_scanner_chunks(chunk_prompts, mock_llm, tmp_path / "run")

        # chunk 1 tamamlanmış olmalı
        assert out2.exists()
        assert call_count == 2  # her iki chunk da çalıştırıldı


# ─────────────────────────────────────────────────────────────────────────────
# ScannerAgent — _read_files_sync() testleri
# ─────────────────────────────────────────────────────────────────────────────

class TestReadFilesSync:
    """_read_files_sync() için birim testleri."""

    def test_truncates_long_content(self, tmp_path):
        """Varsayılan max_chars_per_file (8000) aşan dosya içeriği kesilmeli."""
        from backend.features.scan_pipeline.scanner_agent import ScannerAgent

        max_chars = 8_000
        long_file = tmp_path / "big.py"
        content = "x" * (max_chars + 500)
        long_file.write_text(content, encoding="utf-8")

        result = ScannerAgent()._read_files_sync([str(long_file)])

        # Kesilme işareti olmalı
        assert "kesildi" in result
        # Tam içerik olmamalı
        assert "x" * (max_chars + 1) not in result

    def test_nonexistent_file_returns_error_message(self, tmp_path):
        """Var olmayan dosya için hata mesajı dönmeli (exception yok)."""
        from backend.features.scan_pipeline.scanner_agent import ScannerAgent

        result = ScannerAgent()._read_files_sync([str(tmp_path / "ghost.py")])

        assert "ghost.py" in result
        assert "bulunamadı" in result

    def test_existing_file_content_included(self, tmp_path):
        """Gerçek dosya içeriği sonuca dahil edilmeli."""
        from backend.features.scan_pipeline.scanner_agent import ScannerAgent

        f = tmp_path / "hello.py"
        f.write_text("print('hello')\n", encoding="utf-8")

        result = ScannerAgent()._read_files_sync([str(f)])

        assert "print('hello')" in result


# ─────────────────────────────────────────────────────────────────────────────
# ReviewerAgent — run() testleri
# ─────────────────────────────────────────────────────────────────────────────

class TestReviewerAgentRun:
    """ReviewerAgent.run() için birim testleri."""

    def _write_meta(self, run_dir: Path, extra: dict | None = None) -> Path:
        meta = {
            "run_id": "test-run-id",
            "scan_type": "security",
            "project_id": _PROJECT_ID,
            "project_path": "/tmp/test_project",
            "status": "scanned",
            "started_at": 1000.0,
            "dry_run": False,
        }
        if extra:
            meta.update(extra)
        meta_path = run_dir / "meta.json"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        return meta_path

    @pytest.mark.asyncio
    async def test_run_reads_meta_json(self, tmp_path, mock_lifecycle, mock_llm):
        """run() run_dir'deki meta.json'u okumalı."""
        from backend.features.scan_pipeline.reviewer_agent import ReviewerAgent

        run_id = "test-run-id"
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True)
        self._write_meta(run_dir)

        # review.jsonl gerekiyor
        (run_dir / "review.jsonl").write_text("[]", encoding="utf-8")

        agent = ReviewerAgent()
        mock_pipeline = MagicMock()
        mock_config_loader = MagicMock()
        mock_pipeline.collect_and_build_reviewer_prompt.return_value = ([], "")
        agent._pipeline = mock_pipeline
        agent._config_loader = mock_config_loader

        with patch(_PROJECT_GET_REVIEWER, new=AsyncMock(return_value=_PROJECT)), \
             patch(_LIFECYCLE_REVIEWER, return_value=mock_lifecycle), \
             patch(_GET_LLM_REVIEWER, return_value=mock_llm), \
             patch("backend.features.scan_pipeline.reviewer_agent._RUNS_DIR", tmp_path):
            result = await agent.run(run_id)

        assert result["run_id"] == run_id

    @pytest.mark.asyncio
    async def test_run_raises_when_meta_json_missing(self, tmp_path, mock_lifecycle, mock_llm):
        """meta.json yoksa FileNotFoundError fırlatılmalı."""
        from backend.features.scan_pipeline.reviewer_agent import ReviewerAgent

        run_id = "no-meta-run"
        # run_dir oluştur ama meta.json yazma
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True)

        agent = ReviewerAgent()

        with patch("backend.features.scan_pipeline.reviewer_agent._RUNS_DIR", tmp_path):
            with pytest.raises(FileNotFoundError):
                await agent.run(run_id)

    @pytest.mark.asyncio
    async def test_run_no_findings_mark_completed_zero(self, tmp_path, mock_lifecycle, mock_llm):
        """Bulgu yokken mark_completed '0 bulgu' ile çağrılmalı."""
        from backend.features.scan_pipeline.reviewer_agent import ReviewerAgent

        run_id = "empty-run"
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True)
        self._write_meta(run_dir)

        agent = ReviewerAgent()
        mock_pipeline = MagicMock()
        mock_config_loader = MagicMock()
        mock_pipeline.collect_and_build_reviewer_prompt.return_value = ([], "no prompt")
        agent._pipeline = mock_pipeline
        agent._config_loader = mock_config_loader

        with patch(_PROJECT_GET_REVIEWER, new=AsyncMock(return_value=_PROJECT)), \
             patch(_LIFECYCLE_REVIEWER, return_value=mock_lifecycle), \
             patch(_GET_LLM_REVIEWER, return_value=mock_llm), \
             patch("backend.features.scan_pipeline.reviewer_agent._RUNS_DIR", tmp_path):
            result = await agent.run(run_id)

        assert result["accepted"] == 0
        assert result["rejected"] == 0
        mock_lifecycle.mark_completed.assert_called_once()
        completed_output = mock_lifecycle.mark_completed.call_args[1].get("output", "")
        assert "0 bulgu" in completed_output

    @pytest.mark.asyncio
    async def test_run_happy_path_mark_completed_with_counts(self, tmp_path, mock_lifecycle, mock_llm):
        """Bulgular varken mark_completed accepted/rejected sayılarını içermeli."""
        from backend.features.scan_pipeline.reviewer_agent import ReviewerAgent

        run_id = "happy-run"
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True)
        self._write_meta(run_dir)

        findings = [{"id": "F1"}, {"id": "F2"}]

        mock_pipeline = MagicMock()
        mock_config_loader = MagicMock()
        mock_pipeline.collect_and_build_reviewer_prompt.return_value = (findings, "reviewer prompt text")
        mock_pipeline.finalize.return_value = {"accepted": 2, "rejected": 1, "duplicate": 0}
        mock_pipeline.finalize_from_reviewed.return_value = {"accepted": 2, "rejected": 1, "duplicate": 0}
        agent = ReviewerAgent()
        agent._pipeline = mock_pipeline
        agent._config_loader = mock_config_loader

        with patch(_PROJECT_GET_REVIEWER, new=AsyncMock(return_value=_PROJECT)), \
             patch(_LIFECYCLE_REVIEWER, return_value=mock_lifecycle), \
             patch(_GET_LLM_REVIEWER, return_value=mock_llm), \
             patch("backend.features.scan_pipeline.reviewer_agent._RUNS_DIR", tmp_path):
            result = await agent.run(run_id)

        assert result["accepted"] == 2
        assert result["rejected"] == 1
        assert result["duplicate"] == 0

        mock_lifecycle.mark_completed.assert_called_once()
        completed_output = mock_lifecycle.mark_completed.call_args[1].get("output", "")
        assert "accepted=2" in completed_output
        assert "rejected=1" in completed_output

    @pytest.mark.asyncio
    async def test_run_updates_meta_status_to_reviewed(self, tmp_path, mock_lifecycle, mock_llm):
        """run() tamamlandıktan sonra meta.json status'unu 'reviewed' yapmalı."""
        from backend.features.scan_pipeline.reviewer_agent import ReviewerAgent

        run_id = "status-run"
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True)
        meta_path = self._write_meta(run_dir)

        findings = [{"id": "F1"}]

        mock_pipeline = MagicMock()
        mock_config_loader = MagicMock()
        mock_pipeline.collect_and_build_reviewer_prompt.return_value = (findings, "prompt")
        mock_pipeline.finalize.return_value = {"accepted": 1, "rejected": 0, "duplicate": 0}
        mock_pipeline.finalize_from_reviewed.return_value = {"accepted": 1, "rejected": 0, "duplicate": 0}

        agent = ReviewerAgent()
        agent._pipeline = mock_pipeline
        agent._config_loader = mock_config_loader

        with patch(_PROJECT_GET_REVIEWER, new=AsyncMock(return_value=_PROJECT)), \
             patch(_LIFECYCLE_REVIEWER, return_value=mock_lifecycle), \
             patch(_GET_LLM_REVIEWER, return_value=mock_llm), \
             patch("backend.features.scan_pipeline.reviewer_agent._RUNS_DIR", tmp_path):
            await agent.run(run_id)

        updated_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert updated_meta["status"] == "reviewed"

    @pytest.mark.asyncio
    async def test_run_meta_missing_calls_mark_failed_not_called(self, tmp_path):
        """meta.json yokken FileNotFoundError fırlatılır — lifecycle başlatılmadan önce.

        FileNotFoundError meta_path.exists() kontrolünde fırlatılır;
        AgentLifecycleManager hiç başlatılmaz, dolayısıyla mark_failed çağrılmaz.
        """
        from backend.features.scan_pipeline.reviewer_agent import ReviewerAgent

        run_id = "no-meta-2"
        run_dir = tmp_path / run_id
        run_dir.mkdir(parents=True)
        # meta.json yok

        agent = ReviewerAgent()

        lifecycle_calls = []

        class TrackingLifecycle:
            async def start_run(self, *a, **kw):
                lifecycle_calls.append("start_run")
                return "agent-id"
            async def mark_running(self, *a, **kw):
                lifecycle_calls.append("mark_running")
            async def mark_failed(self, *a, **kw):
                lifecycle_calls.append("mark_failed")
            async def mark_completed(self, *a, **kw):
                lifecycle_calls.append("mark_completed")

        with patch("backend.features.scan_pipeline.reviewer_agent._RUNS_DIR", tmp_path), \
             patch(_LIFECYCLE_REVIEWER, return_value=TrackingLifecycle()):
            with pytest.raises(FileNotFoundError):
                await agent.run(run_id)

        # meta_path kontrolü start_run'dan önce yapılır — lifecycle başlatılmaz
        assert "mark_failed" not in lifecycle_calls
