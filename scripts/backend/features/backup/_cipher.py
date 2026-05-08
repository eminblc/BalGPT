"""BackupCipher — AES-256-GCM şifreleme / çözme (SRP).

Yalnızca kriptografik operasyonlardan sorumludur.
Key türetme, nonce üretimi ve AEAD tag doğrulama bu modülde kapsüllenmiştir.

Kullanım:
    cipher = BackupCipher("my-passphrase")
    nonce, ciphertext = cipher.encrypt(plaintext_bytes)
    original   = cipher.decrypt(nonce, ciphertext)

Güvenlik notları:
    - Anahtar: SHA-256(passphrase) → 32 byte — her zaman 256-bit AES anahtarı üretir.
    - Nonce:   os.urandom(12) — her şifreleme işleminde yeniden üretilir (IV/nonce tekrarı yok).
    - AEAD tag (16 byte) GCM tarafından ciphertext'e dahil edilir; ayrıca saklanmaz.
    - Yanlış anahtar veya bozuk veri → cryptography.exceptions.InvalidTag raise edilir.
"""
from __future__ import annotations

import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_SIZE: int = 12  # AES-GCM standardı — 96-bit nonce


class BackupCipher:
    """AES-256-GCM şifreleme/çözme.

    DIP: BackupWriter ve BackupReader bu sınıfı doğrudan değil,
    isteğe bağlı parametre olarak alır; None geçilirse şifreleme devre dışı kalır.
    """

    def __init__(self, passphrase: str) -> None:
        """Passphrase'den 256-bit AES anahtarı türetir.

        Args:
            passphrase: Herhangi uzunlukta string anahtar cümlesi.
                        SHA-256 ile 32 byte'a normalize edilir.
        """
        key_bytes: bytes = hashlib.sha256(passphrase.encode("utf-8")).digest()
        self._aesgcm = AESGCM(key_bytes)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def encrypt(self, plaintext: bytes) -> tuple[bytes, bytes]:
        """Plaintext'i AES-256-GCM ile şifreler.

        Args:
            plaintext: Şifrelenecek ham veri.

        Returns:
            (nonce, ciphertext) çifti.
            nonce:      12 random byte — BackupWriter dosyaya yazar.
            ciphertext: Şifreli veri + 16-byte GCM tag.
        """
        nonce = os.urandom(_NONCE_SIZE)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, None)
        return nonce, ciphertext

    def decrypt(self, nonce: bytes, ciphertext: bytes) -> bytes:
        """Şifreli veriyi AES-256-GCM ile çözer ve doğrular.

        Args:
            nonce:      encrypt() tarafından üretilen 12-byte nonce.
            ciphertext: Şifreli veri + GCM tag.

        Returns:
            Orijinal plaintext bytes.

        Raises:
            cryptography.exceptions.InvalidTag: Hatalı anahtar veya bozuk veri.
        """
        return self._aesgcm.decrypt(nonce, ciphertext, None)
