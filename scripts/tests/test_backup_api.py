"""backup_api endpoint testleri — tüm bağımlılıklar mock'lanır.

Test kategorileri:
  - POST /agent/export (sync)       — essential, full, custom kapsam
  - POST /agent/export (async_mode) — 202 + task_id
  - GET  /agent/export/status       — running, done, error, 404
  - GET  /agent/export/download     — done, running (409), error (400), 404
  - POST /agent/import              — başarı, format hatası, geçersiz mod

httpx.AsyncClient + ASGITransport kullanılır (in-process, DB erişimi yok).
"""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.features.backup._export_task_registry import ExportTask, ExportTaskRegistry
from backend.features.backup._manifest import BackupManifest
from backend.features.backup._protocol import ImportMode, ImportResult
from backend.features.backup._scope import ExportScope

API_KEY = "test-api-key-backup"
HEADERS = {"X-Api-Key": API_KEY}


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    """Yalnızca backup_api router'ını içeren izole test uygulaması."""
    from backend.routers.api.backup_api import router

    app = FastAPI()
    app.include_router(router, prefix="/agent")
    return app


def _mock_secret(value: str = API_KEY):
    s = MagicMock()
    s.get_secret_value.return_value = value
    return s


def _patch_auth():
    """API key + rate limiter guard'larını devre dışı bırakır."""
    return [
        patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"),
        patch("backend.routers.api._deps.require_api_rate_limit", return_value=None),
    ]


def _make_manifest() -> BackupManifest:
    return BackupManifest(
        version=1,
        created_at="2026-05-08T12:00:00+00:00",
        hostname="testhost",
        app_version="99-root",
        scope_flags={},
        table_row_counts={"projects": 4, "messages": 100},
        file_count=5,
        checksum="abc123",
    )


def _make_import_result(**kwargs) -> ImportResult:
    defaults = dict(
        tables_processed=["projects", "messages"],
        rows_inserted={"projects": 4, "messages": 100},
        rows_skipped={"messages": 2},
        errors=[],
    )
    defaults.update(kwargs)
    return ImportResult(**defaults)


# ---------------------------------------------------------------------------
# POST /agent/export — sync mod
# ---------------------------------------------------------------------------


class TestExportSync:
    @pytest.mark.asyncio
    async def test_essential_scope_returns_binary(self, tmp_path: Path):
        """Essential kapsam → 200 + application/octet-stream."""
        fake_file = tmp_path / "backup.99rb"
        fake_file.write_bytes(b"\x99RBK_data")

        mock_service = MagicMock()
        mock_service.create_backup = AsyncMock(return_value=_make_manifest())

        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
             patch("backend.routers.api.backup_api.get_export_service", return_value=mock_service), \
             patch("backend.routers.api.backup_api._export_sync") as mock_sync:

            from fastapi.responses import FileResponse
            mock_sync.return_value = FileResponse(
                path=str(fake_file),
                media_type="application/octet-stream",
                filename="backup.99rb",
            )

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/agent/export",
                    json={"scope": "essential"},
                    headers=HEADERS,
                )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_full_scope_calls_export_service(self, tmp_path: Path):
        """Full kapsam → ExportService.create_backup ExportScope.full() ile çağrılır."""
        fake_file = tmp_path / "backup_full.99rb"
        fake_file.write_bytes(b"\x99RBK")

        mock_service = MagicMock()
        mock_service.create_backup = AsyncMock(return_value=_make_manifest())

        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
             patch("backend.routers.api.backup_api.get_export_service", return_value=mock_service), \
             patch("backend.routers.api.backup_api._export_sync") as mock_sync:

            from fastapi.responses import FileResponse
            mock_sync.return_value = FileResponse(
                path=str(fake_file),
                media_type="application/octet-stream",
                filename="backup_full.99rb",
            )

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/agent/export",
                    json={"scope": "full"},
                    headers=HEADERS,
                )

        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_custom_scope_uses_individual_flags(self):
        """scope=custom → ExportScope bireysel flag'lerden oluşturulur."""
        from backend.routers.api.backup_api import _scope_from_request, ExportRequest

        body = ExportRequest(
            scope="custom",
            include_messages=False,
            include_plans=True,
            include_bridge_calls=True,
            messages_limit=500,
        )
        scope = _scope_from_request(body)

        assert scope.include_messages is False
        assert scope.include_plans is True
        assert scope.include_bridge_calls is True
        assert scope.messages_limit == 500

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_401(self):
        """API key olmadan → 401."""
        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post("/agent/export", json={"scope": "essential"})

        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /agent/export — async mod
# ---------------------------------------------------------------------------


class TestExportAsync:
    @pytest.mark.asyncio
    async def test_async_mode_returns_202_with_task_id(self):
        """async_mode=true → 202 + task_id."""
        ExportTaskRegistry.clear()
        app = _make_app()

        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
             patch("backend.routers.api.backup_api.asyncio.create_task",
                   side_effect=lambda coro: (coro.close(), MagicMock())[1]):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/agent/export",
                    json={"scope": "essential", "async_mode": True},
                    headers=HEADERS,
                )

        assert resp.status_code == 202
        body = resp.json()
        assert "task_id" in body
        assert body["status"] == "running"

    @pytest.mark.asyncio
    async def test_async_mode_registers_task(self):
        """async_mode=true → ExportTaskRegistry'de görev oluşturulur."""
        ExportTaskRegistry.clear()
        app = _make_app()

        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
             patch("backend.routers.api.backup_api.asyncio.create_task",
                   side_effect=lambda coro: (coro.close(), MagicMock())[1]):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/agent/export",
                    json={"scope": "essential", "async_mode": True},
                    headers=HEADERS,
                )

        task_id = resp.json()["task_id"]
        task = ExportTaskRegistry.get(task_id)
        assert task is not None
        assert task.status == "running"


# ---------------------------------------------------------------------------
# GET /agent/export/status/{task_id}
# ---------------------------------------------------------------------------


class TestExportStatus:
    @pytest.mark.asyncio
    async def test_running_task_returns_running_status(self):
        """Çalışan görev → status: running."""
        ExportTaskRegistry.clear()
        task = ExportTask.new("test-running-task-id")
        ExportTaskRegistry.register(task)

        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/agent/export/status/test-running-task-id",
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        assert resp.json()["status"] == "running"
        assert "download_url" not in resp.json()

    @pytest.mark.asyncio
    async def test_done_task_returns_manifest_and_download_url(self, tmp_path: Path):
        """Tamamlanmış görev → manifest + download_url."""
        ExportTaskRegistry.clear()
        task = ExportTask.new("test-done-task-id")
        ExportTaskRegistry.register(task)
        fake_path = tmp_path / "backup.99rb"
        fake_path.write_bytes(b"data")
        ExportTaskRegistry.mark_done("test-done-task-id", _make_manifest(), fake_path)

        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/agent/export/status/test-done-task-id",
                    headers=HEADERS,
                )

        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "done"
        assert "manifest" in body
        assert body["download_url"] == "/agent/export/download/test-done-task-id"

    @pytest.mark.asyncio
    async def test_error_task_returns_error_message(self):
        """Hatalı görev → status: error + hata mesajı."""
        ExportTaskRegistry.clear()
        task = ExportTask.new("test-error-task-id")
        ExportTaskRegistry.register(task)
        ExportTaskRegistry.mark_error("test-error-task-id", "Disk hatası")

        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/agent/export/status/test-error-task-id",
                    headers=HEADERS,
                )

        body = resp.json()
        assert resp.status_code == 200
        assert body["status"] == "error"
        assert body["error"] == "Disk hatası"

    @pytest.mark.asyncio
    async def test_unknown_task_id_returns_404(self):
        """Bilinmeyen task_id → 404."""
        ExportTaskRegistry.clear()
        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/agent/export/status/nonexistent-task-id",
                    headers=HEADERS,
                )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /agent/export/download/{task_id}
# ---------------------------------------------------------------------------


class TestExportDownload:
    @pytest.mark.asyncio
    async def test_done_task_returns_file(self, tmp_path: Path):
        """Tamamlanmış görev → 200 + binary dosya içeriği."""
        ExportTaskRegistry.clear()
        task = ExportTask.new("test-dl-done")
        ExportTaskRegistry.register(task)
        fake_path = tmp_path / "backup_dl.99rb"
        fake_path.write_bytes(b"\x99RBK_content")
        ExportTaskRegistry.mark_done("test-dl-done", _make_manifest(), fake_path)

        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/agent/export/download/test-dl-done",
                    headers=HEADERS,
                )

        assert resp.status_code == 200
        assert resp.content == b"\x99RBK_content"

    @pytest.mark.asyncio
    async def test_running_task_returns_409(self):
        """Çalışan görev → 409 Conflict."""
        ExportTaskRegistry.clear()
        task = ExportTask.new("test-dl-running")
        ExportTaskRegistry.register(task)

        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/agent/export/download/test-dl-running",
                    headers=HEADERS,
                )

        assert resp.status_code == 409

    @pytest.mark.asyncio
    async def test_unknown_task_returns_404(self):
        """Bilinmeyen task_id → 404."""
        ExportTaskRegistry.clear()
        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.get(
                    "/agent/export/download/unknown-dl-id",
                    headers=HEADERS,
                )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /agent/import
# ---------------------------------------------------------------------------


class TestImport:
    @pytest.mark.asyncio
    async def test_import_success_returns_result(self, tmp_path: Path):
        """Geçerli .99rb dosyası → 200 + ImportResult JSON."""
        fake_backup = tmp_path / "backup.99rb"
        fake_backup.write_bytes(b"\x99RBKfakedata")

        mock_service = MagicMock()
        mock_service.restore_backup = AsyncMock(return_value=_make_import_result())

        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
             patch("backend.routers.api.backup_api.get_import_service", return_value=mock_service):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/agent/import",
                    headers=HEADERS,
                    files={"file": ("backup.99rb", fake_backup.read_bytes(), "application/octet-stream")},
                    data={"mode": "merge"},
                )

        assert resp.status_code == 200
        body = resp.json()
        assert body["rows_inserted"]["projects"] == 4
        assert body["rows_inserted"]["messages"] == 100
        assert body["errors"] == []

    @pytest.mark.asyncio
    async def test_import_invalid_format_returns_400(self, tmp_path: Path):
        """Geçersiz format → 400."""
        bad_file = tmp_path / "bad.99rb"
        bad_file.write_bytes(b"not_a_valid_backup_file")

        mock_service = MagicMock()
        mock_service.restore_backup = AsyncMock(side_effect=ValueError("Geçersiz dosya formatı"))

        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
             patch("backend.routers.api.backup_api.get_import_service", return_value=mock_service):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/agent/import",
                    headers=HEADERS,
                    files={"file": ("bad.99rb", bad_file.read_bytes(), "application/octet-stream")},
                    data={"mode": "merge"},
                )

        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_import_invalid_mode_returns_400(self, tmp_path: Path):
        """Geçersiz mod → 400."""
        fake_backup = tmp_path / "backup.99rb"
        fake_backup.write_bytes(b"\x99RBK")

        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/agent/import",
                    headers=HEADERS,
                    files={"file": ("backup.99rb", fake_backup.read_bytes(), "application/octet-stream")},
                    data={"mode": "invalid_mode"},
                )

        assert resp.status_code == 400
        assert "Geçersiz mod" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_import_replace_mode_passed_to_service(self, tmp_path: Path):
        """mode=replace → ImportMode.REPLACE ile hizmet çağrılır."""
        fake_backup = tmp_path / "backup.99rb"
        fake_backup.write_bytes(b"\x99RBK")

        mock_service = MagicMock()
        mock_service.restore_backup = AsyncMock(return_value=_make_import_result())

        app = _make_app()
        with patch("backend.guards.api_key.settings", api_key=_mock_secret(), environment="development"), \
             patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
             patch("backend.routers.api.backup_api.get_import_service", return_value=mock_service):

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    "/agent/import",
                    headers=HEADERS,
                    files={"file": ("backup.99rb", fake_backup.read_bytes(), "application/octet-stream")},
                    data={"mode": "replace"},
                )

        assert resp.status_code == 200
        # ImportMode.REPLACE ile çağrıldığını doğrula
        call_args = mock_service.restore_backup.call_args
        assert call_args[0][1] == ImportMode.REPLACE


# ---------------------------------------------------------------------------
# Yardımcı birim testleri — _scope_from_request, _parse_import_mode
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_scope_essential(self):
        from backend.routers.api.backup_api import _scope_from_request, ExportRequest
        scope = _scope_from_request(ExportRequest(scope="essential"))
        assert scope.include_bridge_calls is False
        assert scope.include_media is False

    def test_scope_full(self):
        from backend.routers.api.backup_api import _scope_from_request, ExportRequest
        scope = _scope_from_request(ExportRequest(scope="full"))
        assert scope.include_bridge_calls is True
        assert scope.include_media is True
        assert scope.messages_limit == 0

    def test_parse_import_mode_merge(self):
        from backend.routers.api.backup_api import _parse_import_mode
        assert _parse_import_mode("merge") == ImportMode.MERGE

    def test_parse_import_mode_replace(self):
        from backend.routers.api.backup_api import _parse_import_mode
        assert _parse_import_mode("replace") == ImportMode.REPLACE

    def test_parse_import_mode_skip(self):
        from backend.routers.api.backup_api import _parse_import_mode
        assert _parse_import_mode("skip") == ImportMode.SKIP_EXISTING

    def test_parse_import_mode_invalid_raises_400(self):
        from backend.routers.api.backup_api import _parse_import_mode
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            _parse_import_mode("bad_mode")
        assert exc_info.value.status_code == 400
