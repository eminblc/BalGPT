"""BacklogParser — BACKLOG.md dosyasından görev item'larını okur ve günceller.

Desteklenen formatlar (otomatik algılanır):
  Checkbox : - [ ] SEC-001 Açıklama  (my-project, eski 99-root)
  Table    : | SCAN-DEPTH-1 | Başlık | Dosya | Not |  (güncel 99-root)

SRP: Yalnızca format algılama + strateji delegasyonu — parse/write mantığı _formats.py'de.
DIP: Somut format sınıflarına doğrudan bağımlılık yok; detect_format() factory kullanılır.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ._formats import (
    BacklogItem,          # re-export — runner.py bu modülden import eder
    CheckboxFormat,
    TableFormat,
    _atomic_write,
    detect_format,
)

__all__ = ["BacklogItem", "BacklogParser"]

logger = logging.getLogger(__name__)


class BacklogParser:
    """BACKLOG.md dosyasından görev item'larını okur ve durum geçişlerini uygular.

    Tek sorumluluk: format algılama + strateji seçimi.
    Parse/write detayları CheckboxFormat ve TableFormat sınıflarında.
    """

    def get_pending_items(
        self, backlog_path: Path, prefix: str = ""
    ) -> list[BacklogItem]:
        """Bekleyen backlog item'larını döndür.

        Args:
            backlog_path: BACKLOG.md dosyasının Path'i.
            prefix:       Opsiyonel prefix filtresi (örn. "SEC"). Boşsa tümü.

        Returns:
            BacklogItem listesi, orijinal dosya sırasıyla.
        """
        return detect_format(backlog_path).get_pending_items(backlog_path, prefix)

    def mark_in_progress(self, backlog_path: Path, item_id: str) -> bool:
        """Item'ı in_progress olarak işaretle.

        Returns:
            Değişiklik yapıldıysa True, item bulunamazsa False.
        """
        result = detect_format(backlog_path).mark_in_progress(backlog_path, item_id)
        if not result:
            logger.warning("BacklogParser.mark_in_progress: %s bulunamadı.", item_id)
        return result

    def mark_done(self, backlog_path: Path, item_id: str) -> bool:
        """Item'ı tamamlandı olarak işaretle.

        Returns:
            Değişiklik yapıldıysa True, item bulunamazsa False.
        """
        result = detect_format(backlog_path).mark_done(backlog_path, item_id)
        if not result:
            logger.warning("BacklogParser.mark_done: %s bulunamadı.", item_id)
        return result

    def mark_failed(self, backlog_path: Path, item_id: str) -> bool:
        """Item'ı başarısız olarak işaretle (yeniden denenebilir hale döner).

        Returns:
            Değişiklik yapıldıysa True, item bulunamazsa False.
        """
        result = detect_format(backlog_path).mark_failed(backlog_path, item_id)
        if not result:
            logger.warning("BacklogParser.mark_failed: %s bulunamadı.", item_id)
        return result

    def reset_stranded_items(self, backlog_path: Path) -> int:
        """Önceki run'dan kalan in_progress (`- [~]` / 🔄) item'ları pending'e döndürür.

        run() başlangıcında çağrılır → çökme veya iptal sonrası takılı item'lar
        yeniden işlenebilir hale gelir.

        Returns:
            Geri çevrilen satır sayısı (0 → orphan yok).
        """
        return detect_format(backlog_path).reset_stranded_items(backlog_path)

    def _atomic_write(self, path: Path, lines: list[str]) -> None:
        """Geriye dönük uyumluluk için korundu — _formats._atomic_write'ı delege eder."""
        _atomic_write(path, lines)
