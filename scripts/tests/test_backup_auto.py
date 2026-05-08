"""BACKUP-10 — Otomatik periyodik yedekleme birim testleri.

Test kapsamı:
    - AutoBackupJob.run(): başarılı akış → send_document çağrıldı, tmp silindi
    - AutoBackupJob.run(): ExportService hatası → send_text (hata mesajı) çağrıldı
    - AutoBackupJob.run(): MediaMessenger olmayan messenger → yalnızca send_text
    - AutoBackupJob.run(): send_document hatası → hata mesajı gönderildi
    - _register_auto_backup_job(): enabled=True → APScheduler'a job eklendi
    - _register_auto_backup_job(): enabled=False → job eklenmedi
    - _register_auto_backup_job(): geçersiz cron → job eklenmedi, exception yutuldu
"""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.features.backup._auto_backup import AutoBackupJob
from backend.features.backup._manifest import BackupManifest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_manifest(tables: int = 3, files: int = 5) -> BackupManifest:
    return BackupManifest(
        version=1,
        created_at="2026-05-08T00:00:00+00:00",
        hostname="testhost",
        app_version="99-root",
        scope_flags={},
        table_row_counts={f"t{i}": i * 10 for i in range(tables)},
        file_count=files,
        checksum="abc123",
    )


def _make_media_messenger():
    """MediaMessenger protocol'ünü destekleyen mock."""
    from backend.adapters.messenger import MediaMessenger

    class _FakeMediaMessenger(MediaMessenger):
        send_text = AsyncMock()
        send_document = AsyncMock()

        async def send_buttons(self, *a, **kw): ...
        async def receive_message(self, *a, **kw): ...

    return _FakeMediaMessenger()


def _make_plain_messenger():
    """MediaMessenger olmayan plain messenger mock."""
    m = MagicMock()
    m.send_text = AsyncMock()
    # send_document yok — isinstance(m, MediaMessenger) → False
    return m


# ---------------------------------------------------------------------------
# Başarılı akış — MediaMessenger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_success_sends_document(tmp_path):
    """Başarılı export → send_document çağrıldı, tmp dosya silindi."""
    manifest = _make_manifest(tables=3, files=5)
    export_service = MagicMock()

    tmp_file = tmp_path / f"auto_backup_test_{uuid.uuid4().hex[:8]}.99rb"
    tmp_file.write_bytes(b"x" * 2048)  # 2 KB

    async def _fake_create_backup(scope, output_path):
        # AutoBackupJob'un oluşturduğu yolu simüle et: yazılmış gibi davran
        output_path.write_bytes(tmp_file.read_bytes())
        return manifest

    export_service.create_backup = AsyncMock(side_effect=_fake_create_backup)
    messenger = _make_media_messenger()

    job = AutoBackupJob(
        export_service=export_service,
        messenger=messenger,
        owner_id="905300000000",
        lang="tr",
    )
    await job.run()

    messenger.send_document.assert_called_once()
    call_args = messenger.send_document.call_args
    # İlk argüman owner_id, ikincisi dosya yolu
    assert call_args[0][0] == "905300000000"
    assert call_args[0][1].endswith(".99rb")
    # Dosya gönderildikten sonra silinmeli
    assert not Path(call_args[0][1]).exists()


# ---------------------------------------------------------------------------
# Hata akışı — ExportService başarısız
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_export_error_sends_error_message():
    """ExportService exception → kullanıcıya hata mesajı iletildi."""
    export_service = MagicMock()
    export_service.create_backup = AsyncMock(side_effect=RuntimeError("disk dolu"))

    messenger = _make_media_messenger()

    job = AutoBackupJob(
        export_service=export_service,
        messenger=messenger,
        owner_id="905300000000",
        lang="tr",
    )
    await job.run()

    # send_text hata mesajı içermeli
    messenger.send_text.assert_called_once()
    call_text: str = messenger.send_text.call_args[0][1]
    assert "disk dolu" in call_text
    # send_document kesinlikle çağrılmamalı
    messenger.send_document.assert_not_called()


# ---------------------------------------------------------------------------
# Plain messenger (medya desteği yok)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_plain_messenger_sends_text(tmp_path):
    """MediaMessenger olmayan messenger → send_text ile özet gönderildi."""
    manifest = _make_manifest(tables=2, files=4)
    export_service = MagicMock()

    async def _fake_create_backup(scope, output_path):
        output_path.write_bytes(b"y" * 512)
        return manifest

    export_service.create_backup = AsyncMock(side_effect=_fake_create_backup)
    messenger = _make_plain_messenger()

    job = AutoBackupJob(
        export_service=export_service,
        messenger=messenger,
        owner_id="905300000000",
        lang="en",
    )
    await job.run()

    messenger.send_text.assert_called_once()
    # İngilizce caption içermeli
    call_text: str = messenger.send_text.call_args[0][1]
    assert "backup" in call_text.lower() or "Auto" in call_text


# ---------------------------------------------------------------------------
# send_document hatası
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_send_document_error_sends_fallback(tmp_path):
    """send_document exception → hata mesajı gönderildi, job çökmedi."""
    manifest = _make_manifest()
    export_service = MagicMock()

    async def _fake_create_backup(scope, output_path):
        output_path.write_bytes(b"z" * 100)
        return manifest

    export_service.create_backup = AsyncMock(side_effect=_fake_create_backup)
    messenger = _make_media_messenger()
    messenger.send_document = AsyncMock(side_effect=OSError("network error"))

    job = AutoBackupJob(
        export_service=export_service,
        messenger=messenger,
        owner_id="905300000000",
        lang="tr",
    )
    await job.run()

    # Hata durumunda send_text çağrılmalı
    messenger.send_text.assert_called_once()


# ---------------------------------------------------------------------------
# _register_auto_backup_job: enabled/disabled
# ---------------------------------------------------------------------------


def test_register_auto_backup_job_enabled():
    """AUTO_BACKUP_ENABLED=true → APScheduler'a job eklendi."""
    from backend.features import scheduler as sched

    mock_scheduler = MagicMock()
    mock_settings = MagicMock()
    mock_settings.auto_backup_enabled = True
    mock_settings.auto_backup_cron = "0 3 * * *"

    with (
        patch.object(sched, "_scheduler", mock_scheduler),
        patch("backend.features.scheduler.get_settings", return_value=mock_settings),
    ):
        sched._register_auto_backup_job()

    mock_scheduler.add_job.assert_called_once()
    call_kwargs = mock_scheduler.add_job.call_args[1]
    assert call_kwargs["id"] == sched._AUTO_BACKUP_JOB_ID
    assert call_kwargs["hour"] == "3"
    assert call_kwargs["minute"] == "0"


def test_register_auto_backup_job_disabled():
    """AUTO_BACKUP_ENABLED=false → APScheduler'a hiçbir ekleme yapılmadı."""
    from backend.features import scheduler as sched

    mock_scheduler = MagicMock()
    mock_settings = MagicMock()
    mock_settings.auto_backup_enabled = False

    with (
        patch.object(sched, "_scheduler", mock_scheduler),
        patch("backend.features.scheduler.get_settings", return_value=mock_settings),
    ):
        sched._register_auto_backup_job()

    mock_scheduler.add_job.assert_not_called()


def test_register_auto_backup_job_invalid_cron():
    """Geçersiz cron ifadesi → job eklenmedi, exception yutuldu."""
    from backend.features import scheduler as sched

    mock_scheduler = MagicMock()
    mock_settings = MagicMock()
    mock_settings.auto_backup_enabled = True
    mock_settings.auto_backup_cron = "not a cron"

    with (
        patch.object(sched, "_scheduler", mock_scheduler),
        patch("backend.features.scheduler.get_settings", return_value=mock_settings),
    ):
        sched._register_auto_backup_job()  # exception fırlatmamalı

    mock_scheduler.add_job.assert_not_called()
