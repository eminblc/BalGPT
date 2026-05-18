"""Bridge LLM adaptörü — scan/batch görevleri için Claude Code Bridge üzerinden LLM çağrısı.

Her çağrı benzersiz session_id ile gönderilir; conversation history sıfırlanır.
Bu sayede API key gerektirmez — Bridge'in kendi key'ini kullanır.
"""
from __future__ import annotations

import logging
import uuid

import httpx

from ...config import settings
from . import AbstractLLMProvider
from .result import CompletionResult

logger = logging.getLogger(__name__)

# Scan chunk'ları küçük; 120s yeterli
_TIMEOUT = 120.0


class BridgeLLMProvider:
    """Claude Code Bridge üzerinden LLM tamamlama sağlar.

    DIP: settings üzerinden bridge URL ve api_key okur.
    Her complete() çağrısı bağımsız session_id ile gönderilir —
    sohbet geçmişi birikimi olmaz.
    """

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> CompletionResult:
        """Bridge /query endpoint'ine gönderir, text yanıtını döndürür.

        messages listesindeki tüm user/assistant içerikleri birleştirilerek
        Bridge'e tek bir message olarak iletilir.
        """
        parts: list[str] = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                parts.insert(0, content)
            else:
                parts.append(content)
        prompt = "\n\n".join(p for p in parts if p)

        session_id = f"scan_chunk_{uuid.uuid4().hex[:12]}"
        bridge_url = settings.claude_bridge_url.rstrip("/")
        api_key = settings.api_key.get_secret_value()

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{bridge_url}/query",
                headers={"X-Api-Key": api_key},
                json={"session_id": session_id, "message": prompt, "init_prompt": "", "silent": True},
            )
            resp.raise_for_status()
            data = resp.json()

        answer: str = data.get("answer") or ""
        return CompletionResult(
            text=answer,
            model_id="bridge",
            model_name="Bridge (Claude Code CLI)",
            backend="bridge",
            input_tokens=0,
            output_tokens=0,
        )
