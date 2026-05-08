"""BackupRotationManager — tarih bazlı yedek arşivleme ve rotasyon.

SRP: Yalnızca data/backups/ dizininde dosya arşivleme ve eski dosya temizleme.
     Yedek oluşturma → ExportService; zamanlama → AutoBackupJob/scheduler.

Rapor referansı: §10 Faz 4, BACKUP-11.
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKUP_GLOB = "*.99rb"


class BackupRotationManager:
    """data/backups/ dizininde tarih bazlı arşivleme ve rotasyon yönetimi.

    Sorumluluklar:
        - Yedek dosyasını arşiv dizinine timestamp'li kopyala (save_to_archive)
        - retention_days'den eski .99rb dosyalarını sil (cleanup_old)

    Her iki metot bağımsız çağrılabilir; AutoBackupJob her ikisini sırayla çağırır.
    """

    def save_to_archive(self, src_path: Path, backups_dir: Path) -> Path:
        """Kaynaktan arşiv dizinine timestamp'li kopya oluşturur.

        Args:
            src_path:    Kopyalanacak kaynak .99rb dosyası.
            backups_dir: Hedef arşiv dizini (yoksa oluşturulur).

        Returns:
            Oluşturulan arşiv dosyasının tam yolu.

        Raises:
            OSError: Kopyalama veya dizin oluşturma hatası.
        """
        backups_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        dest = backups_dir / f"backup_{timestamp}.99rb"
        shutil.copy2(src_path, dest)
        logger.info("Yedek arşivlendi: %s", dest)
        return dest

    def cleanup_old(self, backups_dir: Path, retention_days: int) -> int:
        """retention_days'den eski .99rb dosyalarını siler.

        Args:
            backups_dir:    Arşiv dizini.
            retention_days: Bu kadar günden eski dosyalar silinir (≥ 1).
                            0 veya negatif değerlerde rotasyon atlanır.

        Returns:
            Silinen dosya sayısı.
        """
        if retention_days < 1:
            logger.warning("Geçersiz retention_days=%d — rotasyon atlandı", retention_days)
            return 0

        if not backups_dir.exists():
            return 0

        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        deleted = 0

        for path in backups_dir.glob(_BACKUP_GLOB):
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    path.unlink()
                    deleted += 1
                    logger.info(
                        "Eski yedek silindi: %s (mtime=%s)",
                        path,
                        mtime.isoformat(),
                    )
            except OSError as exc:
                logger.warning("Eski yedek silinemedi: %s — %s", path, exc)

        if deleted:
            logger.info("Rotasyon tamamlandı: %d dosya silindi", deleted)

        return deleted
