"""LocalFileExporter — dosya sistemi dışa aktarım implementasyonu.

SRP: Yalnızca dosya okuma ve {relative_path: bytes} dict oluşturma sorumluluğu taşır.
     Orchestration → ExportService; binary format → BackupWriter.

Dışa aktarılan dizinler (kapsama göre):
  - data/projects/      → scope.include_project_files
  - data/conv_history/  → scope.include_conv_history
  - data/media/         → scope.include_media

Güvenlik (GUARDRAILS KAT-57 — Path Traversal koruması):
  Her dosya yolu data_dir içinde kaldığı doğrulanır; dışına çıkış girişimleri
  silentle atlanır.

Tasarım notları:
  - Tüm I/O asyncio.to_thread üzerinden çalışır — event loop bloke edilmez.
  - Sembolik linkler takip edilmez (symlink güvenlik riski).
  - Rapor referansı: §2.1, §4 (dosya sistemi kısmı), §11.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._scope import ExportScope

logger = logging.getLogger(__name__)


def _resolve_data_dir() -> Path:
    """99-root/data/ dizinini döndürür.

    _file_exporter.py konumu:
      scripts/backend/features/backup/_file_exporter.py
    Hesaplama:
      parent      → scripts/backend/features/backup/
      parent×2    → scripts/backend/features/
      parent×3    → scripts/backend/
      parent×4    → scripts/
      parent×5    → 99-root/
      / "data"    → 99-root/data/
    """
    return Path(__file__).parent.parent.parent.parent.parent / "data"


# Kapsam flag'i → alt dizin eşlemesi (OCP: yeni dizin ekleme → tablo satırı ekle)
_SCOPE_TO_SUBDIR: dict[str, str] = {
    "include_project_files": "projects",
    "include_conv_history": "conv_history",
    "include_media": "media",
}


class LocalFileExporter:
    """data/ altındaki dizinleri {relative_path: bytes} dict olarak dışa aktarır.

    FileExporter protokolünü uygular — DIP uyumlu.
    Bağımlılık: yalnızca data_dir (constructor enjeksiyonu).

    OOP notu: Kapsam flag'leri → alt dizin eşlemesi _SCOPE_TO_SUBDIR sabitinde
    tanımlanır; yeni dizin eklemek mevcut metot gövdesini değiştirmez (OCP).
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        """
        Args:
            data_dir: 99-root/data/ dizini. None ise otomatik çözümlenir.
        """
        self._data_dir: Path = (data_dir or _resolve_data_dir()).resolve()

    # ------------------------------------------------------------------
    # FileExporter Protokolü
    # ------------------------------------------------------------------

    async def export(self, scope: "ExportScope") -> dict[str, bytes]:
        """Kapsama göre dosya sistemini okur.

        Returns:
            {relative_path: bytes} — yollar data_dir'e göre görecelidir
            (örn. "conv_history/session_abc.json").
        """
        return await asyncio.to_thread(self._sync_export, scope)

    # ------------------------------------------------------------------
    # Özel yardımcılar
    # ------------------------------------------------------------------

    def _sync_export(self, scope: "ExportScope") -> dict[str, bytes]:
        result: dict[str, bytes] = {}

        for flag_name, subdir in _SCOPE_TO_SUBDIR.items():
            if not getattr(scope, flag_name, False):
                continue

            dir_path = self._data_dir / subdir
            if not dir_path.exists():
                logger.debug("Dizin yok, atlanıyor: %s", dir_path)
                continue

            before = len(result)
            self._read_directory(dir_path, result)
            added = len(result) - before
            logger.debug("Dizin okundu: %s → %d dosya", subdir, added)

        logger.info(
            "LocalFileExporter tamamlandı: toplam %d dosya",
            len(result),
        )
        return result

    def _read_directory(self, directory: Path, result: dict[str, bytes]) -> None:
        """Dizin altındaki tüm dosyaları result'a ekler.

        Güvenlik:
          - Sembolik linkler takip edilmez.
          - Çözümlenen yol data_dir dışında ise dosya atlanır (path traversal koruması).
        """
        for file_path in directory.rglob("*"):
            if not file_path.is_file():
                continue

            # Sembolik link güvenlik kontrolü
            if file_path.is_symlink():
                logger.warning("Sembolik link atlandı: %s", file_path)
                continue

            # Path traversal koruması (GUARDRAILS KAT-57)
            resolved = file_path.resolve()
            data_dir_str = str(self._data_dir)
            if not str(resolved).startswith(data_dir_str + "/") and str(resolved) != data_dir_str:
                logger.warning(
                    "Path traversal girişimi atlandı: %s → %s",
                    file_path,
                    resolved,
                )
                continue

            rel_path = resolved.relative_to(self._data_dir)
            try:
                result[str(rel_path)] = resolved.read_bytes()
            except OSError as exc:
                logger.warning("Dosya okunamadı, atlanıyor: %s — %s", resolved, exc)
