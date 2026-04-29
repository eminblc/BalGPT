"""Doğal dil niyet sınıflandırıcıları — whatsapp_router'dan ayrıştırıldı (REF-3).

Sorumluluk (SRP):
  - Yönetim komutu tespiti (_classify_admin_intent)
  - Yıkıcı işlem tespiti (_classify_destructive_intent)

Her iki sınıflandırıcı da:
  - Hızlı ön filtre ile gereksiz API çağrısını önler
  - AnthropicProvider üzerinden Haiku modelini kullanır
  - GUARDRAILS.md'den dinamik bağlam alır
"""
from __future__ import annotations

import logging

from ..adapters.llm.llm_factory import get_llm
from ..config import settings
from ..guards import guardrails_loader
from ..store.repositories import token_stat_repo

logger = logging.getLogger(__name__)

# ── Ortak hint words (her iki sınıflandırıcı paylaşır) ────────────

_HINT_WORDS: frozenset[str] = guardrails_loader.load_hint_words()

# ── Yönetim komutu (admin intent) ─────────────────────────────────

_ADMIN_HINT_WORDS = _HINT_WORDS


def _build_admin_intent_system() -> str:
    cats   = guardrails_loader.load_category_summaries()
    prompt = (
        "Kullanıcı bir mesaj gönderdi. Bu mesaj aşağıdakilerden birini mi istiyor?\n"
        "  - Servisi/sistemi kapatmak, durdurmak → /shutdown\n"
        "  - Servisi/sistemi yeniden başlatmak → /restart\n"
        "  - Bridge oturumunu veya session'ı sıfırlamak → /root-reset\n"
        "  - Hiçbiri → none\n"
        "Yalnızca tek kelimeyle yanıt ver: /shutdown, /restart, /root-reset veya none."
    )
    if cats:
        prompt += f"\n\nReferans — yasak operasyon kategorileri:\n{cats}"
    return prompt


_ADMIN_INTENT_SYSTEM: str = _build_admin_intent_system()


# Niyet sınıflandırma modeli — backend başlangıcında bir kez hesaplanır (K-N5/K-N6)
_CLASSIFY_MODEL: str | None = (
    settings.intent_classifier_model
    if settings.llm_backend.lower() == "anthropic"
    else None
)


def _has_api_key() -> bool:
    """Aktif backend için API anahtarının tanımlı olup olmadığını kontrol eder."""
    backend = settings.llm_backend.lower()
    if backend == "anthropic":
        return bool(settings.anthropic_api_key.get_secret_value())
    if backend == "gemini":
        return bool(settings.gemini_api_key.get_secret_value())
    return True  # ollama — API anahtarı gerekmez


async def classify_admin_intent(text: str) -> str | None:
    """LLM ile niyet analizi — yönetim komutu tespit eder.

    Dönüş: '/shutdown' | '/restart' | '/root-reset' | None
    """
    if not settings.intent_classifier_enabled:
        return None
    t = text.strip()
    if not any(kw in t.lower() for kw in _ADMIN_HINT_WORDS):
        return None
    if not _has_api_key():
        logger.warning("LLM API anahtarı tanımlı değil — admin niyet analizi devre dışı")
        return None

    try:
        llm = get_llm()
        completion = await llm.complete(
            messages=[
                {"role": "system", "content": _ADMIN_INTENT_SYSTEM},
                {"role": "user",   "content": t},
            ],
            model=_CLASSIFY_MODEL,
            max_tokens=16,
        )
        try:
            await token_stat_repo.add_usage(
                completion.model_id, completion.model_name, completion.backend,
                completion.input_tokens, completion.output_tokens,
                context="intent_classifier",
            )
        except Exception:
            pass
        stripped = completion.text.strip()
        if not stripped:
            return None
        cmd = stripped.split()[0]
        if cmd in ("/shutdown", "/restart", "/root-reset"):
            return cmd
    except Exception as exc:
        logger.warning("Admin intent sınıflandırma hatası: %s", exc)
    return None


# ── Yıkıcı işlem tespiti (destructive intent) ─────────────────────

_DESTRUCTIVE_HINT_WORDS = _HINT_WORDS


def _build_destructive_intent_system() -> str:
    cats = guardrails_loader.load_category_summaries()
    base = (
        "Kullanıcı bir mesaj gönderdi. Bu mesaj aşağıdakilerden birini yapmamı istiyor mu?\n"
        "  - Sistem dosyalarını veya kritik dizinleri silmek/üzerine yazmak\n"
        "  - Veritabanı tablolarını DROP / TRUNCATE etmek\n"
        "  - Çalışan kritik süreçleri kill/pkill ile öldürmek\n"
        "  - Dosya izinlerini veya sahipliğini değiştirmek (chmod, chown)\n"
        "  - Hassas dosyaları okumak (.env, id_rsa, /etc/shadow)\n"
        "  - Git'te yıkıcı işlem (force push, reset --hard)\n"
        "  - Ağ/güvenlik duvarı kurallarını değiştirmek\n"
        "  - Kök seviyesinde paket/kernel değişikliği\n\n"
        "Dikkat: 'listeden sil', 'notu kaldır', 'proje sil' gibi uygulama içi silme işlemleri "
        "YIKİCİ DEĞİLDİR. Sadece sistem/altyapı seviyesindeki tehlikeli işlemleri say.\n\n"
        "Sadece tek kelimeyle yanıt ver: evet veya hayır."
    )
    if cats:
        base += f"\n\nReferans — tüm yasak operasyon kategorileri:\n{cats}"
    return base


_DESTRUCTIVE_INTENT_SYSTEM: str = _build_destructive_intent_system()


async def classify_destructive_intent(text: str) -> bool:
    """LLM ile yıkıcı işlem tespiti — GUARDRAILS.md kategorilerine göre."""
    if not settings.intent_classifier_enabled:
        return False
    t = text.strip()
    if not any(kw in t.lower() for kw in _DESTRUCTIVE_HINT_WORDS):
        return False
    if not _has_api_key():
        logger.warning("LLM API anahtarı tanımlı değil — yıkıcı niyet analizi devre dışı")
        return False

    try:
        llm = get_llm()
        completion = await llm.complete(
            messages=[
                {"role": "system", "content": _DESTRUCTIVE_INTENT_SYSTEM},
                {"role": "user",   "content": t},
            ],
            model=_CLASSIFY_MODEL,
            max_tokens=8,
        )
        try:
            await token_stat_repo.add_usage(
                completion.model_id, completion.model_name, completion.backend,
                completion.input_tokens, completion.output_tokens,
                context="intent_classifier",
            )
        except Exception:
            pass
        stripped = completion.text.strip()
        if not stripped:
            return False
        answer = stripped.lower().split()[0]
        return answer == "evet"
    except Exception as exc:
        logger.warning("Yıkıcı niyet sınıflandırma hatası: %s", exc)
    return False
