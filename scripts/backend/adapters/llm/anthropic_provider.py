"""Anthropic Messages API adaptörü.

Bağımlılıklar:
    - httpx (zaten requirements.txt'te mevcut)
    - config.settings.anthropic_api_key
    - config.settings.default_model
"""
from __future__ import annotations

import logging

import httpx

from ...config import settings
from ...constants import LLM_MAX_TOKENS_DEFAULT
from .result import CompletionResult

logger = logging.getLogger(__name__)

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"

_MODEL_NAMES: dict[str, str] = {
    "claude-3-5-haiku-20241022": "Haiku 4.5",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
    "claude-3-5-sonnet-20241022": "Sonnet 4.6",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-opus-4-6": "Opus 4.6",
    "claude-opus-4-7": "Opus 4.7",
}


class AnthropicProvider:
    """Anthropic Messages API üzerinden LLM tamamlama sağlar."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or settings.anthropic_api_key.get_secret_value()
        self._default_model = default_model or settings.default_model
        self._timeout = timeout

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = LLM_MAX_TOKENS_DEFAULT,
    ) -> CompletionResult:
        """Anthropic Messages API'ye istek gönderir, CompletionResult döndürür.

        messages içindeki "system" role'lü girişler ayrıştırılarak
        API'nin üst düzey `system` parametresine taşınır.
        """
        if not self._api_key:
            raise RuntimeError(
                "Anthropic API anahtarı tanımlı değil (ANTHROPIC_API_KEY)"
            )

        resolved_model = model or self._default_model

        # Sistem mesajlarını ayır — Anthropic API ayrı bir `system` alanı bekler
        system_parts: list[str] = []
        chat_messages: list[dict] = []
        for msg in messages:
            if msg.get("role") == "system":
                system_parts.append(msg.get("content", ""))
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        payload: dict = {
            "model": resolved_model,
            "max_tokens": max_tokens,
            "messages": chat_messages,
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                _API_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": _API_VERSION,
                    "content-type": "application/json",
                },
                json=payload,
            )

        if not resp.is_success:
            logger.error(
                "AnthropicProvider hata: status=%s body=%.200s",
                resp.status_code,
                resp.text,
            )
            resp.raise_for_status()

        data = resp.json()
        try:
            text = data["content"][0]["text"]
        except (KeyError, IndexError) as exc:
            raise RuntimeError(f"Anthropic yanıt parse hatası: {data}") from exc

        usage = data.get("usage", {})
        return CompletionResult(
            text=text,
            model_id=resolved_model,
            model_name=_MODEL_NAMES.get(resolved_model, resolved_model),
            backend="anthropic",
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )
