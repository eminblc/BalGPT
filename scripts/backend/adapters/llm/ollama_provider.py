"""Ollama REST API adaptörü.

Bağımlılıklar:
    - httpx (zaten requirements.txt'te mevcut)
    - config.settings.ollama_base_url  (varsayılan: http://localhost:11434)
    - config.settings.ollama_model     (varsayılan: llama3)
"""
from __future__ import annotations

import logging

import httpx

from ...config import settings

logger = logging.getLogger(__name__)


class OllamaProvider:
    """Ollama /api/chat endpoint'i üzerinden LLM tamamlama sağlar."""

    def __init__(
        self,
        base_url: str | None = None,
        default_model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._default_model = default_model or settings.ollama_model
        self._timeout = timeout

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> str:
        """Ollama /api/chat endpoint'ine istek gönderir, yanıt metnini döndürür.

        Ollama, OpenAI uyumlu mesaj formatını destekler (system/user/assistant).
        """
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": model or self._default_model,
            "messages": [
                {"role": msg["role"], "content": msg["content"]}
                for msg in messages
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=payload)

        if not resp.is_success:
            logger.error(
                "OllamaProvider hata: status=%s body=%.200s",
                resp.status_code,
                resp.text,
            )
            resp.raise_for_status()

        data = resp.json()
        try:
            return data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Ollama yanıt parse hatası: {data}") from exc
