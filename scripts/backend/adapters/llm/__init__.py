"""LLM adaptör paketi — sağlayıcıdan bağımsız tamamlama arayüzü (DIP/OCP).

Kullanım:
    from backend.adapters.llm.llm_factory import get_llm

    llm = get_llm()
    response = await llm.complete([{"role": "user", "content": "Merhaba"}])

Yeni sağlayıcı eklemek için:
    1. Bu dizinde yeni bir modül oluştur (ör. gemini_provider.py)
    2. AbstractLLMProvider'ı uygula
    3. llm_factory.py'e elif dalı ekle
    4. config.py'e gerekli env değişkenlerini ekle
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .result import CompletionResult


@runtime_checkable
class AbstractLLMProvider(Protocol):
    """Tüm LLM sağlayıcıların uygulaması gereken arayüz.

    messages formatı (OpenAI uyumlu):
        [
            {"role": "system",    "content": "Sen bir asistansın."},
            {"role": "user",      "content": "Merhaba"},
            {"role": "assistant", "content": "Merhaba! Nasıl yardımcı olabilirim?"},
        ]
    """

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> CompletionResult:
        """Verilen mesaj geçmişine göre bir yanıt üretir.

        Args:
            messages:   Sohbet geçmişi — her eleman {"role": ..., "content": ...}
            model:      Sağlayıcıya özgü model adı; None ise provider'ın konfigüre edilmiş
                        varsayılanı kullanılır. Implementasyonlar bu sözleşmeye UYMALIDIRLAR:
                        model=None geçildiğinde sessizce farklı bir model seçmek yerine
                        provider-configured default'u kullanın.
            max_tokens: Üretilecek maksimum token sayısı.

        Returns:
            CompletionResult — metin, model bilgisi ve token istatistikleri.

        Raises:
            RuntimeError: API çağrısı başarısız olursa.
        """
        ...
