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

# Reviewer batch'leri (50 finding) Bridge→Claude Code CLI üzerinden 2 dk'yı
# aşabilir. CLAUDE_CODE_TIMEOUT_MS default 300s — httpx tarafı bundan büyük
# olmalı ki Bridge'in kendi timeout yanıtı alınabilsin.
_TIMEOUT = 600.0


class BridgeLLMProvider:
    """Claude Code Bridge üzerinden LLM tamamlama sağlar.

    DIP: settings üzerinden bridge URL ve api_key okur.
    Her complete() çağrısı bağımsız session_id ile gönderilir —
    sohbet geçmişi birikimi olmaz.

    `default_model` constructor parametresi `get_scan_llm()` ve `get_llm()`
    fabrikası tarafından set edilir; complete() çağrısında ayrı model
    belirtilmezse bu değer Bridge'in /query endpoint'ine `model` alanı olarak
    iletilir (Bridge bunu CLI'ye `--model <id>` bayrağıyla aktarır).
    """

    # /effort komutuyla aynı whitelist — Bridge server.js de aynı set'i kabul ediyor.
    _VALID_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "max"})
    # Claude Code CLI `--effort` flag'i SADECE şu modellerde geçerli (Haziran 2026 docs):
    # Opus 4.6, Opus 4.7, Opus 4.8, Sonnet 4.6. Haiku 4.5 effort desteklemez —
    # Fable 5 / Mythos 5 / Sonnet 5 adaptive-only; Sonnet 5 API tarafında
    # output_config.effort kabul etse de CLI `--effort` doğrulanmadığı için
    # bilinçli olarak whitelist dışında (menü zaten bu modellerde effort sormaz).
    # CLI sessiz fallback yapsa bile Bridge tarafında hiç göndermeyiz.
    @staticmethod
    def _supports_cli_effort(model_id: str) -> bool:
        m = (model_id or "").lower()
        if "haiku" in m:
            return False
        if any(k in m for k in ("sonnet-5", "fable-5", "mythos-5")):
            return False
        return "sonnet-4-6" in m or "opus-4-6" in m or "opus-4-7" in m or "opus-4-8" in m

    def __init__(
        self,
        default_model: str | None = None,
        default_effort: str | None = None,
        default_thinking: bool = False,
    ) -> None:
        self._default_model = default_model
        self._default_effort = (
            default_effort if default_effort in self._VALID_EFFORTS else None
        )
        self._default_thinking = bool(default_thinking)

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = 4096,
        effort: str | None = None,
        thinking: bool | None = None,
        cache_system: bool = False,  # noqa: ARG002 — Bridge cache'i kendi yönetir, no-op kabul edilir
    ) -> CompletionResult:
        """Bridge /query endpoint'ine gönderir, text yanıtını döndürür.

        messages listesindeki tüm user/assistant içerikleri birleştirilerek
        Bridge'e tek bir message olarak iletilir.

        cache_system: Claude Code CLI prompt caching'i otomatik uyguladığı için
        bu parametre Bridge tarafında yok sayılır (LSP uyumluluğu).
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

        # Model önceliği: complete(model=...) > self._default_model
        # Bridge server.js /query body'sinden `model` okur ve CLI'ye
        # --model <id> bayrağıyla iletir. Boş string Bridge'i CLI default'una
        # düşürür.
        effective_model = (model or self._default_model or "").strip()

        payload = {
            "session_id":  session_id,
            "message":     prompt,
            "init_prompt": "",
            "silent":      True,
            # PERF-INIT-1: Bridge'in 15KB'lık agentIntro+coreFiles+KESİN YASAKLAR init
            # prompt'unu atla — scan/review prompt'unu zaten kendi kuruyor.
            "bare":        True,
        }
        if effective_model:
            payload["model"] = effective_model

        # Thinking + effort: model bazlı per-capability gate.
        # - Sonnet 4.6 / Opus 4.6 / Opus 4.7 / Opus 4.8: hem thinking hem effort flag'i çalışır.
        # - Haiku 4.5: CLI `--effort` desteklemez; effort hiç gönderilmez.
        # - Fable 5 / Mythos 5: adaptive-only; effort gönderilmez.
        #   Thinking CLI'da `--effort` üzerinden kontrol edildiği için bu
        #   modellerde thinking payload'u da Bridge yolunda no-op.
        effective_thinking = thinking if thinking is not None else self._default_thinking
        effective_effort = effort if effort in self._VALID_EFFORTS else self._default_effort
        if effective_thinking and effective_effort and self._supports_cli_effort(effective_model):
            payload["effort"] = effective_effort
            payload["thinking"] = True

        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{bridge_url}/query",
                headers={"X-Api-Key": api_key},
                json=payload,
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
