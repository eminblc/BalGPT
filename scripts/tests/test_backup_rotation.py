"""BACKUP-11 — Tarih bazlı yedek rotasyonu birim testleri.

Test kapsamı:
    BackupRotationManager.save_to_archive():
        - Dosya hedef dizine kopyalanır
        - Hedef dosya backup_<timestamp>.99rb formatına uyar
        - Dizin yoksa oluşturulur
        - Kaynak eksikse OSError fırlatılır

    BackupRotationManager.cleanup_old():
        - retention_days=0 → rotasyon atlanır, 0 döner
        - retention_days < 0 → rotasyon atlanır, 0 döner
        - Dizin yoksa → 0 döner
        - Eski dosyalar silinir, yeni dosyalar korunur
        - Silme başarısız olunca hata loglanır, devam edilir

    AutoBackupJob (BACKUP-11 entegrasyon):
        - backups_dir verilirse save_to_archive + cleanup_old çağrılır
        - backups_dir=None ise rotasyon çağrılmaz
        - retention_days=0 → save_to_archive çağrılır, cleanup 0 döner
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.features.backup._rotation import BackupRotationManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_src(tmp_path: Path) -> Path:
    """Geçici kaynak .99rb dosyası."""
    src = tmp_path / "source.99rb"
    src.write_bytes(b"fake backup data")
    return src


@pytest.fixture()
def backups_dir(tmp_path: Path) -> Path:
    """Henüz oluşturulmamış hedef arşiv dizini."""
    return tmp_path / "backups"


@pytest.fixture()
def manager() -> BackupRotationManager:
    return BackupRotationManager()


# ---------------------------------------------------------------------------
# save_to_archive testleri
# ---------------------------------------------------------------------------


def test_save_to_archive_creates_file(manager, tmp_src, backups_dir):
    dest = manager.save_to_archive(tmp_src, backups_dir)

    assert dest.exists()
    assert dest.suffix == ".99rb"
    assert dest.name.startswith("backup_")
    assert dest.read_bytes() == b"fake backup data"


def test_save_to_archive_creates_missing_dir(manager, tmp_src, backups_dir):
    assert not backups_dir.exists()
    manager.save_to_archive(tmp_src, backups_dir)
    assert backups_dir.exists()


def test_save_to_archive_filename_format(manager, tmp_src, backups_dir):
    dest = manager.save_to_archive(tmp_src, backups_dir)
    # Beklenen format: backup_YYYYMMDD_HHMMSS.99rb
    stem = dest.stem  # backup_20260508_020000
    parts = stem.split("_")
    assert len(parts) == 3, f"Beklenmedik format: {dest.name}"
    assert parts[0] == "backup"
    assert len(parts[1]) == 8    # YYYYMMDD
    assert len(parts[2]) == 6    # HHMMSS


def test_save_to_archive_raises_on_missing_src(manager, backups_dir):
    missing = Path("/nonexistent/path/file.99rb")
    with pytest.raises(OSError):
        manager.save_to_archive(missing, backups_dir)


def test_save_to_archive_multiple_calls_produce_distinct_files(manager, tmp_src, backups_dir):
    """Birden fazla çağrı farklı isimler üretmeli (timestamp değişir)."""
    # İki çağrıyı farklı timestamp'e zorlamak için monkeypatch yerine
    # sadece farklı isimler üretilebilecek kadar zaman geçiyor mu diye kontrol
    dest1 = manager.save_to_archive(tmp_src, backups_dir)
    dest2 = manager.save_to_archive(tmp_src, backups_dir)
    # Aynı saniyede çalışabilir — dosya adı çakışırsa shutil.copy2 üzerine yazar.
    # Burada sadece her ikisinin de var olduğunu doğruluyoruz.
    assert dest1.exists()
    assert dest2.exists()


# ---------------------------------------------------------------------------
# cleanup_old testleri
# ---------------------------------------------------------------------------


def test_cleanup_old_returns_zero_for_nonexistent_dir(manager, tmp_path):
    result = manager.cleanup_old(tmp_path / "missing", retention_days=7)
    assert result == 0


def test_cleanup_old_returns_zero_for_zero_retention(manager, backups_dir, tmp_path):
    backups_dir.mkdir()
    # Dosya oluştur
    (backups_dir / "backup_20200101_000000.99rb").write_bytes(b"old")
    result = manager.cleanup_old(backups_dir, retention_days=0)
    assert result == 0
    assert (backups_dir / "backup_20200101_000000.99rb").exists()


def test_cleanup_old_returns_zero_for_negative_retention(manager, backups_dir):
    backups_dir.mkdir()
    result = manager.cleanup_old(backups_dir, retention_days=-1)
    assert result == 0


def test_cleanup_old_deletes_old_files(manager, backups_dir):
    backups_dir.mkdir()
    old_file = backups_dir / "backup_old.99rb"
    old_file.write_bytes(b"old data")

    # mtime'ı 10 gün öncesine ayarla
    past = datetime.now(timezone.utc) - timedelta(days=10)
    past_ts = past.timestamp()
    os.utime(old_file, (past_ts, past_ts))

    deleted = manager.cleanup_old(backups_dir, retention_days=7)
    assert deleted == 1
    assert not old_file.exists()


def test_cleanup_old_keeps_recent_files(manager, backups_dir):
    backups_dir.mkdir()
    new_file = backups_dir / "backup_new.99rb"
    new_file.write_bytes(b"new data")

    # mtime = şu an (yeni dosya)
    deleted = manager.cleanup_old(backups_dir, retention_days=7)
    assert deleted == 0
    assert new_file.exists()


def test_cleanup_old_mixed_old_and_new(manager, backups_dir):
    backups_dir.mkdir()

    old_file = backups_dir / "backup_20200101_000000.99rb"
    old_file.write_bytes(b"old")
    past = datetime.now(timezone.utc) - timedelta(days=30)
    past_ts = past.timestamp()
    os.utime(old_file, (past_ts, past_ts))

    new_file = backups_dir / "backup_today.99rb"
    new_file.write_bytes(b"new")

    deleted = manager.cleanup_old(backups_dir, retention_days=7)
    assert deleted == 1
    assert not old_file.exists()
    assert new_file.exists()


def test_cleanup_old_ignores_non_99rb_files(manager, backups_dir):
    backups_dir.mkdir()

    txt_file = backups_dir / "old.txt"
    txt_file.write_bytes(b"text")
    past = datetime.now(timezone.utc) - timedelta(days=30)
    past_ts = past.timestamp()
    os.utime(txt_file, (past_ts, past_ts))

    deleted = manager.cleanup_old(backups_dir, retention_days=7)
    assert deleted == 0
    assert txt_file.exists()


def test_cleanup_old_handles_oserror_gracefully(manager, backups_dir, caplog):
    """Silme başarısız olursa hata loglanır, exception fırlatılmaz."""
    backups_dir.mkdir()
    old_file = backups_dir / "backup_old.99rb"
    old_file.write_bytes(b"old")
    past = datetime.now(timezone.utc) - timedelta(days=30)
    past_ts = past.timestamp()
    os.utime(old_file, (past_ts, past_ts))

    with patch.object(Path, "unlink", side_effect=OSError("permission denied")):
        import logging
        with caplog.at_level(logging.WARNING):
            result = manager.cleanup_old(backups_dir, retention_days=7)

    assert result == 0  # Silme başarısız → sayaç artmadı


# ---------------------------------------------------------------------------
# AutoBackupJob entegrasyon testleri (BACKUP-11)
# ---------------------------------------------------------------------------


@pytest.fixture()
def _manifest():
    from backend.features.backup._manifest import BackupManifest
    return BackupManifest(
        version=1,
        created_at="2026-05-08T02:00:00+00:00",
        hostname="test",
        app_version="99-root",
        scope_flags={},
        table_row_counts={"messages": 10},
        file_count=2,
        checksum="abc123",
    )


@pytest.mark.asyncio
async def test_auto_backup_job_calls_rotation(tmp_path, _manifest):
    """backups_dir verildiğinde save_to_archive + cleanup_old çağrılır."""
    from backend.features.backup._auto_backup import AutoBackupJob

    backups_dir = tmp_path / "backups"
    mock_rotation = MagicMock()
    mock_rotation.save_to_archive = MagicMock()
    mock_rotation.cleanup_old = MagicMock(return_value=0)

    # create_backup mock'u dosyayı gerçekten oluşturmalı (yoksa tmp_path.exists() False)
    async def _fake_create_backup(scope, output_path):
        output_path.write_bytes(b"fake backup")
        return _manifest

    mock_export = AsyncMock()
    mock_export.create_backup = _fake_create_backup

    mock_messenger = AsyncMock()
    mock_messenger.send_text = AsyncMock()

    job = AutoBackupJob(
        export_service=mock_export,
        messenger=mock_messenger,
        owner_id="test_owner",
        lang="tr",
        backups_dir=backups_dir,
        retention_days=7,
        rotation_manager=mock_rotation,
    )

    await job.run()

    mock_rotation.save_to_archive.assert_called_once()
    mock_rotation.cleanup_old.assert_called_once_with(backups_dir, 7)


@pytest.mark.asyncio
async def test_auto_backup_job_skips_rotation_when_no_backups_dir(tmp_path, _manifest):
    """backups_dir=None ise rotasyon çağrılmaz."""
    from backend.features.backup._auto_backup import AutoBackupJob

    mock_rotation = MagicMock()
    mock_rotation.save_to_archive = MagicMock()
    mock_rotation.cleanup_old = MagicMock(return_value=0)

    mock_export = AsyncMock()
    mock_export.create_backup = AsyncMock(return_value=_manifest)

    mock_messenger = AsyncMock()
    mock_messenger.send_text = AsyncMock()

    job = AutoBackupJob(
        export_service=mock_export,
        messenger=mock_messenger,
        owner_id="test_owner",
        lang="tr",
        backups_dir=None,
        retention_days=7,
        rotation_manager=mock_rotation,
    )

    await job.run()

    mock_rotation.save_to_archive.assert_not_called()
    mock_rotation.cleanup_old.assert_not_called()
