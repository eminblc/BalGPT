"""Google Gemini REST API adaptörü (DIST-3).

Bağımlılıklar:
    - httpx (zaten requirements.txt'te mevcut)
    - config.settings.gemini_api_key   (GEMINI_API_KEY env değişkeni)
    - config.settings.gemini_model     (varsayılan: gemini-2.0-flash)

Endpoint:
    POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent

Mesaj dönüşümü (OpenAI → Gemini):
    system  → systemInstruction.parts[0].text
    user    → contents[role=user]
    assistant → contents[role=model]
"""
from __future__ import annotations

import logging

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider:
    """Google Gemini generateContent API üzerinden LLM tamamlama sağlar."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self._api_key      = api_key or settings.gemini_api_key.get_secret_value()
        self._default_model = default_model or settings.gemini_model
        self._timeout      = timeout

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> str:
        """Gemini generateContent API'ye istek gönderir, yanıt metnini döndürür.

        OpenAI uyumlu mesaj listesini Gemini formatına dönüştürür:
          - "system" role → systemInstruction
          - "user" / "assistant" → contents (role: user / model)
        """
        if not self._api_key:
            raise RuntimeError(
                "Gemini API anahtarı tanımlı değil (GEMINI_API_KEY)"
            )

        resolved_model = model or self._default_model

        # Sistem mesajını ayır
        system_parts: list[str] = []
        contents: list[dict]    = []
        for msg in messages:
            role    = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                system_parts.append(content)
            elif role == "assistant":
                contents.append({"role": "model", "parts": [{"text": content}]})
            else:
                contents.append({"role": "user", "parts": [{"text": content}]})

        payload: dict = {
            "contents": contents,
            "generationConfig": {
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            payload["systemInstruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }

        url = f"{_API_BASE}/{resolved_model}:generateContent"
        headers = {"x-goog-api-key": self._api_key}

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)

        if not resp.is_success:
            logger.error(
                "GeminiProvider hata: status=%s body=%.200s",
                resp.status_code,
                resp.text,
            )
            resp.raise_for_status()

        data = resp.json()
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Gemini yanıt parse hatası: {data}") from exc
