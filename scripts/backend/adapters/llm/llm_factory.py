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

import logging

from ...config import settings
from ...guards.runtime_state import get_active_model
from . import AbstractLLMProvider
from .anthropic_provider import AnthropicProvider
from .ollama_provider import OllamaProvider
from .gemini_provider import GeminiProvider

logger = logging.getLogger(__name__)

# Backend adı → sağlayıcı sınıfı (OCP: yeni backend = yeni giriş, mevcut if/elif yok)
_BACKENDS: dict[str, type[AbstractLLMProvider]] = {
    "anthropic": AnthropicProvider,
    "ollama":    OllamaProvider,
    "gemini":    GeminiProvider,
}


def register_backend(name: str, cls: type[AbstractLLMProvider]) -> None:
    """Dış paket veya eklenti için LLM backend kaydı.

    Örnek:
        from backend.adapters.llm.llm_factory import register_backend
        from mypackage.my_provider import MyProvider
        register_backend("myprovider", MyProvider)
    """
    _BACKENDS[name] = cls
    logger.debug("LLM backend kaydedildi: %s", name)


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
    return cls(default_model=active) if active is not None else cls()
