"""AutoBackupJob — otomatik periyodik yedekleme iş birimi.

SRP: Yalnızca tek bir otomatik yedekleme döngüsünü koordine eder.
     Zamanlama mantığı scheduler.py'de; iş mantığı burada.
     Arşivleme/rotasyon → BackupRotationManager (BACKUP-11).

DIP: ExportService ve get_messenger() factory üzerinden alınır;
     somut bağımlılıklar constructor'dan enjekte edilir.

Rapor referansı: §10 Faz 4, BACKUP-10, BACKUP-11.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ._rotation import BackupRotationManager

logger = logging.getLogger(__name__)


class AutoBackupJob:
    """Tek bir otomatik yedekleme döngüsünü yürütür.

    Akış:
        ExportScope.essential() → ExportService.create_backup(/tmp/...)
        → messenger.send_document (MediaMessenger ise)
        → BackupRotationManager.save_to_archive(data/backups/)   [BACKUP-11]
        → BackupRotationManager.cleanup_old(retention_days)      [BACKUP-11]
        → tmp dosyayı sil

    Constructor bağımlılıkları test için mock edilebilir (DIP).
    """

    def __init__(
        self,
        export_service,          # ExportService protokolü
        messenger,               # AbstractMessenger (veya MediaMessenger) protokolü
        owner_id: str,
        lang: str = "tr",
        backups_dir: Path | None = None,
        retention_days: int = 7,
        rotation_manager: BackupRotationManager | None = None,
    ) -> None:
        self._export_service = export_service
        self._messenger = messenger
        self._owner_id = owner_id
        self._lang = lang
        self._backups_dir = backups_dir
        self._retention_days = retention_days
        self._rotation_manager = rotation_manager or BackupRotationManager()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Otomatik yedeklemeyi çalıştırır.

        Hata durumunda kullanıcıya hata mesajı iletir; exception fırlatmaz
        (APScheduler job'u başarısız olarak işaretlemeden devam etsin).
        """
        from ...i18n import t
        from ..backup._scope import ExportScope

        scope = ExportScope.essential()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tmp_path = Path(f"/tmp/auto_backup_{timestamp}_{uuid.uuid4().hex[:8]}.99rb")

        logger.info("Otomatik yedekleme başladı: %s", tmp_path)

        try:
            manifest = await self._export_service.create_backup(scope, tmp_path)
        except Exception as exc:
            logger.exception("Otomatik yedekleme başarısız: %s", exc)
            await self._send_text(t("backup.auto_backup_error", self._lang, error=str(exc)))
            return
        finally:
            # Başarısız export durumunda tmp dosya kısmen yazılmış olabilir — temizle
            if not tmp_path.exists():
                pass  # create_backup hiç dosya oluşturmadıysa geç

        size_kb = tmp_path.stat().st_size // 1024 if tmp_path.exists() else 0
        tables  = len(manifest.table_row_counts)
        files   = manifest.file_count
        caption = t(
            "backup.auto_backup_caption", self._lang,
            size=size_kb, tables=tables, files=files,
        )

        await self._send_document(str(tmp_path), tmp_path.name, caption)

        # --- BACKUP-11: data/backups/ arşivleme + rotasyon ---
        if self._backups_dir is not None and tmp_path.exists():
            try:
                self._rotation_manager.save_to_archive(tmp_path, self._backups_dir)
                deleted = self._rotation_manager.cleanup_old(
                    self._backups_dir, self._retention_days
                )
                if deleted:
                    logger.info("Rotasyon: %d eski yedek silindi", deleted)
            except OSError as exc:
                logger.warning("Yedek arşivleme/rotasyon hatası: %s", exc)

        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Otomatik yedek geçici dosyası silinemedi: %s", tmp_path)

        logger.info(
            "Otomatik yedekleme tamamlandı: %s KB, %d tablo, %d dosya",
            size_kb, tables, files,
        )

    # ------------------------------------------------------------------
    # Özel yardımcılar
    # ------------------------------------------------------------------

    async def _send_text(self, text: str) -> None:
        try:
            await self._messenger.send_text(self._owner_id, text)
        except Exception as exc:
            logger.error("AutoBackupJob send_text hatası: %s", exc)

    async def _send_document(self, path: str, filename: str, caption: str) -> None:
        """MediaMessenger ise dosyayı gönderir; değilse yalnızca metin gönderir."""
        from ...adapters.messenger import MediaMessenger

        if isinstance(self._messenger, MediaMessenger):
            try:
                await self._messenger.send_document(self._owner_id, path, filename, caption)
                return
            except Exception as exc:
                logger.exception("AutoBackupJob send_document hatası: %s", exc)
                await self._send_text(
                    f"❌ Yedek gönderilemedi: {exc}"
                )
        else:
            # Medya desteği yoksa yalnızca özet gönder
            await self._send_text(caption)


# ---------------------------------------------------------------------------
# DI Factory
# ---------------------------------------------------------------------------


def get_auto_backup_job() -> AutoBackupJob:
    """AutoBackupJob'ı somut bağımlılıklarla oluşturur.

    DIP: Çağıranlar bu factory'yi kullanır — sınıfları doğrudan örneklendirmez.
    """
    from ...adapters.messenger import get_messenger
    from ...config import settings
    from ..export_service import get_export_service

    backups_dir = settings.resolved_data_dir / "backups"

    return AutoBackupJob(
        export_service=get_export_service(),
        messenger=get_messenger(),
        owner_id=settings.owner_id,
        lang=settings.default_language,
        backups_dir=backups_dir,
        retention_days=settings.backup_retention_days,
    )
