"""BackupReader — .99rb binary yedek dosyası okur.

SRP: Yalnızca binary format okuma ve bütünlük doğrulama sorumluluğu taşır.
     Serileştirme → BackupSerializer; DB yazma → DataImporter.
     Şifre çözme → BackupCipher (opsiyonel — v2 dosyalar için gerekli).

Okuma adımları (v1):
    1. Magic bytes doğrula (4 B)
    2. Format versiyonu oku (2 B)
    3. Saklı SHA-256 checksum'ı oku (64 B)
    4. Sıkıştırılmış veriyi oku ve checksum'ı doğrula
    5. zlib decompress → BackupSerializer.deserialize
    6. manifest, db_data, file_data olarak döndür

Okuma adımları (v2 — AES-256-GCM şifreli):
    1-3. Aynı (magic, version, checksum)
    4. NONCE oku (12 B)
    5. CIPHERTEXT oku (kalan veri)
    6. checksum = SHA-256(NONCE + CIPHERTEXT) ile doğrula
    7. BackupCipher.decrypt(nonce, ciphertext) → sıkıştırılmış veri
    8. zlib decompress → BackupSerializer.deserialize
    9. manifest, db_data, file_data olarak döndür
"""
from __future__ import annotations

import hashlib
import logging
import struct
import zlib
from pathlib import Path

from ._cipher import BackupCipher
from ._manifest import BackupManifest
from ._protocol import BackupSerializer
from ._writer import FORMAT_VERSION_V1, FORMAT_VERSION_V2, MAGIC

logger = logging.getLogger(__name__)

_CHECKSUM_BYTES: int = 64   # SHA-256 hexdigest uzunluğu
_MAGIC_BYTES: int = 4
_VERSION_BYTES: int = 2
_NONCE_SIZE: int = 12        # AES-GCM nonce boyutu


class BackupReader:
    """Binary .99rb dosyası okur ve bütünlüğünü doğrular.

    Bağımlılık enjeksiyonu: serializer ve isteğe bağlı cipher dışarıdan verilir (DIP).

    Şifre çözme kullanımı:
        - cipher=None          → v1 dosyaları okur (şifresiz)
        - cipher=BackupCipher  → v1 ve v2 dosyaları okur (v2 = şifreli)
        - v2 dosya + cipher=None → ValueError (anahtar eksik)
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

    def read(self, path: Path) -> tuple[BackupManifest, dict, dict]:
        """Yedek dosyasını okur, doğrular ve içeriğini döndürür.

        Returns:
            (manifest, db_data, file_data) üçlüsü.

        Raises:
            ValueError: Geçersiz magic bytes, checksum uyuşmazlığı veya
                        şifreli dosyada cipher eksikliği / hatalı anahtar.
            OSError:    Dosya okuma hatası.
        """
        with path.open("rb") as fh:
            magic = fh.read(_MAGIC_BYTES)
            if magic != MAGIC:
                raise ValueError(
                    f"Geçersiz dosya formatı — magic bytes uyuşmuyor: {magic!r}"
                )

            raw_version = fh.read(_VERSION_BYTES)
            version = struct.unpack(">H", raw_version)[0]

            stored_checksum = fh.read(_CHECKSUM_BYTES).decode("ascii")
            body = fh.read()

        if version == FORMAT_VERSION_V1:
            return self._read_v1(path, version, stored_checksum, body)
        if version == FORMAT_VERSION_V2:
            return self._read_v2(path, version, stored_checksum, body)

        # Bilinmeyen (gelecek) sürüm — v1 yolu ile okumayı dene (uyumluluk)
        logger.warning(
            "Bilinmeyen format versiyonu: %d (desteklenen: v1, v2) — "
            "v1 yolu ile okuma deneniyor",
            version,
        )
        return self._read_v1(path, version, stored_checksum, body)

    # ------------------------------------------------------------------
    # Özel okuma yardımcıları
    # ------------------------------------------------------------------

    def _read_v1(
        self,
        path: Path,
        version: int,
        stored_checksum: str,
        body: bytes,
    ) -> tuple[BackupManifest, dict, dict]:
        """v1 format: şifresiz, zlib sıkıştırılmış."""
        actual_checksum = hashlib.sha256(body).hexdigest()
        if actual_checksum != stored_checksum:
            raise ValueError(
                "Dosya bütünlüğü hatası — checksum uyuşmuyor. "
                f"Beklenen: {stored_checksum[:8]}… Hesaplanan: {actual_checksum[:8]}…"
            )

        raw = zlib.decompress(body)
        return self._parse_payload(path, version, raw)

    def _read_v2(
        self,
        path: Path,
        version: int,
        stored_checksum: str,
        body: bytes,
    ) -> tuple[BackupManifest, dict, dict]:
        """v2 format: AES-256-GCM şifreli.

        body = NONCE(12 B) + CIPHERTEXT(değişken)
        CHECKSUM = SHA-256(NONCE + CIPHERTEXT)
        """
        if self._cipher is None:
            raise ValueError(
                "Yedek dosyası şifreli (v2 format) ancak şifre çözme anahtarı "
                "verilmedi. BACKUP_ENCRYPTION_KEY ayarını kontrol edin."
            )

        actual_checksum = hashlib.sha256(body).hexdigest()
        if actual_checksum != stored_checksum:
            raise ValueError(
                "Dosya bütünlüğü hatası — checksum uyuşmuyor. "
                f"Beklenen: {stored_checksum[:8]}… Hesaplanan: {actual_checksum[:8]}…"
            )

        nonce = body[:_NONCE_SIZE]
        ciphertext = body[_NONCE_SIZE:]

        try:
            compressed = self._cipher.decrypt(nonce, ciphertext)
        except Exception as exc:
            raise ValueError(
                "Şifre çözme hatası — anahtar yanlış veya dosya bozuk."
            ) from exc

        raw = zlib.decompress(compressed)
        return self._parse_payload(path, version, raw)

    def _parse_payload(
        self,
        path: Path,
        version: int,
        raw: bytes,
    ) -> tuple[BackupManifest, dict, dict]:
        """Deserialize edilmiş payload'ı ayrıştırır."""
        payload: dict = self._serializer.deserialize(raw)

        manifest = BackupManifest.from_dict(payload.get("manifest", {}))
        db_data: dict = payload.get("db", {})
        file_data: dict = payload.get("files", {})

        logger.info(
            "Yedek dosyası okundu: path=%s version=%d tables=%d files=%d encrypted=%s",
            path,
            version,
            len(db_data),
            len(file_data),
            version == FORMAT_VERSION_V2,
        )
        return manifest, db_data, file_data
