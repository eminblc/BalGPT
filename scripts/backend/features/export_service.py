"""ExportService — yedek alma orchestration katmanı.

SRP: Yalnızca export akışını koordine eder (scope → manifest → dosya).
     DB okuma → DataExporter; dosya okuma → FileExporter; binary yaz → BackupWriter.

DIP: Tüm bağımlılıklar protokol veya soyutlama üzerinden alınır;
     somut sınıflar yalnızca get_export_service() factory'sinde oluşturulur.

Rapor referansı: §4.9, §7.
"""
from __future__ import annotations

import logging
import socket
from datetime import datetime, timezone
from pathlib import Path

from .backup._cipher import BackupCipher
from .backup._db_exporter import DbExporter
from .backup._env_exporter import EnvExporter
from .backup._file_exporter import LocalFileExporter
from .backup._manifest import BackupManifest
from .backup._protocol import BackupSerializer, DataExporter, FileExporter
from .backup._scope import ExportScope
from .backup._serializer import MsgpackSerializer
from .backup._writer import BackupWriter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Null nesne — FileExporter BACKUP-5'te uygulanacak (OCP: ekleme, değiştirme yok)
# ---------------------------------------------------------------------------


class _NullFileExporter:
    """FileExporter protokolünün geçici null implementasyonu.

    BACKUP-5 tamamlanana kadar dosya sistemi export'u boş dict döndürür.
    ExportService bu nesneyle tam olarak çalışır — yalnızca dosya verisi eksiktir.
    """

    async def export(self, scope: ExportScope) -> dict:  # noqa: ARG002
        return {}


# ---------------------------------------------------------------------------
# ExportService
# ---------------------------------------------------------------------------


class ExportService:
    """Orchestration: ExportScope → .99rb yedek dosyası.

    Bağımlılıklar constructor'dan enjekte edilir (DIP).
    Tek başına test edilebilir — mock exporter/writer ile.
    """

    def __init__(
        self,
        db_exporter: DataExporter,
        file_exporter: FileExporter,
        writer: BackupWriter,
        serializer: BackupSerializer,
        env_exporter: EnvExporter | None = None,
    ) -> None:
        self._db_exporter = db_exporter
        self._file_exporter = file_exporter
        self._writer = writer
        self._serializer = serializer
        self._env_exporter = env_exporter

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_backup(
        self,
        scope: ExportScope,
        output_path: Path,
    ) -> BackupManifest:
        """Yedek dosyası oluşturur ve diske yazar.

        Args:
            scope:       Neyin dahil edileceğini tanımlar.
            output_path: Hedef .99rb dosya yolu.

        Returns:
            Doldurulan BackupManifest (checksum dahil).

        Raises:
            OSError: Disk yazma hatası.
            Exception: DB veya dosya sistemi okuma hatası.
        """
        logger.info("Export başladı: output=%s scope=%s", output_path, scope)

        db_data = await self._db_exporter.export(scope)
        file_data = await self._file_exporter.export(scope)

        if self._env_exporter is not None:
            env_data = await self._env_exporter.export(scope)
            if env_data:
                file_data = {**file_data, **env_data}

        manifest = self._build_manifest(scope, db_data, file_data)

        self._writer.write(output_path, manifest, db_data, file_data)

        logger.info(
            "Export tamamlandı: path=%s tables=%d files=%d",
            output_path,
            len(db_data),
            len(file_data),
        )
        return manifest

    # ------------------------------------------------------------------
    # Özel yardımcılar
    # ------------------------------------------------------------------

    def _build_manifest(
        self,
        scope: ExportScope,
        db_data: dict,
        file_data: dict,
    ) -> BackupManifest:
        """Manifest nesnesini oluşturur — checksum BackupWriter tarafından doldurulur."""
        table_row_counts = {table: len(rows) for table, rows in db_data.items()}

        return BackupManifest(
            version=1,
            created_at=datetime.now(tz=timezone.utc).isoformat(),
            hostname=_get_hostname(),
            app_version="99-root",
            scope_flags=scope.to_flags_dict(),
            table_row_counts=table_row_counts,
            file_count=len(file_data),
            checksum="",  # BackupWriter tarafından doldurulur
        )


# ---------------------------------------------------------------------------
# DI Factory
# ---------------------------------------------------------------------------


def get_export_service() -> ExportService:
    """ExportService'i somut bağımlılıklarla oluşturur.

    DIP: Çağıranlar bu factory'yi kullanır — sınıfları doğrudan örneklendirmez.
    """
    from ..config import settings

    serializer: BackupSerializer = MsgpackSerializer()
    db_exporter: DataExporter = DbExporter()
    file_exporter: FileExporter = LocalFileExporter(  # type: ignore[assignment]
        data_dir=settings.resolved_data_dir,
    )

    # Şifreleme: BACKUP_ENCRYPTION_KEY boşsa cipher=None (v1 format)
    enc_key = settings.backup_encryption_key.get_secret_value()
    cipher: BackupCipher | None = BackupCipher(enc_key) if enc_key else None

    writer = BackupWriter(serializer, cipher=cipher)

    return ExportService(
        db_exporter=db_exporter,
        file_exporter=file_exporter,
        writer=writer,
        serializer=serializer,
        env_exporter=EnvExporter(),
    )


# ---------------------------------------------------------------------------
# Yardımcı fonksiyon
# ---------------------------------------------------------------------------


def _get_hostname() -> str:
    """Makine adını döndürür — hata durumunda 'unknown' fallback."""
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"
