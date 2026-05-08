"""ExportService unit testleri — tüm bağımlılıklar mock'lanır.

Rapor referansı: §4.9, §7.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.features.backup._manifest import BackupManifest
from backend.features.backup._scope import ExportScope
from backend.features.export_service import ExportService, _NullFileExporter, _get_hostname, get_export_service


# ---------------------------------------------------------------------------
# Fixture yardımcıları
# ---------------------------------------------------------------------------


def _make_service(db_data: dict | None = None, file_data: dict | None = None):
    """Mock bağımlılıklarla ExportService döndürür."""
    db_exporter = AsyncMock()
    db_exporter.export.return_value = db_data or {"projects": [], "messages": []}

    file_exporter = AsyncMock()
    file_exporter.export.return_value = file_data or {}

    writer = MagicMock()

    serializer = MagicMock()

    service = ExportService(
        db_exporter=db_exporter,
        file_exporter=file_exporter,
        writer=writer,
        serializer=serializer,
    )
    return service, db_exporter, file_exporter, writer


# ---------------------------------------------------------------------------
# ExportService.create_backup testleri
# ---------------------------------------------------------------------------


class TestCreateBackup:
    @pytest.mark.asyncio
    async def test_calls_db_exporter(self):
        service, db_exp, _, _ = _make_service()
        scope = ExportScope.essential()
        output = Path("/tmp/test_backup.99rb")

        await service.create_backup(scope, output)

        db_exp.export.assert_awaited_once_with(scope)

    @pytest.mark.asyncio
    async def test_calls_file_exporter(self):
        service, _, file_exp, _ = _make_service()
        scope = ExportScope.essential()
        output = Path("/tmp/test_backup.99rb")

        await service.create_backup(scope, output)

        file_exp.export.assert_awaited_once_with(scope)

    @pytest.mark.asyncio
    async def test_calls_writer_write(self):
        db_data = {"projects": [{"id": "p1"}], "messages": []}
        file_data = {"some/file.txt": b"content"}
        service, _, _, writer = _make_service(db_data=db_data, file_data=file_data)
        scope = ExportScope()
        output = Path("/tmp/test_backup.99rb")

        await service.create_backup(scope, output)

        writer.write.assert_called_once()
        call_args = writer.write.call_args
        assert call_args[0][0] == output          # path
        assert isinstance(call_args[0][1], BackupManifest)  # manifest
        assert call_args[0][2] == db_data         # db_data
        assert call_args[0][3] == file_data        # file_data

    @pytest.mark.asyncio
    async def test_returns_backup_manifest(self):
        service, _, _, _ = _make_service()
        scope = ExportScope()
        output = Path("/tmp/test_backup.99rb")

        result = await service.create_backup(scope, output)

        assert isinstance(result, BackupManifest)

    @pytest.mark.asyncio
    async def test_manifest_has_correct_scope_flags(self):
        service, _, _, _ = _make_service()
        scope = ExportScope(include_messages=False, include_plans=True)
        output = Path("/tmp/test_backup.99rb")

        manifest = await service.create_backup(scope, output)

        assert manifest.scope_flags["include_messages"] is False
        assert manifest.scope_flags["include_plans"] is True

    @pytest.mark.asyncio
    async def test_manifest_table_row_counts(self):
        db_data = {
            "projects": [{"id": "p1"}, {"id": "p2"}],
            "messages": [{"id": "m1"}],
        }
        service, _, _, _ = _make_service(db_data=db_data)
        scope = ExportScope()
        output = Path("/tmp/test_backup.99rb")

        manifest = await service.create_backup(scope, output)

        assert manifest.table_row_counts["projects"] == 2
        assert manifest.table_row_counts["messages"] == 1

    @pytest.mark.asyncio
    async def test_manifest_file_count(self):
        file_data = {"a.txt": b"x", "b.txt": b"y", "c.txt": b"z"}
        service, _, _, _ = _make_service(file_data=file_data)
        scope = ExportScope()
        output = Path("/tmp/test_backup.99rb")

        manifest = await service.create_backup(scope, output)

        assert manifest.file_count == 3

    @pytest.mark.asyncio
    async def test_manifest_has_created_at(self):
        service, _, _, _ = _make_service()
        scope = ExportScope()
        output = Path("/tmp/test_backup.99rb")

        manifest = await service.create_backup(scope, output)

        assert manifest.created_at  # boş olmamalı
        assert "T" in manifest.created_at  # ISO8601 formatı

    @pytest.mark.asyncio
    async def test_manifest_hostname(self):
        service, _, _, _ = _make_service()
        scope = ExportScope()
        output = Path("/tmp/test_backup.99rb")

        manifest = await service.create_backup(scope, output)

        assert manifest.hostname  # boş olmamalı

    @pytest.mark.asyncio
    async def test_propagates_db_exporter_exception(self):
        service, db_exp, _, _ = _make_service()
        db_exp.export.side_effect = RuntimeError("DB hatası")
        scope = ExportScope()
        output = Path("/tmp/test_backup.99rb")

        with pytest.raises(RuntimeError, match="DB hatası"):
            await service.create_backup(scope, output)


# ---------------------------------------------------------------------------
# _NullFileExporter testleri
# ---------------------------------------------------------------------------


class TestNullFileExporter:
    @pytest.mark.asyncio
    async def test_returns_empty_dict(self):
        exporter = _NullFileExporter()
        result = await exporter.export(ExportScope())
        assert result == {}

    @pytest.mark.asyncio
    async def test_works_with_any_scope(self):
        exporter = _NullFileExporter()
        for scope in [ExportScope.full(), ExportScope.essential(), ExportScope()]:
            result = await exporter.export(scope)
            assert result == {}


# ---------------------------------------------------------------------------
# _get_hostname testleri
# ---------------------------------------------------------------------------


class TestGetHostname:
    def test_returns_string(self):
        result = _get_hostname()
        assert isinstance(result, str)
        assert len(result) > 0

    def test_fallback_on_error(self):
        with patch("backend.features.export_service.socket.gethostname", side_effect=OSError):
            result = _get_hostname()
        assert result == "unknown"


# ---------------------------------------------------------------------------
# get_export_service factory testleri
# ---------------------------------------------------------------------------


class TestGetExportServiceFactory:
    def test_returns_export_service(self):
        service = get_export_service()
        assert isinstance(service, ExportService)

    def test_service_has_db_exporter(self):
        from backend.features.backup._db_exporter import DbExporter
        service = get_export_service()
        assert isinstance(service._db_exporter, DbExporter)

    def test_service_has_local_file_exporter(self):
        from backend.features.backup._file_exporter import LocalFileExporter
        service = get_export_service()
        assert isinstance(service._file_exporter, LocalFileExporter)

    def test_service_has_writer(self):
        from backend.features.backup._writer import BackupWriter
        service = get_export_service()
        assert isinstance(service._writer, BackupWriter)
