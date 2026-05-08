"""BACKUP-9 — AES-256-GCM şifreleme birim testleri.

Test kapsamı:
    - BackupCipher: şifreleme / çözme round-trip
    - BackupCipher: hatalı anahtar → InvalidTag
    - BackupCipher: nonce tekrarsızlığı (her çağrıda farklı nonce)
    - BackupWriter v2: şifreli dosya yazımı
    - BackupReader v2: şifreli dosya okuma round-trip
    - BackupReader v2: anahtar eksik → ValueError
    - BackupReader v2: hatalı anahtar → ValueError
    - BackupWriter v1 + BackupReader v1: geriye dönük uyumluluk korunuyor
    - BackupReader v1: cipher verilse bile v1 dosya okunabilir
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from backend.features.backup._cipher import BackupCipher
from backend.features.backup._manifest import BackupManifest
from backend.features.backup._reader import BackupReader
from backend.features.backup._serializer import MsgpackSerializer
from backend.features.backup._writer import BackupWriter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def serializer() -> MsgpackSerializer:
    return MsgpackSerializer()


@pytest.fixture()
def cipher() -> BackupCipher:
    return BackupCipher("test-secret-key")


@pytest.fixture()
def sample_manifest() -> BackupManifest:
    return BackupManifest.create(
        scope_flags={"db": True, "files": False},
        table_row_counts={"messages": 5},
        file_count=0,
    )


@pytest.fixture()
def sample_db_data() -> dict:
    return {"messages": [{"id": 1, "text": "hello"}, {"id": 2, "text": "world"}]}


@pytest.fixture()
def sample_file_data() -> dict:
    return {}


# ---------------------------------------------------------------------------
# BackupCipher testleri
# ---------------------------------------------------------------------------


class TestBackupCipher:
    def test_encrypt_decrypt_roundtrip(self, cipher: BackupCipher) -> None:
        plaintext = b"Hello, AES-256-GCM!"
        nonce, ciphertext = cipher.encrypt(plaintext)
        result = cipher.decrypt(nonce, ciphertext)
        assert result == plaintext

    def test_ciphertext_differs_from_plaintext(self, cipher: BackupCipher) -> None:
        plaintext = b"sensitive data"
        _, ciphertext = cipher.encrypt(plaintext)
        assert plaintext not in ciphertext  # şifreli veri orijinali içermemeli

    def test_nonce_is_unique_per_call(self, cipher: BackupCipher) -> None:
        """Her şifreleme çağrısında farklı nonce üretilmeli."""
        _, _ = cipher.encrypt(b"data")
        nonces = {cipher.encrypt(b"data")[0] for _ in range(20)}
        assert len(nonces) > 1  # en az 2 farklı nonce beklenir

    def test_wrong_key_raises_on_decrypt(self) -> None:
        cipher_a = BackupCipher("key-a")
        cipher_b = BackupCipher("key-b")
        nonce, ciphertext = cipher_a.encrypt(b"secret")
        with pytest.raises(Exception):  # cryptography.exceptions.InvalidTag
            cipher_b.decrypt(nonce, ciphertext)

    def test_different_passphrases_different_keys(self) -> None:
        c1 = BackupCipher("passphrase-one")
        c2 = BackupCipher("passphrase-two")
        nonce, ct = c1.encrypt(b"test")
        with pytest.raises(Exception):
            c2.decrypt(nonce, ct)

    def test_empty_plaintext(self, cipher: BackupCipher) -> None:
        nonce, ct = cipher.encrypt(b"")
        result = cipher.decrypt(nonce, ct)
        assert result == b""

    def test_large_plaintext(self, cipher: BackupCipher) -> None:
        plaintext = b"x" * 1_000_000  # 1 MB
        nonce, ct = cipher.encrypt(plaintext)
        result = cipher.decrypt(nonce, ct)
        assert result == plaintext


# ---------------------------------------------------------------------------
# BackupWriter v2 + BackupReader v2 testleri
# ---------------------------------------------------------------------------


class TestEncryptedWriteRead:
    def test_write_v2_read_v2_roundtrip(
        self,
        serializer: MsgpackSerializer,
        cipher: BackupCipher,
        sample_manifest: BackupManifest,
        sample_db_data: dict,
        sample_file_data: dict,
    ) -> None:
        """Şifreli yaz → şifreli oku — veri aynı kalmalı."""
        writer = BackupWriter(serializer, cipher=cipher)
        reader = BackupReader(serializer, cipher=cipher)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "backup.99rb"
            writer.write(path, sample_manifest, sample_db_data, sample_file_data)

            manifest, db_data, file_data = reader.read(path)

        assert db_data == sample_db_data
        assert file_data == sample_file_data
        assert manifest.scope_flags == sample_manifest.scope_flags

    def test_v2_file_has_different_bytes_than_v1(
        self,
        serializer: MsgpackSerializer,
        cipher: BackupCipher,
        sample_manifest: BackupManifest,
        sample_db_data: dict,
        sample_file_data: dict,
    ) -> None:
        """v1 ve v2 aynı veri için farklı binary içerik üretmeli."""
        writer_v1 = BackupWriter(serializer, cipher=None)
        writer_v2 = BackupWriter(serializer, cipher=cipher)

        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = Path(tmpdir) / "v1.99rb"
            p2 = Path(tmpdir) / "v2.99rb"
            writer_v1.write(p1, sample_manifest, sample_db_data, sample_file_data)
            writer_v2.write(p2, sample_manifest, sample_db_data, sample_file_data)
            assert p1.read_bytes() != p2.read_bytes()

    def test_v2_without_cipher_raises(
        self,
        serializer: MsgpackSerializer,
        cipher: BackupCipher,
        sample_manifest: BackupManifest,
        sample_db_data: dict,
        sample_file_data: dict,
    ) -> None:
        """Şifreli dosyayı cipher=None ile okumaya çalışmak ValueError raise etmeli."""
        writer = BackupWriter(serializer, cipher=cipher)
        reader_no_cipher = BackupReader(serializer, cipher=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "backup.99rb"
            writer.write(path, sample_manifest, sample_db_data, sample_file_data)

            with pytest.raises(ValueError, match="şifreli"):
                reader_no_cipher.read(path)

    def test_v2_wrong_key_raises(
        self,
        serializer: MsgpackSerializer,
        cipher: BackupCipher,
        sample_manifest: BackupManifest,
        sample_db_data: dict,
        sample_file_data: dict,
    ) -> None:
        """Yanlış anahtar ile v2 okuma ValueError raise etmeli."""
        writer = BackupWriter(serializer, cipher=cipher)
        wrong_cipher = BackupCipher("wrong-key")
        reader_wrong = BackupReader(serializer, cipher=wrong_cipher)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "backup.99rb"
            writer.write(path, sample_manifest, sample_db_data, sample_file_data)

            with pytest.raises(ValueError, match="Şifre çözme hatası"):
                reader_wrong.read(path)

    def test_v2_tampered_data_raises(
        self,
        serializer: MsgpackSerializer,
        cipher: BackupCipher,
        sample_manifest: BackupManifest,
        sample_db_data: dict,
        sample_file_data: dict,
    ) -> None:
        """Checksum uyuşmazlığı ValueError raise etmeli."""
        writer = BackupWriter(serializer, cipher=cipher)
        reader = BackupReader(serializer, cipher=cipher)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "backup.99rb"
            writer.write(path, sample_manifest, sample_db_data, sample_file_data)

            # Son birkaç byte'ı boz
            data = bytearray(path.read_bytes())
            data[-1] ^= 0xFF
            path.write_bytes(bytes(data))

            with pytest.raises(ValueError, match="checksum"):
                reader.read(path)


# ---------------------------------------------------------------------------
# Geriye dönük uyumluluk — v1 testleri
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    def test_v1_write_read_roundtrip(
        self,
        serializer: MsgpackSerializer,
        sample_manifest: BackupManifest,
        sample_db_data: dict,
        sample_file_data: dict,
    ) -> None:
        """v1 (şifresiz) format hâlâ çalışmalı."""
        writer = BackupWriter(serializer, cipher=None)
        reader = BackupReader(serializer, cipher=None)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "backup.99rb"
            writer.write(path, sample_manifest, sample_db_data, sample_file_data)
            manifest, db_data, file_data = reader.read(path)

        assert db_data == sample_db_data

    def test_v1_readable_with_cipher_provided(
        self,
        serializer: MsgpackSerializer,
        cipher: BackupCipher,
        sample_manifest: BackupManifest,
        sample_db_data: dict,
        sample_file_data: dict,
    ) -> None:
        """v1 dosyası, cipher verilmiş reader ile okunabilmeli (cipher yoksayılır)."""
        writer_v1 = BackupWriter(serializer, cipher=None)
        reader_with_cipher = BackupReader(serializer, cipher=cipher)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "backup.99rb"
            writer_v1.write(path, sample_manifest, sample_db_data, sample_file_data)
            _, db_data, _ = reader_with_cipher.read(path)

        assert db_data == sample_db_data

    def test_invalid_magic_raises(
        self,
        serializer: MsgpackSerializer,
    ) -> None:
        """Geçersiz magic bytes → ValueError."""
        reader = BackupReader(serializer)
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.99rb"
            path.write_bytes(b"\x00\x00\x00\x00" + b"\x00" * 100)
            with pytest.raises(ValueError, match="magic bytes"):
                reader.read(path)
