"""Backup/export/import soyutlama protokolleri — DIP / ISP uyumlu.

Her protokol tek bir sorumluluğa sahiptir (ISP).
Yüksek katmanlar somut sınıflara değil bu protokollere bağımlıdır (DIP).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from ._scope import ExportScope


# ---------------------------------------------------------------------------
# ImportMode — import stratejisi enum'u (BACKUP-4'te kullanılır, burada tanımlanır
# çünkü DataImporter protokolü imza için buna bağımlıdır)
# ---------------------------------------------------------------------------


class ImportMode(Enum):
    """Import stratejisi — DbImporter ve ImportService tarafından kullanılır."""

    MERGE = "merge"          # Mevcut verileri koru, yenileri UPSERT ile ekle
    REPLACE = "replace"      # Tabloyu temizle ve yeniden yükle
    SKIP_EXISTING = "skip"   # ID çakışmalarında satırı atla


# ---------------------------------------------------------------------------
# ImportResult — import sonucu bilgi nesnesi
# ---------------------------------------------------------------------------


@dataclass
class ImportResult:
    """Import işlemi sonucunu taşır — SRP."""

    tables_processed: list[str] = field(default_factory=list)
    rows_inserted: dict[str, int] = field(default_factory=dict)
    rows_skipped: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Protokoller
# ---------------------------------------------------------------------------


@runtime_checkable
class BackupSerializer(Protocol):
    """Veri serileştirme sözleşmesi.

    DIP: Yüksek katmanlar somut serileştirici yerine bu soyutlamaya bağımlıdır.
    Uygulayan sınıflar: MsgpackSerializer (BACKUP-2).
    """

    def serialize(self, data: dict) -> bytes:
        """Python dict → bytes."""
        ...

    def deserialize(self, raw: bytes) -> dict:
        """bytes → Python dict."""
        ...


@runtime_checkable
class DataExporter(Protocol):
    """Veritabanı dışa aktarım sözleşmesi.

    ISP: Yalnızca export sözleşmesini içerir; import operasyonları ayrı protokolde.
    Uygulayan sınıflar: DbExporter (BACKUP-3).
    """

    async def export(self, scope: "ExportScope") -> dict:
        """Verilen kapsama göre veritabanını dict olarak döndürür."""
        ...


@runtime_checkable
class DataImporter(Protocol):
    """Veritabanı içe aktarım sözleşmesi.

    ISP: Yalnızca import sözleşmesini içerir; export operasyonları ayrı protokolde.
    Uygulayan sınıflar: DbImporter (BACKUP-4).
    """

    async def import_data(self, data: dict, mode: ImportMode) -> ImportResult:
        """Verilen dict'i belirtilen mod ile veritabanına yazar."""
        ...


@runtime_checkable
class FileExporter(Protocol):
    """Dosya sistemi dışa aktarım sözleşmesi.

    ISP: Yalnızca dosya export sözleşmesini içerir.
    Uygulayan sınıflar: FileExporter (BACKUP-5).
    """

    async def export(self, scope: "ExportScope") -> dict:
        """Kapsama göre dosya sistemini {relative_path: bytes} dict olarak döndürür."""
        ...


@runtime_checkable
class FileImporter(Protocol):
    """Dosya sistemi içe aktarım sözleşmesi.

    ISP: Yalnızca dosya import sözleşmesini içerir.
    Uygulayan sınıflar: FileImporter (BACKUP-6).
    """

    async def import_files(self, files: dict) -> dict:
        """``{relative_path: bytes}`` dict'ini dosya sistemine yazar.

        Returns:
            ``{relative_path: "ok"|"error: ..."}`` durum dict'i.
        """
        ...
