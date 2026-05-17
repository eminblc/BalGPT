"""LocalFileExporter unit testleri — tmp_path tabanlı gerçek dosya sistemi.

Test kategorileri:
  - Temel dosya okuma (projects, conv_history, media)
  - Scope flag'lerine göre dizin filtreleme
  - Path traversal koruması
  - Sembolik link atlama
  - Boş / varolmayan dizin davranışı
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.features.backup._file_exporter import LocalFileExporter
from backend.features.backup._scope import ExportScope


# ---------------------------------------------------------------------------
# Yardımcı fixture
# ---------------------------------------------------------------------------


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    """Gerçekçi data/ dizin yapısını oluşturur."""
    (tmp_path / "projects" / "proj_a").mkdir(parents=True)
    (tmp_path / "projects" / "proj_a" / "CLAUDE.md").write_bytes(b"# Project A")
    (tmp_path / "projects" / "proj_a" / "BACKLOG.md").write_bytes(b"## Backlog")

    (tmp_path / "conv_history").mkdir()
    (tmp_path / "conv_history" / "session_001.json").write_bytes(b'{"id": "001"}')
    (tmp_path / "conv_history" / "session_002.json").write_bytes(b'{"id": "002"}')

    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "photo.jpg").write_bytes(b"\xff\xd8\xff")

    return tmp_path


# ---------------------------------------------------------------------------
# Temel okuma testleri
# ---------------------------------------------------------------------------


class TestLocalFileExporterBasic:
    @pytest.mark.asyncio
    async def test_returns_dict(self, data_dir: Path):
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(ExportScope())
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_exports_project_files_when_enabled(self, data_dir: Path):
        scope = ExportScope(include_project_files=True, include_conv_history=False, include_media=False)
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)

        assert "projects/proj_a/CLAUDE.md" in result
        assert "projects/proj_a/BACKLOG.md" in result
        assert result["projects/proj_a/CLAUDE.md"] == b"# Project A"

    @pytest.mark.asyncio
    async def test_exports_conv_history_when_enabled(self, data_dir: Path):
        scope = ExportScope(include_project_files=False, include_conv_history=True, include_media=False)
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)

        assert "conv_history/session_001.json" in result
        assert "conv_history/session_002.json" in result
        assert result["conv_history/session_001.json"] == b'{"id": "001"}'

    @pytest.mark.asyncio
    async def test_exports_media_when_enabled(self, data_dir: Path):
        scope = ExportScope(include_project_files=False, include_conv_history=False, include_media=True)
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)

        assert "media/photo.jpg" in result
        assert result["media/photo.jpg"] == b"\xff\xd8\xff"

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_disabled(self, data_dir: Path):
        scope = ExportScope(include_project_files=False, include_conv_history=False, include_media=False)
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)
        assert result == {}

    @pytest.mark.asyncio
    async def test_exports_all_when_all_enabled(self, data_dir: Path):
        scope = ExportScope(include_project_files=True, include_conv_history=True, include_media=True)
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)

        assert "projects/proj_a/CLAUDE.md" in result
        assert "conv_history/session_001.json" in result
        assert "media/photo.jpg" in result

    @pytest.mark.asyncio
    async def test_file_count_matches_files_on_disk(self, data_dir: Path):
        scope = ExportScope(include_project_files=True, include_conv_history=True, include_media=True)
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)

        # 2 proje dosyası + 2 conv_history + 1 medya
        assert len(result) == 5


# ---------------------------------------------------------------------------
# Scope flag testleri
# ---------------------------------------------------------------------------


class TestScopeFiltering:
    @pytest.mark.asyncio
    async def test_project_files_excluded_when_false(self, data_dir: Path):
        scope = ExportScope(include_project_files=False, include_conv_history=True)
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)

        assert not any(k.startswith("projects/") for k in result)

    @pytest.mark.asyncio
    async def test_conv_history_excluded_when_false(self, data_dir: Path):
        scope = ExportScope(include_project_files=True, include_conv_history=False)
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)

        assert not any(k.startswith("conv_history/") for k in result)

    @pytest.mark.asyncio
    async def test_media_excluded_when_false(self, data_dir: Path):
        scope = ExportScope(include_media=False)
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)

        assert not any(k.startswith("media/") for k in result)

    @pytest.mark.asyncio
    async def test_essential_scope_excludes_media(self, data_dir: Path):
        scope = ExportScope.essential()
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)

        assert not any(k.startswith("media/") for k in result)

    @pytest.mark.asyncio
    async def test_full_scope_includes_media(self, data_dir: Path):
        scope = ExportScope.full()
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)

        assert "media/photo.jpg" in result


# ---------------------------------------------------------------------------
# Varolmayan dizin testleri
# ---------------------------------------------------------------------------


class TestMissingDirectories:
    @pytest.mark.asyncio
    async def test_missing_projects_dir_returns_empty(self, tmp_path: Path):
        """projects/ dizini olmasa bile hata atmaz."""
        scope = ExportScope(include_project_files=True, include_conv_history=False, include_media=False)
        exporter = LocalFileExporter(tmp_path)
        result = await exporter.export(scope)
        assert result == {}

    @pytest.mark.asyncio
    async def test_missing_conv_history_dir_returns_empty(self, tmp_path: Path):
        scope = ExportScope(include_project_files=False, include_conv_history=True, include_media=False)
        exporter = LocalFileExporter(tmp_path)
        result = await exporter.export(scope)
        assert result == {}

    @pytest.mark.asyncio
    async def test_missing_media_dir_returns_empty(self, tmp_path: Path):
        scope = ExportScope(include_project_files=False, include_conv_history=False, include_media=True)
        exporter = LocalFileExporter(tmp_path)
        result = await exporter.export(scope)
        assert result == {}


# ---------------------------------------------------------------------------
# İç içe dizin testleri
# ---------------------------------------------------------------------------


class TestNestedDirectories:
    @pytest.mark.asyncio
    async def test_nested_files_included(self, tmp_path: Path):
        """Derin dizin yapıları doğru taranır."""
        (tmp_path / "projects" / "a" / "b" / "c").mkdir(parents=True)
        (tmp_path / "projects" / "a" / "b" / "c" / "deep.md").write_bytes(b"deep")

        scope = ExportScope(include_project_files=True, include_conv_history=False, include_media=False)
        exporter = LocalFileExporter(tmp_path)
        result = await exporter.export(scope)

        assert "projects/a/b/c/deep.md" in result
        assert result["projects/a/b/c/deep.md"] == b"deep"


# ---------------------------------------------------------------------------
# Path traversal güvenlik testleri
# ---------------------------------------------------------------------------


class TestPathTraversalProtection:
    @pytest.mark.asyncio
    async def test_symlink_to_outside_is_skipped(self, tmp_path: Path, tmp_path_factory):
        """data_dir dışına işaret eden sembolik link atlanır."""
        sensitive_dir = tmp_path_factory.mktemp("outside")
        sensitive_file = sensitive_dir / "secret.txt"
        sensitive_file.write_bytes(b"SECRET")

        (tmp_path / "projects").mkdir()
        link_path = tmp_path / "projects" / "escape_link"
        link_path.symlink_to(sensitive_file)

        scope = ExportScope(include_project_files=True, include_conv_history=False, include_media=False)
        exporter = LocalFileExporter(tmp_path)
        result = await exporter.export(scope)

        # Sembolik link atlandı — secret içerik dict'e girmemeli
        for v in result.values():
            assert v != b"SECRET"

    @pytest.mark.asyncio
    async def test_normal_files_not_affected_by_path_traversal_check(self, data_dir: Path):
        """Normal dosyalar path traversal kontrolünden etkilenmez."""
        scope = ExportScope(include_project_files=True, include_conv_history=False, include_media=False)
        exporter = LocalFileExporter(data_dir)
        result = await exporter.export(scope)

        assert "projects/proj_a/CLAUDE.md" in result

    def test_is_relative_to_within_base(self, tmp_path: Path):
        """Path.is_relative_to(): data_dir içindeki path geçer."""
        base = tmp_path.resolve()
        safe_path = (tmp_path / "subdir" / "file.txt").resolve()
        # Gerçek dosya gerekmez — sadece Path nesnesi üzerinde is_relative_to testi
        assert safe_path.is_relative_to(base)

    def test_is_relative_to_outside_base(self, tmp_path: Path, tmp_path_factory):
        """Path.is_relative_to(): data_dir dışındaki path engellenir."""
        base = tmp_path.resolve()
        outside_dir = tmp_path_factory.mktemp("outside_base")
        outside_path = (outside_dir / "secret.txt").resolve()
        assert not outside_path.is_relative_to(base)

    @pytest.mark.asyncio
    async def test_mock_path_outside_data_dir_is_skipped(self, tmp_path: Path):
        """_read_directory: resolve() sonucu data_dir dışına çıkan dosya atlanır (mock ile).

        SEC-SCAN2-F1: Path.is_relative_to() koruması doğrudan test edilir.
        Gerçek '../' traversal'ı filesystem'de oluşturmak mümkün olmadığından
        _read_directory'nin iç kontrol mantığı mock ile izole test edilir.
        """
        from unittest.mock import MagicMock, patch
        import os

        # data_dir içinde projects/ dizini oluştur
        (tmp_path / "projects" / "proj_x").mkdir(parents=True)
        legit_file = tmp_path / "projects" / "proj_x" / "notes.md"
        legit_file.write_bytes(b"notes")

        # data_dir dışında "kaçan" bir dosya yolu simüle et
        outside_dir = tmp_path.parent / "outside_secret"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "stolen.txt"
        outside_file.write_bytes(b"STOLEN")

        exporter = LocalFileExporter(tmp_path)

        # rglob patch: gerçek dosya + outside dosyasını döndür
        real_files = list((tmp_path / "projects").rglob("*"))
        real_files.append(outside_file)  # dışarıdaki dosyayı sahte olarak ekle

        with patch.object(Path, "rglob", return_value=iter(real_files)):
            scope = ExportScope(include_project_files=True, include_conv_history=False, include_media=False)
            result = await exporter.export(scope)

        # Dışarıdaki dosya dict'e girmemiş olmalı
        assert b"STOLEN" not in result.values(), "data_dir dışı dosya export'a dahil edilmemeli"
        # Meşru dosya ise dahil edilmiş olmalı
        assert b"notes" in result.values(), "data_dir içi dosya export'a dahil edilmeli"

    @pytest.mark.asyncio
    async def test_symlink_chain_outside_is_skipped(self, tmp_path: Path, tmp_path_factory):
        """Zincirleme sembolik link (symlink → symlink → dış dosya) atlanır."""
        sensitive_dir = tmp_path_factory.mktemp("chain_outside")
        real_file = sensitive_dir / "deep_secret.txt"
        real_file.write_bytes(b"CHAIN_SECRET")

        (tmp_path / "projects").mkdir()
        # İlk link → dış dosya
        first_link = sensitive_dir / "link1"
        first_link.symlink_to(real_file)
        # İkinci link (projects/ içinde) → ilk link
        second_link = tmp_path / "projects" / "chain_link"
        second_link.symlink_to(first_link)

        scope = ExportScope(include_project_files=True, include_conv_history=False, include_media=False)
        exporter = LocalFileExporter(tmp_path)
        result = await exporter.export(scope)

        for v in result.values():
            assert v != b"CHAIN_SECRET", "Zincirleme symlink atlanmalıydı"


# ---------------------------------------------------------------------------
# Default data_dir testleri
# ---------------------------------------------------------------------------


class TestDefaultDataDir:
    def test_constructor_accepts_none(self):
        """data_dir=None geçildiğinde hata atmamalı."""
        exporter = LocalFileExporter(None)
        assert exporter._data_dir.name == "data"

    def test_constructor_resolves_path(self, tmp_path: Path):
        exporter = LocalFileExporter(tmp_path)
        assert exporter._data_dir == tmp_path.resolve()
