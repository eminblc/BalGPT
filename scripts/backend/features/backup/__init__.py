"""backup paketi — 99-root veri dışa/içe aktarım altyapısı.

Faz 1a (BACKUP-1): Protokoller, kapsam ve manifest tanımları.
Faz 1b (BACKUP-2): Binary format — BackupWriter, BackupReader, MsgpackSerializer.
Faz 1c (BACKUP-3): DbExporter + ExportService orchestration.
Faz 2a (BACKUP-4): DbImporter + ImportService orchestration.
Faz 2b (BACKUP-5): LocalFileExporter + LocalFileImporter (projects/, conv_history/, media/).

Dışa aktarılan semboller:
    - BackupSerializer, DataExporter, DataImporter, FileExporter,
      FileImporter                                                 (protokoller)
    - ImportMode, ImportResult                                     (import türleri)
    - ExportScope                                                  (kapsam konfigürasyonu)
    - BackupManifest                                               (yedek meta verisi)
    - MsgpackSerializer                                            (BackupSerializer impl)
    - BackupWriter                                                 (binary .99rb yazar)
    - BackupReader                                                 (binary .99rb okur)
    - DbExporter                                                   (SQLite → dict)
    - DbImporter                                                   (dict → SQLite)
    - LocalFileExporter                                            (dosya sistemi → dict)
    - LocalFileImporter                                            (dict → dosya sistemi)
"""
from ._db_exporter import DbExporter
from ._db_importer import DbImporter
from ._env_exporter import EnvExporter
from ._file_exporter import LocalFileExporter
from ._file_importer import LocalFileImporter
from ._manifest import BackupManifest
from ._protocol import (
    BackupSerializer,
    DataExporter,
    DataImporter,
    FileExporter,
    FileImporter,
    ImportMode,
    ImportResult,
)
from ._reader import BackupReader
from ._scope import ExportScope
from ._serializer import MsgpackSerializer
from ._writer import MAGIC, FORMAT_VERSION, BackupWriter

__all__ = [
    "BackupManifest",
    "BackupReader",
    "BackupSerializer",
    "BackupWriter",
    "DataExporter",
    "DataImporter",
    "DbExporter",
    "DbImporter",
    "EnvExporter",
    "ExportScope",
    "FileExporter",
    "FileImporter",
    "FORMAT_VERSION",
    "MAGIC",
    "ImportMode",
    "ImportResult",
    "LocalFileExporter",
    "LocalFileImporter",
    "MsgpackSerializer",
]
