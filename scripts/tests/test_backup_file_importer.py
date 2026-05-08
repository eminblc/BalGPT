"""LocalFileImporter unit testleri — tmp_path tabanlı gerçek dosya sistemi.

Test kategorileri:
  - Temel dosya yazma
  - Dizin otomatik oluşturma
  - Mevcut dosyaları .bak ile yedekleme
  - Path traversal koruması
  - Sembolik link koruması
  - Boş dict davranışı
  - Durum dict içeriği ("ok" / "error:")
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.features.backup._file_importer import LocalFileImporter


# ---------------------------------------------------------------------------
# Temel yazma testleri
# ---------------------------------------------------------------------------


class TestLocalFileImporterBasic:
    @pytest.mark.asyncio
    async def test_returns_dict(self, tmp_path: Path):
        importer = LocalFileImporter(tmp_path)
        result = await importer.import_files({})
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_writes_single_file(self, tmp_path: Path):
        importer = LocalFileImporter(tmp_path)
        files = {"conv_history/session_001.json": b'{"id": "001"}'}
        result = await importer.import_files(files)

        assert result["conv_history/session_001.json"] == "ok"
        written = tmp_path / "conv_history" / "session_001.json"
        assert written.exists()
        assert written.read_bytes() == b'{"id": "001"}'

    @pytest.mark.asyncio
    async def test_writes_multiple_files(self, tmp_path: Path):
        importer = LocalFileImporter(tmp_path)
        files = {
            "projects/proj/CLAUDE.md": b"# Claude",
            "projects/proj/BACKLOG.md": b"## Backlog",
            "conv_history/ses.json": b"{}",
        }
        result = await importer.import_files(files)

        assert all(v == "ok" for v in result.values())
        assert (tmp_path / "projects" / "proj" / "CLAUDE.md").read_bytes() == b"# Claude"

    @pytest.mark.asyncio
    async def test_returns_ok_status_for_each_file(self, tmp_path: Path):
        importer = LocalFileImporter(tmp_path)
        files = {"a.txt": b"a", "b.txt": b"b"}
        result = await importer.import_files(files)

        assert result["a.txt"] == "ok"
        assert result["b.txt"] == "ok"

    @pytest.mark.asyncio
    async def test_empty_files_dict_returns_empty(self, tmp_path: Path):
        importer = LocalFileImporter(tmp_path)
        result = await importer.import_files({})
        assert result == {}


# ---------------------------------------------------------------------------
# Dizin oluşturma testleri
# ---------------------------------------------------------------------------


class TestDirectoryCreation:
    @pytest.mark.asyncio
    async def test_creates_missing_parent_dirs(self, tmp_path: Path):
        importer = LocalFileImporter(tmp_path)
        files = {"a/b/c/deep.md": b"deep content"}
        result = await importer.import_files(files)

        assert result["a/b/c/deep.md"] == "ok"
        assert (tmp_path / "a" / "b" / "c" / "deep.md").read_bytes() == b"deep content"

    @pytest.mark.asyncio
    async def test_creates_nested_structure(self, tmp_path: Path):
        importer = LocalFileImporter(tmp_path)
        files = {
            "projects/my_proj/src/main.py": b"# main",
            "projects/my_proj/src/utils.py": b"# utils",
        }
        result = await importer.import_files(files)

        assert all(v == "ok" for v in result.values())
        assert (tmp_path / "projects" / "my_proj" / "src" / "main.py").exists()


# ---------------------------------------------------------------------------
# .bak yedekleme testleri
# ---------------------------------------------------------------------------


class TestBackupOnOverwrite:
    @pytest.mark.asyncio
    async def test_existing_file_renamed_to_bak(self, tmp_path: Path):
        existing = tmp_path / "data.json"
        existing.write_bytes(b"original")

        importer = LocalFileImporter(tmp_path)
        result = await importer.import_files({"data.json": b"new content"})

        assert result["data.json"] == "ok"
        assert existing.read_bytes() == b"new content"
        bak = tmp_path / "data.json.bak"
        assert bak.exists()
        assert bak.read_bytes() == b"original"

    @pytest.mark.asyncio
    async def test_nested_existing_file_renamed_to_bak(self, tmp_path: Path):
        (tmp_path / "sub").mkdir()
        existing = tmp_path / "sub" / "file.txt"
        existing.write_bytes(b"old")

        importer = LocalFileImporter(tmp_path)
        result = await importer.import_files({"sub/file.txt": b"new"})

        assert result["sub/file.txt"] == "ok"
        assert existing.read_bytes() == b"new"
        assert (tmp_path / "sub" / "file.txt.bak").read_bytes() == b"old"

    @pytest.mark.asyncio
    async def test_nonexistent_file_written_without_bak(self, tmp_path: Path):
        importer = LocalFileImporter(tmp_path)
        result = await importer.import_files({"new_file.txt": b"content"})

        assert result["new_file.txt"] == "ok"
        assert (tmp_path / "new_file.txt").read_bytes() == b"content"
        assert not (tmp_path / "new_file.txt.bak").exists()


# ---------------------------------------------------------------------------
# Path traversal güvenlik testleri
# ---------------------------------------------------------------------------


class TestPathTraversalProtection:
    @pytest.mark.asyncio
    async def test_relative_path_traversal_blocked(self, tmp_path: Path):
        """../escape girişimi reddedilmeli."""
        importer = LocalFileImporter(tmp_path)
        files = {"../outside.txt": b"malicious"}
        result = await importer.import_files(files)

        assert result["../outside.txt"].startswith("error:")
        # Dosya data_dir dışına yazılmamış olmalı
        outside = tmp_path.parent / "outside.txt"
        assert not outside.exists()

    @pytest.mark.asyncio
    async def test_deep_traversal_blocked(self, tmp_path: Path):
        """../../etc/passwd tipi girişim reddedilmeli."""
        importer = LocalFileImporter(tmp_path)
        files = {"../../etc/passwd": b"root:x:0:0"}
        result = await importer.import_files(files)

        status = result["../../etc/passwd"]
        assert status.startswith("error:")

    @pytest.mark.asyncio
    async def test_valid_paths_still_work_after_traversal_check(self, tmp_path: Path):
        """Geçerli yollar traversal kontrolünden etkilenmemeli."""
        importer = LocalFileImporter(tmp_path)
        files = {
            "../outside.txt": b"bad",
            "valid/file.txt": b"good",
        }
        result = await importer.import_files(files)

        assert result["valid/file.txt"] == "ok"
        assert (tmp_path / "valid" / "file.txt").read_bytes() == b"good"


# ---------------------------------------------------------------------------
# Sembolik link koruması
# ---------------------------------------------------------------------------


class TestSymlinkProtection:
    @pytest.mark.asyncio
    async def test_symlink_target_not_overwritten(self, tmp_path: Path, tmp_path_factory):
        """Sembolik link hedefi silinip dosyayla değiştirilmemeli."""
        outside = tmp_path_factory.mktemp("outside") / "real.txt"
        outside.write_bytes(b"original")

        link = tmp_path / "link.txt"
        link.symlink_to(outside)

        importer = LocalFileImporter(tmp_path)
        result = await importer.import_files({"link.txt": b"injected"})

        assert result["link.txt"].startswith("error:")
        # Orijinal içerik korunmalı
        assert outside.read_bytes() == b"original"


# ---------------------------------------------------------------------------
# Default data_dir testleri
# ---------------------------------------------------------------------------


class TestDefaultDataDir:
    def test_constructor_accepts_none(self):
        importer = LocalFileImporter(None)
        assert importer._data_dir.name == "data"

    def test_constructor_resolves_path(self, tmp_path: Path):
        importer = LocalFileImporter(tmp_path)
        assert importer._data_dir == tmp_path.resolve()


# ---------------------------------------------------------------------------
# Hata durumu testleri
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_multiple_files_error_does_not_stop_others(self, tmp_path: Path):
        """Bir dosya başarısız olsa da diğerleri yazılmaya devam etmeli."""
        importer = LocalFileImporter(tmp_path)
        files = {
            "../bad.txt": b"bad",
            "good.txt": b"good",
        }
        result = await importer.import_files(files)

        # bad.txt hata, good.txt ok
        assert result["../bad.txt"].startswith("error:")
        assert result["good.txt"] == "ok"
        assert (tmp_path / "good.txt").exists()
