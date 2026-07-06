"""LLM sağlayıcı fabrikası — LLM_BACKEND env değerine göre uygun adaptörü döndürür.

Kullanım:
    from backend.adapters.llm.llm_factory import get_llm

    llm = get_llm()
    text = await llm.complete([{"role": "user", "content": "Merhaba"}])

Yeni backend eklemek:
    1. adapters/llm/myprovider_provider.py oluştur
    2. Bu dosyaya import + register_backend() çağrısı ekle
    3. config.py ve .env.example'a gerekli ayarları ekle
"""
from __future__ import annotations

import asyncio
import inspect
import logging

from ...config import settings
from ...guards.runtime_state import get_active_model
from . import AbstractLLMProvider
from .anthropic_provider import AnthropicProvider
from .ollama_provider import OllamaProvider
from .gemini_provider import GeminiProvider
from .bridge_provider import BridgeLLMProvider

logger = logging.getLogger(__name__)

# Backend adı → sağlayıcı sınıfı (OCP: yeni backend = yeni giriş, mevcut if/elif yok)
_BACKENDS: dict[str, type[AbstractLLMProvider]] = {
    "anthropic": AnthropicProvider,
    "ollama":    OllamaProvider,
    "gemini":    GeminiProvider,
    "bridge":    BridgeLLMProvider,
}


def register_backend(name: str, cls: type[AbstractLLMProvider]) -> None:
    """Dış paket veya eklenti için LLM backend kaydı.

    Örnek:
        from backend.adapters.llm.llm_factory import register_backend
        from mypackage.my_provider import MyProvider
        register_backend("myprovider", MyProvider)

    Raises:
        TypeError: cls bir tür değilse veya `complete` metodu yoksa.
        ValueError: `complete` metodu async (coroutine function) değilse.
    """
    if not (isinstance(cls, type) and callable(getattr(cls, "complete", None))):
        raise TypeError(
            f"register_backend: {cls!r} geçerli bir LLM sağlayıcı sınıfı değil — "
            "AbstractLLMProvider Protocol'ünü (complete() metodu) uygulamalı."
        )
    # IMP-ADAP-4: complete() async olmalı — sync implementasyonlar asyncio event loop'unu bloklar
    if not asyncio.iscoroutinefunction(cls.complete):
        raise ValueError(
            f"register_backend: {cls.__name__}.complete() async (coroutine function) değil. "
            "LLM provider'lar asyncio uyumluluğu için `async def complete(...)` kullanmalı."
        )
    _BACKENDS[name] = cls
    logger.debug("LLM backend kaydedildi: %s", name)


def _accepts_default_model(cls: type) -> bool:
    """Sınıfın __init__ metodunun `default_model` parametresi alıp almadığını kontrol eder.

    LSP güvencesi: AbstractLLMProvider Protocol'ü constructor imzasını sözleşmeye
    dahil etmez. register_backend() üzerinden eklenen yeni sağlayıcılar
    `default_model` desteklemeyebilir; bu kontrol sessiz TypeError'ı önler.
    """
    try:
        sig = inspect.signature(cls.__init__)
        return "default_model" in sig.parameters
    except (ValueError, TypeError):
        return False


def _accepts_default_effort(cls: type) -> bool:
    """Sınıfın __init__ metodu `default_effort` parametresi alıyor mu?

    AnthropicProvider ve BridgeLLMProvider destekler; OllamaProvider/GeminiProvider
    desteklemez — sessiz TypeError önlenir.
    """
    try:
        sig = inspect.signature(cls.__init__)
        return "default_effort" in sig.parameters
    except (ValueError, TypeError):
        return False


# Scan için model alias → tam model adı (model_cmd.py ile senkron)
_SCAN_MODEL_ALIASES: dict[str, str] = {
    "haiku":   "claude-haiku-4-5-20251001",
    "sonnet":  "claude-sonnet-4-6",
    "sonnet5": "claude-sonnet-5",
    "opus":    "claude-opus-4-8",
    "fable":   "claude-fable-5",
}


def resolve_model_alias(model: str | None) -> str:
    """Model alias'ını ("haiku" | "sonnet" | "sonnet5" | "opus" | "fable") tam model ID'sine çevirir.

    Alias değilse (tam model adı verilmişse) olduğu gibi döndürür; boş/None → "".
    Scan pipeline ve backlog executor bu tek kaynağı kullanır — alias listesi
    yalnızca burada güncellenir.
    """
    if not model:
        return ""
    return _SCAN_MODEL_ALIASES.get(model.lower().strip(), model.strip())


def get_scan_llm(
    model: str | None = None,
    effort: str | None = None,
    thinking: bool = False,
) -> AbstractLLMProvider:
    """Scan/review görevleri için LLM provider döndürür.

    Args:
        model: Opsiyonel alias veya tam model adı (ör. "haiku", "sonnet", "opus").
               Verilmezse varsayılan model kullanılır.
        effort: Opsiyonel effort seviyesi ("low" | "medium" | "high" | "max").
                thinking=True iken AnthropicProvider için extended thinking
                budget_tokens'ına çevrilir; BridgeLLMProvider için Bridge'e
                effort + thinking alanı olarak iletilir. thinking=False iken
                effort gönderilmez (VS Code UX'iyle birebir aynı davranış).
        thinking: Extended Thinking on/off toggle. False (varsayılan) iken
                  effort seviyesi seçili olsa bile gönderilmez.

    Öncelik sırası:
    1. LLM_BACKEND=anthropic ve ANTHROPIC_API_KEY tanımlı → AnthropicProvider
    2. LLM_BACKEND=anthropic ama API key yok           → BridgeLLMProvider (fallback)
    3. LLM_BACKEND=bridge                              → BridgeLLMProvider
    4. LLM_BACKEND=ollama/gemini/diğer                → get_llm() (normal akış)

    Bridge her zaman kullanılabilir fallback — API key gerektirmez.
    """
    resolved = settings.llm_backend.lower().strip()

    # Alias → tam model adı (Anthropic ve Bridge için ortak)
    resolved_model = resolve_model_alias(model) or None
    # Effort sanitize: "off" / boş / geçersiz → None (provider'lar zaten None'ı handle ediyor)
    resolved_effort = effort if effort in {"low", "medium", "high", "max"} else None

    if resolved == "anthropic":
        try:
            key = settings.anthropic_api_key.get_secret_value()
            if key and key.strip():
                logger.debug(
                    "get_scan_llm: Anthropic API key mevcut, AnthropicProvider model=%s effort=%s thinking=%s",
                    resolved_model, resolved_effort, thinking,
                )
                kwargs: dict = {"default_thinking": bool(thinking)}
                if resolved_model:
                    kwargs["default_model"] = resolved_model
                if resolved_effort:
                    kwargs["default_effort"] = resolved_effort
                return AnthropicProvider(**kwargs)
        except Exception:
            pass
        logger.debug(
            "get_scan_llm: Anthropic API key yok, Bridge fallback model=%s effort=%s thinking=%s",
            resolved_model, resolved_effort, thinking,
        )
        return BridgeLLMProvider(
            default_model=resolved_model,
            default_effort=resolved_effort,
            default_thinking=bool(thinking),
        )

    if resolved == "bridge":
        logger.debug(
            "get_scan_llm: Bridge backend, BridgeLLMProvider model=%s effort=%s thinking=%s",
            resolved_model, resolved_effort, thinking,
        )
        return BridgeLLMProvider(
            default_model=resolved_model,
            default_effort=resolved_effort,
            default_thinking=bool(thinking),
        )

    return get_llm(resolved)


def get_llm(backend: str | None = None) -> AbstractLLMProvider:
    """LLM_BACKEND'e göre uygun AbstractLLMProvider örneği döndürür.

    Args:
        backend: Zorunlu değil; verilmezse config.settings.llm_backend kullanılır.

    Returns:
        AbstractLLMProvider örneği.

    Raises:
        ValueError: Bilinmeyen backend değeri verilirse.
    """
    resolved = (backend or settings.llm_backend).lower().strip()
    cls = _BACKENDS.get(resolved)
    if cls is None:
        raise ValueError(
            f"Bilinmeyen LLM_BACKEND değeri: '{resolved}'. "
            f"Desteklenenler: {', '.join(_BACKENDS)}"
        )
    logger.debug("LLM backend: %s", cls.__name__)
    active = get_active_model()
    if active is not None and _accepts_default_model(cls):
        return cls(default_model=active)
    return cls()
