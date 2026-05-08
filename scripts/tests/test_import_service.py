"""ImportService unit testleri — tüm bağımlılıklar mock'lanır.

Rapor referansı: §4.9, §7.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.features.backup._manifest import BackupManifest
from backend.features.backup._protocol import ImportMode, ImportResult
from backend.features.import_service import (
    ImportService,
    _NullFileImporter,
    get_import_service,
)


# ---------------------------------------------------------------------------
# Fixture yardımcıları
# ---------------------------------------------------------------------------


def _make_manifest(**kwargs) -> BackupManifest:
    defaults = dict(
        version=1,
        created_at="2026-05-08T12:00:00+00:00",
        hostname="testhost",
        app_version="99-root",
        scope_flags={},
        table_row_counts={"projects": 2},
        file_count=0,
        checksum="abc123",
    )
    defaults.update(kwargs)
    return BackupManifest(**defaults)


def _make_service(
    db_data: dict | None = None,
    file_data: dict | None = None,
    db_result: ImportResult | None = None,
):
    """Mock bağımlılıklarla ImportService döndürür."""
    manifest = _make_manifest()
    reader = MagicMock()
    reader.read.return_value = (
        manifest,
        db_data or {"projects": []},
        file_data or {},
    )

    db_importer = AsyncMock()
    db_importer.import_data.return_value = db_result or ImportResult(
        tables_processed=["projects"]
    )

    file_importer = AsyncMock()
    file_importer.import_files.return_value = {}

    service = ImportService(
        db_importer=db_importer,
        file_importer=file_importer,
        reader=reader,
    )
    return service, reader, db_importer, file_importer


# ---------------------------------------------------------------------------
# ImportService.restore_backup testleri
# ---------------------------------------------------------------------------


class TestRestoreBackup:
    @pytest.mark.asyncio
    async def test_calls_reader(self):
        service, reader, _, _ = _make_service()
        backup_path = Path("/tmp/test.99rb")

        await service.restore_backup(backup_path)

        reader.read.assert_called_once_with(backup_path)

    @pytest.mark.asyncio
    async def test_calls_db_importer_with_data_and_mode(self):
        db_data = {"messages": [{"id": "1"}]}
        service, _, db_importer, _ = _make_service(db_data=db_data)
        backup_path = Path("/tmp/test.99rb")

        await service.restore_backup(backup_path, mode=ImportMode.REPLACE)

        db_importer.import_data.assert_awaited_once_with(db_data, ImportMode.REPLACE)

    @pytest.mark.asyncio
    async def test_calls_file_importer(self):
        file_data = {"projects/foo/CLAUDE.md": b"content"}
        service, _, _, file_importer = _make_service(file_data=file_data)

        await service.restore_backup(Path("/tmp/test.99rb"))

        file_importer.import_files.assert_awaited_once_with(file_data)

    @pytest.mark.asyncio
    async def test_default_mode_is_merge(self):
        service, _, db_importer, _ = _make_service()

        await service.restore_backup(Path("/tmp/test.99rb"))

        _, kwargs = db_importer.import_data.call_args
        positional = db_importer.import_data.call_args.args
        mode_passed = positional[1] if len(positional) > 1 else kwargs.get("mode")
        assert mode_passed == ImportMode.MERGE

    @pytest.mark.asyncio
    async def test_returns_db_result(self):
        expected = ImportResult(
            tables_processed=["messages", "projects"],
            rows_inserted={"messages": 10, "projects": 2},
        )
        service, _, _, _ = _make_service(db_result=expected)

        result = await service.restore_backup(Path("/tmp/test.99rb"))

        assert result is expected

    @pytest.mark.asyncio
    async def test_reader_exception_propagates(self):
        service, reader, _, _ = _make_service()
        reader.read.side_effect = ValueError("Geçersiz format")

        with pytest.raises(ValueError, match="Geçersiz format"):
            await service.restore_backup(Path("/tmp/bad.99rb"))

    @pytest.mark.asyncio
    async def test_all_import_modes_forwarded(self):
        for mode in ImportMode:
            service, _, db_importer, _ = _make_service()
            await service.restore_backup(Path("/tmp/test.99rb"), mode=mode)
            positional = db_importer.import_data.call_args.args
            assert positional[1] == mode


# ---------------------------------------------------------------------------
# _NullFileImporter testleri
# ---------------------------------------------------------------------------


class TestNullFileImporter:
    @pytest.mark.asyncio
    async def test_returns_empty_dict(self):
        importer = _NullFileImporter()
        result = await importer.import_files({"some/file": b"content"})
        assert result == {}

    @pytest.mark.asyncio
    async def test_accepts_empty_files(self):
        importer = _NullFileImporter()
        result = await importer.import_files({})
        assert result == {}

    def test_protocol_compatibility(self):
        from backend.features.backup._protocol import FileImporter

        importer = _NullFileImporter()
        assert isinstance(importer, FileImporter)


# ---------------------------------------------------------------------------
# get_import_service factory testi
# ---------------------------------------------------------------------------


class TestGetImportService:
    def test_returns_import_service(self):
        service = get_import_service()
        assert isinstance(service, ImportService)

    def test_uses_local_file_importer(self):
        from backend.features.backup._file_importer import LocalFileImporter
        service = get_import_service()
        assert isinstance(service._file_importer, LocalFileImporter)

    def test_uses_db_importer(self):
        from backend.features.backup._db_importer import DbImporter

        service = get_import_service()
        assert isinstance(service._db_importer, DbImporter)

    def test_uses_backup_reader(self):
        from backend.features.backup._reader import BackupReader

        service = get_import_service()
        assert isinstance(service._reader, BackupReader)
