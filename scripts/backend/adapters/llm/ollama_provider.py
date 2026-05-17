"""Ollama REST API adaptörü.

Bağımlılıklar:
    - httpx (zaten requirements.txt'te mevcut)
    - config.settings.ollama_base_url  (varsayılan: http://localhost:11434)
    - config.settings.ollama_model     (varsayılan: llama3)
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from ...config import settings
from .result import CompletionResult

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


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
    ) -> CompletionResult:
        """Ollama /api/chat endpoint'ine istek gönderir, CompletionResult döndürür.

        Ollama, OpenAI uyumlu mesaj formatını destekler (system/user/assistant).
        """
        resolved_model = model or self._default_model
        url = f"{self._base_url}/api/chat"
        payload = {
            "model": resolved_model,
            "messages": [
                {"role": msg["role"], "content": msg["content"]}
                for msg in messages
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    resp = await client.post(url, json=payload)

                if resp.is_success:
                    break

                if resp.status_code not in _RETRYABLE_STATUS:
                    logger.error(
                        "OllamaProvider hata: status=%s body=%.200s",
                        resp.status_code,
                        resp.text,
                    )
                    resp.raise_for_status()

                logger.warning(
                    "OllamaProvider geçici hata (deneme %d/%d): status=%d",
                    attempt + 1, _MAX_RETRIES, resp.status_code,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    resp.raise_for_status()

            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "OllamaProvider timeout (deneme %d/%d): %s",
                    attempt + 1, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
            except httpx.ConnectError as exc:
                last_exc = exc
                logger.warning(
                    "OllamaProvider bağlantı hatası (deneme %d/%d): %s",
                    attempt + 1, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

        if last_exc is not None:
            raise last_exc

        data = resp.json()
        try:
            text = data["message"]["content"]
        except (KeyError, TypeError) as exc:
            raise RuntimeError(f"Ollama yanıt parse hatası: {data}") from exc

        return CompletionResult(
            text=text,
            model_id=resolved_model,
            model_name=f"Ollama/{resolved_model}",
            backend="ollama",
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
        )
