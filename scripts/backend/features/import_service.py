"""ImportService — yedek geri yükleme orchestration katmanı.

SRP: Yalnızca import akışını koordine eder (dosya oku → DB yaz → dosya yaz).
     Binary okuma → BackupReader; DB yazma → DataImporter; dosya yazma → FileImporter.

DIP: Tüm bağımlılıklar protokol veya soyutlama üzerinden alınır;
     somut sınıflar yalnızca get_import_service() factory'sinde oluşturulur.

Rapor referansı: §4.9, §7.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .backup._cipher import BackupCipher
from .backup._db_importer import DbImporter
from .backup._file_importer import LocalFileImporter
from .backup._protocol import DataImporter, FileImporter, ImportMode, ImportResult
from .backup._reader import BackupReader
from .backup._serializer import MsgpackSerializer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Null nesne — FileImporter BACKUP-6'da uygulanacak (OCP: ekleme, değiştirme yok)
# ---------------------------------------------------------------------------


class _NullFileImporter:
    """FileImporter protokolünün geçici null implementasyonu.

    BACKUP-6 tamamlanana kadar dosya sistemi import'u boş dict döndürür.
    ImportService bu nesneyle tam olarak çalışır — yalnızca dosya yazma eksiktir.
    """

    async def import_files(self, files: dict) -> dict:  # noqa: ARG002
        return {}


# ---------------------------------------------------------------------------
# ImportService
# ---------------------------------------------------------------------------


class ImportService:
    """Orchestration: .99rb yedek dosyası → DB + dosya sistemi.

    Bağımlılıklar constructor'dan enjekte edilir (DIP).
    Tek başına test edilebilir — mock importer/reader ile.
    """

    def __init__(
        self,
        db_importer: DataImporter,
        file_importer: FileImporter,
        reader: BackupReader,
    ) -> None:
        self._db_importer = db_importer
        self._file_importer = file_importer
        self._reader = reader

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def restore_backup(
        self,
        backup_path: Path,
        mode: ImportMode = ImportMode.MERGE,
    ) -> ImportResult:
        """Yedek dosyasını okur ve DB + dosya sistemine yazar.

        Args:
            backup_path: .99rb yedek dosyasının yolu.
            mode:        Çakışma çözüm stratejisi (varsayılan: MERGE).

        Returns:
            ImportResult — eklenen/atlanan satır sayıları ve hatalar.

        Raises:
            ValueError: Geçersiz format veya checksum hatası.
            OSError:    Dosya okuma hatası.
        """
        logger.info(
            "Import başladı: path=%s mode=%s", backup_path, mode.value
        )

        manifest, db_data, file_data = self._reader.read(backup_path)
        logger.info(
            "Manifest okundu: created_at=%s hostname=%s tables=%s",
            manifest.created_at,
            manifest.hostname,
            list(manifest.table_row_counts.keys()),
        )

        db_result = await self._db_importer.import_data(db_data, mode)

        file_result = await self._file_importer.import_files(file_data)
        files_written = sum(
            1 for status in file_result.values() if status == "ok"
        )

        logger.info(
            "Import tamamlandı: tables=%d rows_inserted=%s hata=%d files=%d",
            len(db_result.tables_processed),
            db_result.rows_inserted,
            len(db_result.errors),
            files_written,
        )
        return db_result


# ---------------------------------------------------------------------------
# DI Factory
# ---------------------------------------------------------------------------


def get_import_service() -> ImportService:
    """ImportService'i somut bağımlılıklarla oluşturur.

    DIP: Çağıranlar bu factory'yi kullanır — sınıfları doğrudan örneklendirmez.
    """
    from ..config import settings

    serializer = MsgpackSerializer()
    db_importer: DataImporter = DbImporter()
    file_importer: FileImporter = LocalFileImporter(  # type: ignore[assignment]
        data_dir=settings.resolved_data_dir,
    )

    # Şifreleme: BACKUP_ENCRYPTION_KEY boşsa cipher=None (v1 dosyalar okunur)
    enc_key = settings.backup_encryption_key.get_secret_value()
    cipher: BackupCipher | None = BackupCipher(enc_key) if enc_key else None

    reader = BackupReader(serializer, cipher=cipher)

    return ImportService(
        db_importer=db_importer,
        file_importer=file_importer,
        reader=reader,
    )
