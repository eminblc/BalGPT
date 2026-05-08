"""BackupWriter — .99rb binary yedek dosyası yazar.

SRP: Yalnızca binary format yazma sorumluluğu taşır.
     Serileştirme → BackupSerializer; DB okuma → DataExporter; kapsam → ExportScope.
     Şifreleme → BackupCipher (opsiyonel — verilmezse v1 format kullanılır).

Binary format v1 (şifresiz):
    [MAGIC 4 B] [VERSION=1, 2 B] [CHECKSUM 64 B] [ZLIB(MSGPACK)]

Binary format v2 (AES-256-GCM şifreli):
    [MAGIC 4 B] [VERSION=2, 2 B] [CHECKSUM 64 B] [NONCE 12 B] [AESGCM(ZLIB(MSGPACK))]

    CHECKSUM = SHA-256(NONCE + CIPHERTEXT) — şifreli bloğun bütünlüğünü doğrular.

Payload yapısı (her iki format için):
    {
        "manifest": {...},              # BackupManifest.to_dict()
        "db":       {...},              # DbExporter çıktısı
        "files":    {"rel/path": b"…"} # FileExporter çıktısı (base64 yok — bytes)
    }
"""
from __future__ import annotations

import hashlib
import logging
import struct
import zlib
from dataclasses import asdict
from pathlib import Path

from ._cipher import BackupCipher
from ._manifest import BackupManifest
from ._protocol import BackupSerializer

logger = logging.getLogger(__name__)

MAGIC: bytes = b"\x99\x52\x42\x4B"   # ASCII'de "99RBK" karşılığı değil — literal magic
FORMAT_VERSION_V1: int = 1
FORMAT_VERSION_V2: int = 2
FORMAT_VERSION: int = FORMAT_VERSION_V1   # Varsayılan (geriye dönük uyumluluk)

_ZLIB_LEVEL: int = 6                   # hız/boyut dengesi
_NONCE_SIZE: int = 12                  # AES-GCM nonce boyutu


class BackupWriter:
    """Binary .99rb dosyası yazar.

    Bağımlılık enjeksiyonu: serializer ve isteğe bağlı cipher dışarıdan verilir (DIP).

    Şifreleme kullanımı:
        - cipher=None  → v1 format (şifresiz, mevcut davranış)
        - cipher=BackupCipher(key) → v2 format (AES-256-GCM şifreli)
    """

    def __init__(
        self,
        serializer: BackupSerializer,
        cipher: BackupCipher | None = None,
    ) -> None:
        self._serializer = serializer
        self._cipher = cipher

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(
        self,
        path: Path,
        manifest: BackupManifest,
        db_data: dict,
        file_data: dict,
    ) -> None:
        """Yedek dosyasını diske yazar.

        Şifreleme anahtarı constructor'da verilmişse v2 (şifreli) format,
        verilmemişse v1 (şifresiz) format kullanılır.

        Args:
            path:      Hedef dosya yolu (.99rb uzantısı önerilir).
            manifest:  BackupManifest örneği — checksum BURADA doldurulur.
            db_data:   DataExporter.export() çıktısı.
            file_data: FileExporter.export() çıktısı — {rel_path: bytes}.

        Raises:
            OSError:   Disk yazma hatası.
        """
        payload = {
            "manifest": asdict(manifest),
            "db": db_data,
            "files": file_data,
        }

        raw: bytes = self._serializer.serialize(payload)
        compressed: bytes = zlib.compress(raw, _ZLIB_LEVEL)

        if self._cipher is not None:
            self._write_v2(path, manifest, payload, compressed)
        else:
            self._write_v1(path, manifest, payload, compressed)

    # ------------------------------------------------------------------
    # Özel yazma yardımcıları
    # ------------------------------------------------------------------

    def _write_v1(
        self,
        path: Path,
        manifest: BackupManifest,
        payload: dict,
        compressed: bytes,
    ) -> None:
        """v1 format: şifresiz, zlib sıkıştırılmış."""
        checksum: str = hashlib.sha256(compressed).hexdigest()

        # manifest.checksum'ı güncelle ve veriyi yeniden seri hale getir
        payload["manifest"]["checksum"] = checksum
        raw = self._serializer.serialize(payload)
        compressed = zlib.compress(raw, _ZLIB_LEVEL)
        checksum = hashlib.sha256(compressed).hexdigest()

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            fh.write(MAGIC)
            fh.write(struct.pack(">H", FORMAT_VERSION_V1))
            fh.write(checksum.encode("ascii"))   # 64 bytes (hex digest)
            fh.write(compressed)

        self._log_written(path, checksum)

    def _write_v2(
        self,
        path: Path,
        manifest: BackupManifest,
        payload: dict,
        compressed: bytes,
    ) -> None:
        """v2 format: AES-256-GCM şifreli.

        CHECKSUM = SHA-256(NONCE + CIPHERTEXT) — bütünlük doğrulama.
        """
        assert self._cipher is not None  # mypy guard

        nonce, ciphertext = self._cipher.encrypt(compressed)
        checksum: str = hashlib.sha256(nonce + ciphertext).hexdigest()

        # manifest'e şifreleme bilgisini kaydet
        payload["manifest"]["checksum"] = checksum
        payload["manifest"]["encrypted"] = True

        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as fh:
            fh.write(MAGIC)
            fh.write(struct.pack(">H", FORMAT_VERSION_V2))
            fh.write(checksum.encode("ascii"))   # 64 bytes (hex digest)
            fh.write(nonce)                       # 12 bytes
            fh.write(ciphertext)                  # değişken uzunluk

        self._log_written(path, checksum)

    def _log_written(self, path: Path, checksum: str) -> None:
        size_kb = path.stat().st_size // 1024
        logger.info(
            "Yedek dosyası yazıldı: path=%s size_kb=%d checksum=%s… encrypted=%s",
            path,
            size_kb,
            checksum[:8],
            self._cipher is not None,
        )
