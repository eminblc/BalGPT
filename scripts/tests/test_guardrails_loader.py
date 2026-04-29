"""guardrails_loader.py token listesi doğrulama testleri (GR-2).

Bu test dosyası `load_hint_words()` ve `load_category_summaries()` fonksiyonlarının
GUARDRAILS.md içeriğini doğru yüklediğini doğrular:

- `load_hint_words()` — bash bloklarındaki tüm first-token'ların frozenset olarak
  döndürüldüğünü; kritik komutların (rm, sudo, shutdown, …) eksik olmadığını kontrol eder.
- `load_category_summaries()` — kategori başlıklarının metin olarak döndürüldüğünü
  ve beklenen başlıkların var olduğunu kontrol eder.
- Dosya yok / okunamaz durumunda graceful fallback (boş değerler) doğrulanır.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from backend.guards.guardrails_loader import load_hint_words, load_category_summaries

# GUARDRAILS.md proje kökünde — bu testten göreli yol
# scripts/tests/ → scripts/ → proje-kökü  (parents[2])
_GUARDRAILS_PATH = Path(__file__).parents[2] / "GUARDRAILS.md"


# ── Yardımcı: bağımsız token çıkarma ─────────────────────────────────────────

def _extract_tokens_from_file(path: Path) -> frozenset[str]:
    """Loader ile aynı algoritmayı kullanarak token'ları bağımsız çıkarır.

    Test, loader'ın çıktısını bu referans çıktıyla karşılaştırır.
    Amaç: loader kodunun GUARDRAILS.md'deki bash bloklarını eksiksiz yönetip
    yönetmediğini doğrulamak.
    """
    words: set[str] = set()
    in_bash = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "```bash":
            in_bash = True
            continue
        if in_bash and stripped == "```":
            in_bash = False
            continue
        if in_bash and stripped and not stripped.startswith("#"):
            first_token = stripped.split()[0].lower()
            if first_token:
                words.add(first_token)
    return frozenset(words)


# ── load_hint_words ───────────────────────────────────────────────────────────

def test_hint_words_returns_frozenset():
    result = load_hint_words()
    assert isinstance(result, frozenset)


def test_hint_words_nonempty():
    """GUARDRAILS.md mevcut ve dolu; sonuç boş olmamalı."""
    result = load_hint_words()
    assert len(result) > 0, "load_hint_words() boş frozenset döndürdü"


def test_hint_words_matches_independent_extraction():
    """Loader çıktısı, bağımsız referans çıkarma ile tam eşleşmeli."""
    assert _GUARDRAILS_PATH.exists(), "GUARDRAILS.md bulunamadı — test ortamı hatalı"
    expected = _extract_tokens_from_file(_GUARDRAILS_PATH)
    actual = load_hint_words()
    missing = expected - actual
    assert not missing, (
        f"load_hint_words() şu token'ları döndürmedi: {sorted(missing)}"
    )


def test_hint_words_no_extra_tokens():
    """Loader, dosyada olmayan token üretmemeli."""
    expected = _extract_tokens_from_file(_GUARDRAILS_PATH)
    actual = load_hint_words()
    extra = actual - expected
    assert not extra, (
        f"load_hint_words() fazladan token içeriyor: {sorted(extra)}"
    )


# ── Kritik komutlar ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("token", [
    # Dosya sistemi yıkımı
    "rm", "shred", "dd", "mkfs.ext4",
    # Sistem yönetimi
    "shutdown", "reboot", "systemctl",
    # Yetki yükseltme
    "sudo", "su", "chmod", "chown",
    # Süreç öldürme
    "kill", "killall", "pkill", "fuser",
    # Ağ
    "iptables", "ufw", "nc", "nmap",
    # Paket yönetimi (GR-1)
    "pip3", "npx", "yarn",
    # Git yıkıcı
    "git",
    # Veri tabanı
    "sqlite3",
    # Uzak çalıştırma / RCE
    "curl", "wget", "bash", "sh",
    # SSH
    "ssh", "ssh-keygen", "scp",
])
def test_critical_token_present(token: str):
    """Belirli kritik komutlar hint words içinde bulunmalı."""
    result = load_hint_words()
    assert token in result, (
        f"Kritik token '{token}' load_hint_words() içinde bulunamadı"
    )


# ── Graceful fallback — dosya yok ────────────────────────────────────────────

def test_hint_words_missing_file_returns_empty_frozenset():
    """GUARDRAILS.md okunamazsa load_hint_words() frozenset() döndürmeli."""
    with patch(
        "backend.guards.guardrails_loader._GUARDRAILS_PATH",
        Path("/nonexistent/path/GUARDRAILS.md"),
    ):
        result = load_hint_words()
    assert result == frozenset()


# ── load_category_summaries ───────────────────────────────────────────────────

def test_category_summaries_returns_str():
    result = load_category_summaries()
    assert isinstance(result, str)


def test_category_summaries_nonempty():
    result = load_category_summaries()
    assert result.strip(), "load_category_summaries() boş string döndürdü"


def test_category_summaries_min_count():
    """GUARDRAILS.md en az 60 kategori içermeli."""
    result = load_category_summaries()
    lines = [ln for ln in result.splitlines() if ln.strip()]
    assert len(lines) >= 60, (
        f"Beklenen en az 60 kategori, bulunan: {len(lines)}"
    )


@pytest.mark.parametrize("fragment", [
    "Sistem Kapatma",
    "Dosya Sistemi Silme",
    "Kritik Süreç Öldürme",
    "Hassas Veri Okuma",
    "Git Yıkıcı İşlemleri",
    "Veritabanı Yıkımı",
    "Uzak Kod Çalıştırma",
    "Pipe ile Uzak Script",   # GR-1 ile eklenen KATEGORİ 61
    "Sistem Geneli Paket",    # GR-1 ile eklenen KATEGORİ 62
])
def test_expected_category_present(fragment: str):
    """Beklenen kategori başlık fragmanları load_category_summaries() içinde yer almalı."""
    result = load_category_summaries()
    assert fragment in result, (
        f"Kategori fragmanı '{fragment}' load_category_summaries() içinde bulunamadı"
    )


def test_category_summaries_missing_file_returns_empty_string():
    """GUARDRAILS.md okunamazsa load_category_summaries() '' döndürmeli."""
    with patch(
        "backend.guards.guardrails_loader._GUARDRAILS_PATH",
        Path("/nonexistent/path/GUARDRAILS.md"),
    ):
        result = load_category_summaries()
    assert result == ""
