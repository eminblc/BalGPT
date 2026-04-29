"""LLM tamamlama sonuç tipi — metin + token istatistikleri."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompletionResult:
    """Tek bir LLM tamamlama çağrısının dönüş değeri.

    Attributes:
        text:          Üretilen yanıt metni.
        model_id:      Sağlayıcıya özgü model kimliği (ör. "claude-3-5-haiku-20241022").
        model_name:    İnsan-okunur kategori adı (ör. "Haiku 4.5", "Gemini 2.0 Flash").
        backend:       LLM backend adı ("anthropic" | "gemini" | "ollama").
        input_tokens:  Bu çağrıda tüketilen input token sayısı.
        output_tokens: Bu çağrıda üretilen output token sayısı.
    """

    text: str
    model_id: str
    model_name: str
    backend: str
    input_tokens: int
    output_tokens: int
