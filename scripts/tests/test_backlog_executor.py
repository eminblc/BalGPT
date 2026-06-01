"""Wave 2 testleri — BacklogParser ve BacklogExecutorAgent.

BacklogParser testleri gerçek dosya I/O kullanır (tmp_path).
BacklogExecutorAgent testleri tüm dış bağımlılıkları mock eder:
  project_get, AgentLifecycleManager, httpx.AsyncClient.

Format kapsamı:
  CheckboxFormat — mevcut - [ ] formatı (PetekV5 + eski 99-root)
  TableFormat    — | ID | ... tablo formatı (güncel 99-root)
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

    def test_skips_items_in_deferred_section(self, tmp_path):
        """## Ertelenmiş / ## ✅ Tamamlandı / ## Kullanıcı bölümlerindeki
        - [ ] satırları executor pending listesine alınmamalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "## Backlog\n"
            "- [ ] SEC-001 aktif iş\n"
            "\n"
            "## Ertelenmiş\n"
            "- [ ] PENTEST-001 ertelenmiş iş\n"
            "\n"
            "## ✅ Tamamlandı\n"
            "- [ ] OLD-001 eski iş\n"
            "\n"
            "## Kullanıcı Eylemi Gerektiren\n"
            "- [ ] USER-001 kullanıcı işi\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f)
        ids = {i["item_id"] for i in items}
        assert ids == {"SEC-001"}
        assert "PENTEST-001" not in ids
        assert "OLD-001" not in ids
        assert "USER-001" not in ids


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

    def test_mark_failed_increments_retry_counter(self, tmp_path):
        """İlk başarısızlıkta satır sonuna `(1/3 başarısız)` eklenir."""
        f = tmp_path / "BACKLOG.md"
        f.write_text("- [~] SEC-010 Test\n", encoding="utf-8")
        self._parser().mark_failed(f, "SEC-010")
        text = f.read_text(encoding="utf-8")
        assert "- [ ] SEC-010 Test (1/3 başarısız)" in text

    def test_mark_failed_locks_item_after_max_retries(self, tmp_path):
        """MAX_RETRIES (3) başarısızlığa ulaşınca item [!] ile kilitlenir."""
        from backend.features.backlog_executor._formats import MAX_RETRIES, CheckboxFormat
        f = tmp_path / "BACKLOG.md"
        f.write_text("- [~] SEC-011 Test\n", encoding="utf-8")
        fmt = CheckboxFormat()
        for _ in range(MAX_RETRIES):
            fmt.mark_failed(f, "SEC-011")
            # tekrar dener gibi [~] yap
            if "- [ ]" in f.read_text(encoding="utf-8"):
                fmt.mark_in_progress(f, "SEC-011")
        text = f.read_text(encoding="utf-8")
        assert "- [!] SEC-011" in text
        assert f"({MAX_RETRIES}/{MAX_RETRIES} başarısız)" in text

    def test_locked_item_skipped_by_get_pending(self, tmp_path):
        """[!] ile kilitlenmiş item get_pending_items'tan dönmez."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "- [ ] SEC-012 Aktif\n"
            "- [!] SEC-013 Kilitli (3/3 başarısız)\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f)
        ids = [i["item_id"] for i in items]
        assert ids == ["SEC-012"]

    def test_mark_done_clears_retry_counter(self, tmp_path):
        """Manuel olarak [!] item [x] yapıldığında retry sayacı temizlenir."""
        f = tmp_path / "BACKLOG.md"
        f.write_text("- [!] SEC-014 Test (3/3 başarısız)\n", encoding="utf-8")
        self._parser().mark_done(f, "SEC-014")
        text = f.read_text(encoding="utf-8")
        assert "- [x] SEC-014 Test" in text
        assert "başarısız" not in text

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
        mock_response.json.return_value = {
            "answer": "Item implement edildi: ilgili dosya güncellendi ve testler geçti.",
            "session_id": "executor_SEC-001",
        }

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
            resp.json.return_value = {
                "answer": "SEC-002 implement edildi: ilgili dosya başarıyla güncellendi.",
                "session_id": "executor_SEC-002",
            }
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
    async def test_run_bridge_empty_answer_treated_as_failure(
        self, tmp_path, mock_lifecycle, mock_settings, project_with_backlog
    ):
        """HTTP 200 + boş `answer` → sahte tamamlama önlenmeli, item failed olmalı.

        Regresyon: 2026-05-20 1:00 AM koşusunda Bridge HTTP 200 dönmesine rağmen
        Claude Code CLI 0 token / 0 tool ile sessizce exit etmiş, response body
        boş gelmişti. Runner yalnızca status code'a baktığı için 19 item sahte
        tamamlandı olarak işaretlendi.
        """
        agent = self._agent()

        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("- [ ] SEC-001 İş yapılmayacak\n", encoding="utf-8")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"answer": "", "session_id": "executor_SEC-001"}

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.get_settings", return_value=mock_settings), \
             patch(f"{_RUNNER_MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await agent.run(_PROJECT_ID, max_items=1)

        assert result["failed"] == 1
        assert result["completed"] == 0
        # Item [x] (done) yerine [ ] (pending) durumuna geri dönmeli
        backlog_text = backlog.read_text(encoding="utf-8")
        assert "- [x]" not in backlog_text
        assert "- [ ] SEC-001" in backlog_text

    @pytest.mark.asyncio
    async def test_run_bridge_cancelled_treated_as_failure(
        self, tmp_path, mock_lifecycle, mock_settings, project_with_backlog
    ):
        """HTTP 200 + cancelled=True → sahte tamamlama önlenmeli."""
        agent = self._agent()

        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("- [ ] SEC-001 İptal edilecek\n", encoding="utf-8")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "answer": "",
            "session_id": "executor_SEC-001",
            "cancelled": True,
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.get_settings", return_value=mock_settings), \
             patch(f"{_RUNNER_MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await agent.run(_PROJECT_ID, max_items=1)

        assert result["failed"] == 1
        assert result["completed"] == 0

    @pytest.mark.asyncio
    async def test_run_bridge_status_failed_line_treated_as_failure(
        self, tmp_path, mock_lifecycle, mock_settings, project_with_backlog
    ):
        """EXEC-PROMPT-001: Uzun cevap olsa bile son satır `STATUS: failed` ise failure.

        Prompt sözleşmesi modelden mesajın son satırında `STATUS: ok` veya
        `STATUS: failed` ister. Sadece uzunluk eşiğine güvenmek yetmez: model
        "yapamadım çünkü dosya yok" gibi 40+ karakterlik bir failure metni
        gönderebilir — bu durumda item failed kalmalı.
        """
        agent = self._agent()

        backlog = tmp_path / "BACKLOG.md"
        backlog.write_text("- [ ] SEC-001 Halüsinasyon item\n", encoding="utf-8")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "answer": (
                "Görev hedefi olan dosya repoda bulunamadı; halüsinasyon olarak "
                "EXECUTORS_COMMENTS.md'ye not düştüm.\nSTATUS: failed"
            ),
            "session_id": "executor_SEC-001",
        }

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.get_settings", return_value=mock_settings), \
             patch(f"{_RUNNER_MODULE}.httpx.AsyncClient", return_value=mock_client):
            result = await agent.run(_PROJECT_ID, max_items=1)

        assert result["failed"] == 1
        assert result["completed"] == 0
        backlog_text = backlog.read_text(encoding="utf-8")
        assert "- [x]" not in backlog_text
        assert "- [ ] SEC-001" in backlog_text

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
            resp.json.return_value = {
                "answer": "Item implement edildi: dosya güncellendi ve doğrulandı.",
                "session_id": "executor",
            }
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


# ─────────────────────────────────────────────────────────────────────────────
# BacklogExecutorAgent._build_prompt — Git commit kuralı
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildPromptGitRule:
    """Prompt'un git commit kuralı bölümünü zorunlu olarak içermesi gerektiğini doğrular.

    Backlog executor item'ları implement ettikten sonra **yalnızca işlediği projenin**
    kök dizininde commit atmalı; başka repo'lara (özellikle 99-root) dokunmamalı,
    push yapmamalı, remote'u olmayan projede commit atmamalı.
    """

    def _agent(self):
        from backend.features.backlog_executor.runner import BacklogExecutorAgent
        return BacklogExecutorAgent()

    def _item(self):
        from backend.features.backlog_executor.parser import BacklogItem
        return BacklogItem(
            item_id="BUG-001",
            text="- [ ] BUG-001 örnek görev",
            line_no=0,
            prefix="BUG",
        )

    def test_prompt_scopes_git_to_project_root(self):
        """Tüm git komutları `git -C "{project_root}"` formatında olmalı."""
        prompt = self._agent()._build_prompt(self._item(), "/path/to/petekv5")
        assert 'git -C "/path/to/petekv5"' in prompt

    def test_prompt_forbids_push(self):
        prompt = self._agent()._build_prompt(self._item(), "/path/to/petekv5")
        assert "push" in prompt.lower()
        # Push yasağı açıkça yer almalı
        assert "git push" in prompt
        assert "YAPMA" in prompt

    def test_prompt_requires_remote_check(self):
        """Remote yoksa commit atılmaması talimatı bulunmalı."""
        prompt = self._agent()._build_prompt(self._item(), "/path/to/proj")
        assert 'git -C "/path/to/proj" remote' in prompt
        assert "boş" in prompt  # "Çıktı boş ise commit ATMA"

    def test_prompt_protects_other_repos(self):
        """project_root dışındaki repo'lara dokunulmaması belirtilmeli."""
        prompt = self._agent()._build_prompt(self._item(), "/path/to/petekv5")
        # Konsolide kural: "başka dizinde git ÇALIŞTIRMA, başka repo'ya dokunma"
        assert "başka repo" in prompt
        assert "başka dizinde git" in prompt

    def test_prompt_mentions_conventional_commits(self):
        prompt = self._agent()._build_prompt(self._item(), "/p")
        assert "Conventional Commit" in prompt
        assert "feat:" in prompt and "fix:" in prompt

    def test_prompt_requires_minimal_change(self):
        """Minimal değişiklik talimatı bulunmalı."""
        prompt = self._agent()._build_prompt(self._item(), "/p")
        assert "Minimal değişiklik" in prompt

    def test_prompt_empty_status_skips_commit(self):
        """`git status --porcelain` boşsa commit atılmaması talimatı bulunmalı."""
        prompt = self._agent()._build_prompt(self._item(), "/path/to/proj")
        assert "status --porcelain" in prompt
        assert "commit ATMA" in prompt
        assert "refactor" in prompt.lower()

    def test_prompt_requires_status_line_contract(self):
        """EXEC-PROMPT-001: prompt 1-3 cümle özet + STATUS: ok/failed satırı şart koşmalı.

        Eski sözleşme tek kelimelik "yapıldı." istiyordu ve _MIN_ANSWER_LEN=40
        ile çelişiyordu (executor her item'ı failed olarak işaretliyordu).
        Yeni sözleşme: anlamlı özet + son satırda STATUS: ok / STATUS: failed.
        """
        prompt = self._agent()._build_prompt(self._item(), "/p")
        assert "STATUS: ok" in prompt
        assert "STATUS: failed" in prompt
        assert "1–3 cümle" in prompt or "1-3 cümle" in prompt
        # Eski "yapıldı." / "yapılamadı." sözleşmesi yasaklanmalı
        assert "YASAK" in prompt or "tek kelimelik cevaplar" in prompt.lower()


# ─────────────────────────────────────────────────────────────────────────────
# TableFormat — get_pending_items()
# ─────────────────────────────────────────────────────────────────────────────

class TestTableFormatGetPending:
    """TableFormat.get_pending_items() testleri — 99-root BACKLOG.md formatı."""

    _TABLE_CONTENT = (
        "## 🟠 YÜKSEK\n"
        "\n"
        "| # | Başlık | Dosya | Not |\n"
        "|---|--------|-------|-----|\n"
        "| SCAN-DEPTH-1 | max chars config | scanner.py | detay |\n"
        "| SCAN-DEPTH-2 | chunk boyutu | scanner.py | detay |\n"
        "\n"
        "## 🟡 ORTA\n"
        "\n"
        "| # | Başlık | Dosya | Not |\n"
        "|---|--------|-------|-----|\n"
        "| IMP-FEAT-1 | küçük iyileştirme | features.py | — |\n"
    )

    def _parser(self):
        from backend.features.backlog_executor.parser import BacklogParser
        return BacklogParser()

    def test_reads_all_table_items(self, tmp_path):
        """Tablo satırlarındaki tüm ID'ler pending olarak döner."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(self._TABLE_CONTENT, encoding="utf-8")
        items = self._parser().get_pending_items(f)
        ids = {i["item_id"] for i in items}
        assert "SCAN-DEPTH-1" in ids
        assert "SCAN-DEPTH-2" in ids
        assert "IMP-FEAT-1" in ids

    def test_prefix_filter_table(self, tmp_path):
        """prefix='SCAN' → yalnızca SCAN-* satırlar."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(self._TABLE_CONTENT, encoding="utf-8")
        items = self._parser().get_pending_items(f, prefix="SCAN")
        assert all(i["prefix"] == "SCAN" for i in items)
        assert len(items) == 2

    def test_skips_separator_and_header_rows(self, tmp_path):
        """Başlık ve separator satırları item olarak okunmamalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(self._TABLE_CONTENT, encoding="utf-8")
        items = self._parser().get_pending_items(f)
        ids = {i["item_id"] for i in items}
        # "Başlık", "Dosya", "Not" gibi header kelimeleri eşleşmemeli
        assert all(_looks_like_real_id(i) for i in ids)

    def test_skips_in_progress_table_rows(self, tmp_path):
        """🔄 prefiksli satırlar atlanmalı."""
        content = (
            "| 🔄SCAN-DEPTH-1 | max chars | scanner.py | — |\n"
            "| SCAN-DEPTH-2 | chunk | scanner.py | — |\n"
        )
        f = tmp_path / "BACKLOG.md"
        f.write_text(content, encoding="utf-8")
        items = self._parser().get_pending_items(f)
        ids = {i["item_id"] for i in items}
        assert "SCAN-DEPTH-1" not in ids
        assert "SCAN-DEPTH-2" in ids

    def test_skips_completed_section(self, tmp_path):
        """✅ Tamamlandı bölümü altındaki satırlar atlanmalı."""
        content = (
            "| SCAN-DEPTH-1 | aktif | scanner.py | — |\n"
            "\n"
            "## ✅ Tamamlandı\n"
            "\n"
            "| OLD-001 | eski görev | file.py | — |\n"
        )
        f = tmp_path / "BACKLOG.md"
        f.write_text(content, encoding="utf-8")
        items = self._parser().get_pending_items(f)
        ids = {i["item_id"] for i in items}
        assert "OLD-001" not in ids
        assert "SCAN-DEPTH-1" in ids

    def test_empty_table_returns_empty(self, tmp_path):
        """Yalnızca header/separator satırı olan tablo boş döner."""
        content = (
            "| # | Başlık | Dosya | Not |\n"
            "|---|--------|-------|-----|\n"
        )
        f = tmp_path / "BACKLOG.md"
        f.write_text(content, encoding="utf-8")
        assert self._parser().get_pending_items(f) == []


# ─────────────────────────────────────────────────────────────────────────────
# TableFormat — mark_in_progress(), mark_done(), mark_failed()
# ─────────────────────────────────────────────────────────────────────────────

class TestTableFormatMutations:
    """TableFormat durum geçişi metodları."""

    def _parser(self):
        from backend.features.backlog_executor.parser import BacklogParser
        return BacklogParser()

    def _table_file(self, tmp_path, rows: str) -> Path:
        f = tmp_path / "BACKLOG.md"
        f.write_text(rows, encoding="utf-8")
        return f

    def test_mark_in_progress_adds_prefix(self, tmp_path):
        """mark_in_progress: | SCAN-DEPTH-1 | → | 🔄SCAN-DEPTH-1 |."""
        f = self._table_file(tmp_path, "| SCAN-DEPTH-1 | başlık | f.py | — |\n")
        result = self._parser().mark_in_progress(f, "SCAN-DEPTH-1")
        assert result is True
        assert "| 🔄SCAN-DEPTH-1 |" in f.read_text(encoding="utf-8")

    def test_mark_in_progress_returns_false_when_not_found(self, tmp_path):
        """Bulunamayan item için False döner."""
        f = self._table_file(tmp_path, "| IMP-FEAT-1 | başlık | f.py | — |\n")
        result = self._parser().mark_in_progress(f, "SCAN-DEPTH-1")
        assert result is False

    def test_mark_done_removes_row(self, tmp_path):
        """mark_done: satır dosyadan kaldırılır."""
        f = self._table_file(
            tmp_path,
            "| SCAN-DEPTH-1 | başlık | f.py | — |\n"
            "| SCAN-DEPTH-2 | diğer | g.py | — |\n",
        )
        result = self._parser().mark_done(f, "SCAN-DEPTH-1")
        assert result is True
        content = f.read_text(encoding="utf-8")
        assert "SCAN-DEPTH-1" not in content
        assert "SCAN-DEPTH-2" in content  # diğer satır korunmalı

    def test_mark_done_also_works_on_in_progress_row(self, tmp_path):
        """mark_done: 🔄 prefiksli satırı da kaldırır."""
        f = self._table_file(tmp_path, "| 🔄SCAN-DEPTH-1 | başlık | f.py | — |\n")
        result = self._parser().mark_done(f, "SCAN-DEPTH-1")
        assert result is True
        assert "SCAN-DEPTH-1" not in f.read_text(encoding="utf-8")

    def test_mark_failed_removes_prefix(self, tmp_path):
        """mark_failed: | 🔄SCAN-DEPTH-1 | → | SCAN-DEPTH-1 | (pending'e döner)."""
        f = self._table_file(tmp_path, "| 🔄SCAN-DEPTH-1 | başlık | f.py | — |\n")
        result = self._parser().mark_failed(f, "SCAN-DEPTH-1")
        assert result is True
        content = f.read_text(encoding="utf-8")
        assert "🔄" not in content
        assert "| SCAN-DEPTH-1 |" in content

    def test_mark_failed_returns_false_for_non_in_progress(self, tmp_path):
        """Pending (prefix yok) satır için mark_failed False döner."""
        f = self._table_file(tmp_path, "| SCAN-DEPTH-1 | başlık | f.py | — |\n")
        result = self._parser().mark_failed(f, "SCAN-DEPTH-1")
        assert result is False

    def test_atomic_write_no_tmp_after_mark(self, tmp_path):
        """Atomic write: .tmp dosyası işlem sonrası yok olmalı."""
        f = self._table_file(tmp_path, "| SCAN-DEPTH-1 | başlık | f.py | — |\n")
        self._parser().mark_in_progress(f, "SCAN-DEPTH-1")
        assert not f.with_suffix(".tmp").exists()


# ─────────────────────────────────────────────────────────────────────────────
# PetekV5 checkbox formatı — çok parçalı ID desteği
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckboxFormatMultiPartIds:
    """PetekV5 formatı: çok parçalı ID'ler (BUG-BE-007, LOG-B001, UIGAP-001)."""

    def _parser(self):
        from backend.features.backlog_executor.parser import BacklogParser
        return BacklogParser()

    def test_double_hyphen_id(self, tmp_path):
        """BUG-BE-007 formatındaki ID okunmalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "- [ ] [BUG-BE-007] **WebSocket CORS `origin: '*'`** — tüm domainler kabul\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f)
        assert len(items) == 1
        assert items[0]["item_id"] == "BUG-BE-007"

    def test_letter_in_number_segment(self, tmp_path):
        """LOG-B001 gibi sayısal segment harf içeriyorsa ID okunmalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "- [ ] [LOG-B001] **auth.service.ts silent catch** — hata yutulur\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f)
        assert len(items) == 1
        assert items[0]["item_id"] == "LOG-B001"

    def test_val_media_style_id(self, tmp_path):
        """VAL-MEDIA-1 gibi üç parçalı ID okunmalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "- [ ] [VAL-MEDIA-1] **media.controller.ts ValidationPipe bypass**\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f)
        assert len(items) == 1
        assert items[0]["item_id"] == "VAL-MEDIA-1"

    def test_uigap_style_id(self, tmp_path):
        """UIGAP-001 formatı (standart) hâlâ çalışmalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "- [ ] [UIGAP-001] **Web — Breed Club sayfaları yok** — endpoint hazır\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f)
        assert len(items) == 1
        assert items[0]["item_id"] == "UIGAP-001"

    def test_done_items_skipped_with_multi_part_id(self, tmp_path):
        """[x] + çok parçalı ID → atlanmalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "- [x] [BUG-BE-007] tamamlandı\n"
            "- [ ] [BUG-BE-008] bekliyor\n",
            encoding="utf-8",
        )
        items = self._parser().get_pending_items(f)
        assert len(items) == 1
        assert items[0]["item_id"] == "BUG-BE-008"

    def test_mark_done_with_multi_part_id(self, tmp_path):
        """mark_done çok parçalı ID için çalışmalı."""
        f = tmp_path / "BACKLOG.md"
        f.write_text("- [ ] [BUG-BE-007] **WebSocket sorunu**\n", encoding="utf-8")
        result = self._parser().mark_done(f, "BUG-BE-007")
        assert result is True
        assert "- [x]" in f.read_text(encoding="utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Format otomatik tespiti
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectFormat:
    """detect_format() — checkbox vs table formatı otomatik tespiti."""

    def test_checkbox_file_returns_checkbox_format(self, tmp_path):
        from backend.features.backlog_executor._formats import (
            CheckboxFormat, detect_format,
        )
        f = tmp_path / "BACKLOG.md"
        f.write_text("- [ ] SEC-001 bekliyor\n", encoding="utf-8")
        assert isinstance(detect_format(f), CheckboxFormat)

    def test_table_file_returns_table_format(self, tmp_path):
        from backend.features.backlog_executor._formats import (
            TableFormat, detect_format,
        )
        f = tmp_path / "BACKLOG.md"
        f.write_text("| SCAN-DEPTH-1 | başlık | f.py | — |\n", encoding="utf-8")
        assert isinstance(detect_format(f), TableFormat)

    def test_mixed_prefers_checkbox(self, tmp_path):
        """Hem checkbox hem tablo varsa checkbox öncelikli."""
        from backend.features.backlog_executor._formats import (
            CheckboxFormat, detect_format,
        )
        f = tmp_path / "BACKLOG.md"
        f.write_text(
            "- [ ] SEC-001 bekliyor\n"
            "| SCAN-DEPTH-1 | başlık | f.py | — |\n",
            encoding="utf-8",
        )
        assert isinstance(detect_format(f), CheckboxFormat)

    def test_empty_file_defaults_to_checkbox(self, tmp_path):
        from backend.features.backlog_executor._formats import (
            CheckboxFormat, detect_format,
        )
        f = tmp_path / "BACKLOG.md"
        f.write_text("", encoding="utf-8")
        assert isinstance(detect_format(f), CheckboxFormat)


# ─────────────────────────────────────────────────────────────────────────────
# Yardımcı
# ─────────────────────────────────────────────────────────────────────────────

def _looks_like_real_id(s: str) -> bool:
    """Test yardımcısı: gerçek item ID gibi görünüyor mu (en az bir rakam var)."""
    return any(c.isdigit() for c in s)


# ─────────────────────────────────────────────────────────────────────────────
# Effort threading — runner.run(effort=...) → body["effort"] = ...
# ─────────────────────────────────────────────────────────────────────────────

class TestEffortThreading:
    """BacklogExecutorAgent.run(effort=...) → Bridge body'sinde effort alanı."""

    def _agent(self):
        from backend.features.backlog_executor.runner import BacklogExecutorAgent
        return BacklogExecutorAgent()

    @pytest.mark.asyncio
    async def test_effort_with_thinking_propagates_to_bridge_body(
        self, tmp_path, mock_lifecycle, mock_settings, project_with_backlog
    ):
        """thinking=True + effort='high' → body['effort']='high' + body['thinking']=True."""
        agent = self._agent()

        captured_body: dict = {}

        async def _capture_post(url, json=None, headers=None):
            captured_body.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"answer": "implement edildi: dosya guncellendi.", "session_id": "executor"}
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = _capture_post

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.get_settings", return_value=mock_settings), \
             patch(f"{_RUNNER_MODULE}.httpx.AsyncClient", return_value=mock_client):
            await agent.run(_PROJECT_ID, max_items=1, effort="high", thinking=True)

        assert captured_body.get("effort") == "high"
        assert captured_body.get("thinking") is True

    @pytest.mark.asyncio
    async def test_effort_set_but_thinking_off_omits_effort(
        self, tmp_path, mock_lifecycle, mock_settings, project_with_backlog
    ):
        """thinking=False + effort='high' → body'de effort yok (VS Code UX gate)."""
        agent = self._agent()

        captured_body: dict = {}

        async def _capture_post(url, json=None, headers=None):
            captured_body.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"answer": "implement edildi: dosya guncellendi.", "session_id": "executor"}
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = _capture_post

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.get_settings", return_value=mock_settings), \
             patch(f"{_RUNNER_MODULE}.httpx.AsyncClient", return_value=mock_client):
            await agent.run(_PROJECT_ID, max_items=1, effort="high", thinking=False)

        assert "effort" not in captured_body
        assert "thinking" not in captured_body

    @pytest.mark.asyncio
    async def test_effort_off_omitted_from_body(
        self, tmp_path, mock_lifecycle, mock_settings, project_with_backlog
    ):
        """effort=None / off → body'de effort alanı bulunmamalı."""
        agent = self._agent()

        captured_body: dict = {}

        async def _capture_post(url, json=None, headers=None):
            captured_body.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"answer": "implement edildi: dosya guncellendi.", "session_id": "executor"}
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = _capture_post

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.get_settings", return_value=mock_settings), \
             patch(f"{_RUNNER_MODULE}.httpx.AsyncClient", return_value=mock_client):
            await agent.run(_PROJECT_ID, max_items=1)  # effort defaults to None

        assert "effort" not in captured_body

    @pytest.mark.asyncio
    async def test_invalid_effort_silently_omitted(
        self, tmp_path, mock_lifecycle, mock_settings, project_with_backlog
    ):
        """Geçersiz effort whitelist'lenir → body'ye yazılmaz (silent skip)."""
        agent = self._agent()

        captured_body: dict = {}

        async def _capture_post(url, json=None, headers=None):
            captured_body.update(json or {})
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {"answer": "implement edildi: dosya guncellendi.", "session_id": "executor"}
            return resp

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = _capture_post

        with patch(_PROJECT_GET, new=AsyncMock(return_value=project_with_backlog)), \
             patch(_LIFECYCLE, return_value=mock_lifecycle), \
             patch(f"{_RUNNER_MODULE}.get_settings", return_value=mock_settings), \
             patch(f"{_RUNNER_MODULE}.httpx.AsyncClient", return_value=mock_client):
            await agent.run(_PROJECT_ID, max_items=1, effort="ultra")

        assert "effort" not in captured_body
