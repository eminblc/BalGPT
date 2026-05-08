"""LocalFileImporter — dosya sistemi içe aktarım implementasyonu.

SRP: Yalnızca {relative_path: bytes} dict'ini dosya sistemine yazma sorumluluğu taşır.
     Orchestration → ImportService; binary okuma → BackupReader.

Davranış:
  - Hedef dosya zaten varsa .bak uzantısıyla yedeklenir.
  - Hedef dizin yoksa oluşturulur.
  - Her dosya için durum "ok" veya "error: <mesaj>" olarak raporlanır.

Güvenlik (GUARDRAILS KAT-57 — Path Traversal koruması):
  Her relative_path data_dir içinde kaldığı doğrulanır; dışına çıkış girişimleri
  "error: path traversal" durumuyla reddedilir.

Tasarım notları:
  - Tüm I/O asyncio.to_thread üzerinden çalışır — event loop bloke edilmez.
  - Sembolik link olarak kaydedilmiş hedefler overwrite edilmez.
  - Rapor referansı: §6 (çakışma çözümü — dosya sistemi satırı), §11.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _resolve_data_dir() -> Path:
    """99-root/data/ dizinini döndürür.

    _file_importer.py konumu:
      scripts/backend/features/backup/_file_importer.py
    Hesaplama:
      parent      → scripts/backend/features/backup/
      parent×2    → scripts/backend/features/
      parent×3    → scripts/backend/
      parent×4    → scripts/
      parent×5    → 99-root/
      / "data"    → 99-root/data/
    """
    return Path(__file__).parent.parent.parent.parent.parent / "data"


class LocalFileImporter:
    """Yedekteki dosyaları data/ dizinine geri yazar.

    FileImporter protokolünü uygular — DIP uyumlu.
    Bağımlılık: yalnızca data_dir (constructor enjeksiyonu).
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        """
        Args:
            data_dir: 99-root/data/ dizini. None ise otomatik çözümlenir.
        """
        self._data_dir: Path = (data_dir or _resolve_data_dir()).resolve()

    # ------------------------------------------------------------------
    # FileImporter Protokolü
    # ------------------------------------------------------------------

    async def import_files(self, files: dict[str, bytes]) -> dict[str, str]:
        """Dosyaları data_dir altına yazar.

        Args:
            files: {relative_path: bytes} — yollar data_dir'e göre görecelidir.

        Returns:
            {relative_path: "ok" | "error: <açıklama>"} durum dict'i.
        """
        return await asyncio.to_thread(self._sync_import, files)

    # ------------------------------------------------------------------
    # Özel yardımcılar
    # ------------------------------------------------------------------

    def _sync_import(self, files: dict[str, bytes]) -> dict[str, str]:
        result: dict[str, str] = {}

        for rel_path, content in files.items():
            result[rel_path] = self._write_one(rel_path, content)

        ok_count = sum(1 for s in result.values() if s == "ok")
        err_count = len(result) - ok_count
        logger.info(
            "LocalFileImporter tamamlandı: %d yazıldı, %d hata",
            ok_count,
            err_count,
        )
        return result

    def _write_one(self, rel_path: str, content: bytes) -> str:
        """Tek bir dosyayı yazar.

        Returns:
            "ok" veya "error: <açıklama>".
        """
        try:
            target = self._resolve_target(rel_path)
        except ValueError as exc:
            logger.warning("Geçersiz yol reddedildi: %s — %s", rel_path, exc)
            return f"error: {exc}"

        try:
            # Mevcut dosyayı .bak olarak yedekle (sembolik link değilse)
            if target.exists() and not target.is_symlink():
                bak_path = target.with_suffix(target.suffix + ".bak")
                target.rename(bak_path)
                logger.debug("Yedeklendi: %s → %s", target, bak_path)
            elif target.is_symlink():
                # Sembolik link güvenlik koruması — üzerine yazma
                logger.warning(
                    "Sembolik link hedefi atlandı, üzerine yazılmıyor: %s", target
                )
                return "error: hedef sembolik link — atlandı"

            # Hedef dizini oluştur
            target.parent.mkdir(parents=True, exist_ok=True)

            # Dosyayı yaz
            target.write_bytes(content)
            return "ok"

        except OSError as exc:
            logger.error("Dosya yazılamadı: %s — %s", target, exc)
            return f"error: {exc}"

    def _resolve_target(self, rel_path: str) -> Path:
        """Hedef dosya yolunu güvenli biçimde çözümler.

        Raises:
            ValueError: rel_path, data_dir dışına çıkıyorsa (path traversal).
        """
        # os.path.join yerine Path / operatörü — absolute segment bypass önlenir
        target = (self._data_dir / rel_path).resolve()
        data_dir_str = str(self._data_dir)

        if not str(target).startswith(data_dir_str + "/") and str(target) != data_dir_str:
            raise ValueError(
                f"path traversal girişimi: {rel_path!r} → {target}"
            )

        return target
