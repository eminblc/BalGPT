"""Wave 2 testleri — BacklogParser ve BacklogExecutorAgent.

BacklogParser testleri gerçek dosya I/O kullanır (tmp_path).
BacklogExecutorAgent testleri tüm dış bağımlılıkları mock eder:
  project_get, AgentLifecycleManager, httpx.AsyncClient.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Sabitler
# ─────────────────────────────────────────────────────────────────────────────

_PROJECT_ID = "proj-001"
_RUNNER_MODULE = "backend.features.backlog_executor.runner"
_PROJECT_GET = f"{_RUNNER_MODULE}.project_get"
_LIFECYCLE = f"{_RUNNER_MODULE}.AgentLifecycleManager"


# ─────────────────────────────────────────────────────────────────────────────
# BacklogParser — get_pending_items()
# ─────────────────────────────────────────────────────────────────────────────

class TestBacklogParserGetPending:
    """BacklogParser.get_pending_items() testleri."""

    def _parser(self):
        from backend.features.backlog_executor.parser import BacklogParser
        return BacklogParser()

    def test_empty_file_returns_empty_list(self, tmp_path):
        """Boş dosya → boş liste."""
        f = tmp_path / "BACKLOG.md"
        f.write_text("", encoding="utf-8")
        result = self._parser().get_pending_items(f)
        assert result == []

    def test_finds_pending_items(self, tmp_path):
        """[ ] işaretli item'lar döner."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "## Backlog\n"
            "- [ ] SEC-001 SQL injection açığı\n"
            "- [ ] BUG-042 Login hatası\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f)
        assert len(items) == 2
        ids = {i["item_id"] for i in items}
        assert "SEC-001" in ids
        assert "BUG-042" in ids

    def test_prefix_filter_returns_only_matching(self, tmp_path):
        """prefix='SEC' → yalnızca SEC-* item'lar."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "- [ ] SEC-001 Açıklama\n"
            "- [ ] BUG-002 Başka şey\n"
            "- [ ] SEC-003 Üçüncü\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f, prefix="SEC")
        assert len(items) == 2
        for item in items:
            assert item["prefix"] == "SEC"

    def test_skips_done_items(self, tmp_path):
        """[x] satırları atlanmalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "- [x] SEC-001 Tamamlandı\n"
            "- [ ] SEC-002 Bekliyor\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f)
        assert len(items) == 1
        assert items[0]["item_id"] == "SEC-002"

    def test_skips_in_progress_items(self, tmp_path):
        """[~] satırları atlanmalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "- [~] SEC-010 İşleniyor\n"
            "- [ ] SEC-011 Bekliyor\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f)
        assert len(items) == 1
        assert items[0]["item_id"] == "SEC-011"

    def test_skips_lines_without_item_id(self, tmp_path):
        """Item ID pattern olmayan [ ] satırlar atlanmalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "- [ ] bu satırda item id yok\n"
            "- [ ] SEC-001 bu var\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f)
        assert len(items) == 1
        assert items[0]["item_id"] == "SEC-001"


# ─────────────────────────────────────────────────────────────────────────────
# BacklogParser — mark_in_progress(), mark_done(), mark_failed()
# ─────────────────────────────────────────────────────────────────────────────

class TestBacklogParserMutations:
    """BacklogParser durum geçişi metodları."""

    def _parser(self):
        from backend.features.backlog_executor.parser import BacklogParser
        return BacklogParser()

    def test_mark_in_progress_changes_bracket(self, tmp_path):
        """mark_in_progress: [ ] → [~]."""
        f = tmp_path / "BACKLOG.md"
        f.write_text("- [ ] SEC-001 Açıklama\n", encoding="utf-8")
        result = self._parser().mark_in_progress(f, "SEC-001")
        assert result is True
        assert "- [~] SEC-001" in f.read_text(encoding="utf-8")

    def test_mark_in_progress_returns_false_when_not_found(self, tmp_path):
        """Bulunamayan item için False döner."""
        f = tmp_path / "BACKLOG.md"
        f.write_text("- [ ] BUG-999 Başka\n", encoding="utf-8")
        result = self._parser().mark_in_progress(f, "SEC-001")
        assert result is False

    def test_mark_done_from_pending(self, tmp_path):
        """mark_done: [ ] → [x]."""
        f = tmp_path / "BACKLOG.md"
        f.write_text("- [ ] SEC-002 Bekliyor\n", encoding="utf-8")
        result = self._parser().mark_done(f, "SEC-002")
        assert result is True
        assert "- [x] SEC-002" in f.read_text(encoding="utf-8")

    def test_mark_done_from_in_progress(self, tmp_path):
        """mark_done: [~] → [x]."""
        f = tmp_path / "BACKLOG.md"
        f.write_text("- [~] SEC-003 İşleniyor\n", encoding="utf-8")
        result = self._parser().mark_done(f, "SEC-003")
        assert result is True
        assert "- [x] SEC-003" in f.read_text(encoding="utf-8")

    def test_mark_failed_reverts_to_pending(self, tmp_path):
        """mark_failed: [~] → [ ]."""
        f = tmp_path / "BACKLOG.md"
        f.write_text("- [~] SEC-004 İşleniyor\n", encoding="utf-8")
        result = self._parser().mark_failed(f, "SEC-004")
        assert result is True
        assert "- [ ] SEC-004" in f.read_text(encoding="utf-8")

    def test_atomic_write_tmp_file_gone_after_write(self, tmp_path):
        """Atomic write: .tmp dosyası işlem sonrası yok olmalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text("- [ ] SEC-005 Test\n", encoding="utf-8")

        self._parser().mark_in_progress(f, "SEC-005")

        tmp_file = f.with_suffix(".tmp")
        assert not tmp_file.exists(), ".tmp dosyası atomic write sonrası silinmeli"


# ─────────────────────────────────────────────────────────────────────────────
# BacklogExecutorAgent fixture'lar
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_lifecycle():
    lc = MagicMock()
    lc.start_run = AsyncMock(return_value="exec-run-001")
    lc.mark_running = AsyncMock()
    lc.mark_completed = AsyncMock()
    lc.mark_failed = AsyncMock()
    return lc


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.claude_bridge_url = "http://localhost:8013"
    s.api_key.get_secret_value.return_value = "test-api-key"
    return s


@pytest.fixture
def backlog_file(tmp_path):
    """Bir pending item içeren BACKLOG.md döndürür."""
    content = (
        "## Açık\n"
        "- [ ] SEC-001 SQL injection düzelt\n"
        "- [ ] BUG-002 Login hatası gider\n"
    )
    f = tmp_path / "BACKLOG.md"
    f.write_text(content, encoding="utf-8")
    return f


@pytest.fixture
def project_with_backlog(tmp_path, backlog_file):
    """Proje dict'i; path tmp_path'e işaret eder."""
    return {"path": str(tmp_path), "id": _PROJECT_ID}


# ─────────────────────────────────────────────────────────────────────────────
# BacklogExecutorAgent — run() testleri
# ─────────────────────────────────────────────────────────────────────────────

class TestBacklogExecutorAgentRun:
    """BacklogExecutorAgent.run() için birim testleri."""

    def _agent(self):
        from backend.features.backlog_executor.runner import BacklogExecutorAgent
        return BacklogExecutorAgent()

    @pytest.mark.asyncio
    async def test_run_raises_when_project_not_found(self, mock_lifecycle):
        """Proje bulunamazsa ValueError."""
        agent = self._agent()
        with patch(_PROJECT_GET, new=AsyncMock(return_value=None)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle):
            with pytest.raises(ValueError, match="Proje bulunamadı"):
                await agent.run(_PROJECT_ID)

    @pytest.mark.asyncio
    async def test_run_raises_when_backlog_missing(self, tmp_path, mock_lifecycle):
        """BACKLOG.md yoksa FileNotFoundError."""
        project = {"path": str(tmp_path), "id": _PROJECT_ID}
        agent = self._agent()
        with patch(_PROJECT_GET, new=AsyncMock(return_value=project)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle):
            with pytest.raises(FileNotFoundError):
                await agent.run(_PROJECT_ID)

    @pytest.mark.asyncio
    async def test_run_no_pending_items_mark_completed(
        self, tmp_path, mock_lifecycle, project_with_backlog
    ):
        """Pending item yoksa mark_completed '0 item' ile çağrılmalı."""
        # BACKLOG.md yaz — sadece done item'lar
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("- [x] SEC-001 Tamamlandı\n", encoding="utf-8")

        agent = self._agent()
        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle):
            result = await agent.run(_PROJECT_ID)

        assert result["total"] == 0
        mock_lifecycle.mark_completed.assert_called_once()
        output_arg = mock_lifecycle.mark_completed.call_args[1].get("output", "")
        assert "0 item" in output_arg

    @pytest.mark.asyncio
    async def test_run_dry_run_marks_done_no_bridge_call(
        self, tmp_path, mock_lifecycle, project_with_backlog
    ):
        """dry_run=True → mark_done çağrılmalı, Bridge'e istek atılmamalı."""
        agent = self._agent()

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.httpx") as mock_httpx:
            result = await agent.run(_PROJECT_ID, dry_run=True)

        # httpx client hiç kullanılmamalı
        mock_httpx.AsyncClient.assert_not_called()
        assert result["completed"] >= 1  # en az bir item işlendi
        # BACKLOG.md'de [x] işaretleri olmalı
        backlog_text = (tmp_path / "BACKLOG.md").read_text(encoding="utf-8")
        assert "- [x]" in backlog_text

    @pytest.mark.asyncio
    async def test_run_happy_path_marks_in_progress_then_done(
        self, tmp_path, mock_lifecycle, mock_settings, project_with_backlog
    ):
        """Happy path: mark_in_progress → Bridge çağrısı → mark_done."""
        agent = self._agent()

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.get_settings", return_value=mock_settings), \
             patch(f"{_RUNNER_MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await agent.run(_PROJECT_ID, max_items=1)

        assert result["completed"] == 1
        assert result["failed"] == 0

        backlog_text = (tmp_path / "BACKLOG.md").read_text(encoding="utf-8")
        assert "- [x]" in backlog_text

    @pytest.mark.asyncio
    async def test_run_bridge_non_200_calls_mark_failed(
        self, tmp_path, mock_lifecycle, mock_settings, project_with_backlog
    ):
        """Bridge HTTP 500 → item mark_failed olarak işaretlenmeli."""
        agent = self._agent()

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        # Önce in_progress yap — mark_failed [~] → [ ] yapmalı
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("- [ ] SEC-001 Test item\n", encoding="utf-8")

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.get_settings", return_value=mock_settings), \
             patch(f"{_RUNNER_MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await agent.run(_PROJECT_ID, max_items=1)

        assert result["failed"] == 1
        assert result["completed"] == 0

        # mark_failed: [~] → [ ] geri alınmalı
        backlog_text = backlog.read_text(encoding="utf-8")
        assert "- [ ] SEC-001" in backlog_text

    @pytest.mark.asyncio
    async def test_run_bridge_exception_mark_failed_continues(
        self, tmp_path, mock_lifecycle, mock_settings, project_with_backlog
    ):
        """Bridge exception atarsa: mark_failed çağrılmalı, diğer item'lar devam etmeli."""
        agent = self._agent()

        # İki pending item
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text(
            "- [ ] SEC-001 Hata verecek\n"
            "- [ ] SEC-002 Başarılı\n",
            encoding="utf-8",
        )

        call_count = 0

        async def _post_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("Bridge down")
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=_post_side_effect)

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.get_settings", return_value=mock_settings), \
             patch(f"{_RUNNER_MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await agent.run(_PROJECT_ID, max_items=2, parallel=2)

        # SEC-001 başarısız, SEC-002 başarılı
        assert result["failed"] == 1
        assert result["completed"] == 1

    @pytest.mark.asyncio
    async def test_parallel_semaphore_limits_concurrency(
        self, tmp_path, mock_lifecycle, mock_settings, project_with_backlog
    ):
        """parallel=2 → aynı anda en fazla 2 Bridge çağrısı yapılmalı."""
        agent = self._agent()

        # 4 pending item yaz
        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text(
            "- [ ] SEC-001 Bir\n"
            "- [ ] SEC-002 İki\n"
            "- [ ] SEC-003 Üç\n"
            "- [ ] SEC-004 Dört\n",
            encoding="utf-8",
        )

        concurrent_peak = 0
        current_concurrent = 0
        import asyncio as _asyncio

        async def _tracked_post(*args, **kwargs):
            nonlocal concurrent_peak, current_concurrent
            current_concurrent += 1
            if current_concurrent > concurrent_peak:
                concurrent_peak = current_concurrent
            # kısa gecikme — concurrent hesaplama için
            await _asyncio.sleep(0.01)
            current_concurrent -= 1
            resp = MagicMock()
            resp.status_code = 200
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = _tracked_post

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.get_settings", return_value=mock_settings), \
             patch(f"{_RUNNER_MODULE}.httpx.AsyncClient", return_value=mock_client):
            await agent.run(_PROJECT_ID, max_items=4, parallel=2)

        # Eş zamanlılık 2'yi geçmemeli
        assert concurrent_peak <= 2
