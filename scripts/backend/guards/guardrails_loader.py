"""GUARDRAILS.md okuyucu — yasak komut token'ları ve kategori özetleri.

Modül, proje kökündeki GUARDRAILS.md dosyasını ayrıştırarak iki yardımcı çıktı üretir:

  - load_hint_words()       : bash bloklarındaki ilk token'lar (ön filtre için)
  - load_category_summaries(): KATEGORİ başlıklarının kısa listesi (LLM prompt'a eklemek için)

Her iki fonksiyon try/except ile sarılıdır; dosya okunamazsa
sırasıyla frozenset() ve "" döner — çağıran kodu kırmaz.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# GUARDRAILS.md proje kökünde: scripts/backend/guards/ → ../../.. → proje kökü
_GUARDRAILS_PATH = Path(__file__).parents[3] / "GUARDRAILS.md"


def load_hint_words() -> frozenset[str]:
    """GUARDRAILS.md içindeki ```bash blokları ilk token'larını döndürür.

    Her bash bloğundaki her satırın ilk kelimesi (# ile başlayanlar atlanır)
    küçük harfe çevrilip frozenset'e eklenir. LLM API çağrısı öncesi hızlı
    ön filtre olarak kullanılır — eşleşme yoksa API'ye hiç gidilmez.
    """
    try:
        text = _GUARDRAILS_PATH.read_text(encoding="utf-8")
        words: set[str] = set()
        in_bash = False
        for line in text.splitlines():
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
        logger.debug("GUARDRAILS hint words yüklendi: %d token", len(words))
        return frozenset(words)
    except Exception as exc:
        logger.warning("GUARDRAILS.md hint words yüklenemedi: %s", exc)
        return frozenset()


def load_category_summaries() -> str:
    """GUARDRAILS.md'deki KATEGORİ başlıklarını satır listesi olarak döndürür.

    Örnek çıktı:
        1 — Sistem Kapatma / Yeniden Başlatma
        2 — Dosya Sistemi Silme / Üzerine Yazma
        ...

    LLM sistem prompt'una bağlam olarak eklenir.
    """
    try:
        text = _GUARDRAILS_PATH.read_text(encoding="utf-8")
        lines: list[str] = []
        for line in text.splitlines():
            if line.startswith("## KATEGORİ") and " — " in line:
                summary = line.removeprefix("## KATEGORİ").strip()
                lines.append(summary)
        result = "\n".join(lines)
        logger.debug("GUARDRAILS kategori özetleri yüklendi: %d kategori", len(lines))
        return result
    except Exception as exc:
        logger.warning("GUARDRAILS.md kategori özetleri yüklenemedi: %s", exc)
        return ""
