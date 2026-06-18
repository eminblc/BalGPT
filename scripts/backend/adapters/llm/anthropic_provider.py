"""Anthropic Messages API adaptörü.

Bağımlılıklar:
    - httpx (zaten requirements.txt'te mevcut)
    - config.settings.anthropic_api_key
    - config.settings.default_model
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from ...config import settings
from ...constants import LLM_MAX_TOKENS_DEFAULT
from .result import CompletionResult

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
# HTTP durum kodları — geçici hatalar için yeniden deneme yapılır
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"

_MODEL_NAMES: dict[str, str] = {
    "claude-3-5-haiku-20241022": "Haiku 4.5",
    "claude-haiku-4-5-20251001": "Haiku 4.5",
    "claude-3-5-sonnet-20241022": "Sonnet 4.6",
    "claude-sonnet-4-6": "Sonnet 4.6",
    "claude-opus-4-6": "Opus 4.6",
    "claude-opus-4-7": "Opus 4.7",
    "claude-opus-4-8": "Opus 4.8",
    "claude-fable-5": "Fable 5",
    "claude-mythos-5": "Mythos 5",
}

# Effort seviyesi → extended thinking budget_tokens (Anthropic Messages API
# `thinking.enabled` payload formatı için). Yalnızca _supports_manual_thinking()
# True dönen modellerde uygulanır.
_EFFORT_BUDGETS: dict[str, int] = {
    "low":    1024,
    "medium": 4000,
    "high":   16000,
    "max":    32000,
}


def _is_haiku_4_5(model_id: str) -> bool:
    """Haiku 4.5 ailesi mi? (claude-haiku-4-5-*)"""
    m = (model_id or "").lower()
    return "haiku-4-5" in m


def _is_opus_4_7(model_id: str) -> bool:
    """Opus 4.7 ailesi mi? (claude-opus-4-7*)"""
    m = (model_id or "").lower()
    return "opus-4-7" in m


def _is_adaptive_only(model_id: str) -> bool:
    """Yalnızca adaptive thinking destekleyen model mi?

    Anthropic docs (Haziran 2026): Opus 4.7, Opus 4.8, Fable 5, Mythos 5
    manual thinking'i KABUL ETMEZ — yalnızca adaptive.
    """
    m = (model_id or "").lower()
    return any(k in m for k in ("opus-4-7", "opus-4-8", "fable-5", "mythos-5"))


def _supports_manual_thinking(model_id: str) -> bool:
    """Model `thinking: {type:"enabled", budget_tokens:N}` payload'unu destekliyor mu?

    Anthropic docs (Haziran 2026):
    - Desteklemez (400 error): Opus 4.7, Opus 4.8, Fable 5, Mythos 5, Haiku ailesi
    - Destekler: Sonnet 4.6, Opus 4.6, Sonnet 4.5 ve önceki sürümler
    Haiku 3.5 ve eski tüm Haiku'lar thinking desteklemez.
    """
    m = (model_id or "").lower()
    if not m:
        return False
    if "haiku" in m:
        return False
    if _is_adaptive_only(m):
        return False
    return True


def _supports_adaptive_thinking(model_id: str) -> bool:
    """Model `thinking: {type:"adaptive"}` payload'unu destekliyor mu?

    Anthropic docs (Haziran 2026): Opus 4.7/4.8, Fable 5, Mythos 5, Sonnet 4.6,
    Opus 4.6, Haiku 4.5 adaptive thinking destekler.
    """
    m = (model_id or "").lower()
    if _is_adaptive_only(m):
        return True
    if "sonnet-4-6" in m or "opus-4-6" in m:
        return True
    if _is_haiku_4_5(m):
        return True
    return False


class AnthropicProvider:
    """Anthropic Messages API üzerinden LLM tamamlama sağlar."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str | None = None,
        default_effort: str | None = None,
        default_thinking: bool = False,
        timeout: float = 60.0,
    ) -> None:
        self._api_key = api_key or settings.anthropic_api_key.get_secret_value()
        self._default_model = default_model or settings.default_model
        self._default_effort = default_effort if default_effort in _EFFORT_BUDGETS else None
        self._default_thinking = bool(default_thinking)
        self._timeout = timeout

    async def complete(
        self,
        messages: list[dict],
        model: str | None = None,
        max_tokens: int = LLM_MAX_TOKENS_DEFAULT,
        effort: str | None = None,
        thinking: bool | None = None,
        cache_system: bool = False,
    ) -> CompletionResult:
        """Anthropic Messages API'ye istek gönderir, CompletionResult döndürür.

        messages içindeki "system" role'lü girişler ayrıştırılarak
        API'nin üst düzey `system` parametresine taşınır.

        cache_system=True iken system bloğu `cache_control: {type: ephemeral}`
        ile işaretlenir — aynı prefix 5 dakika içinde tekrar gönderilirse cache
        hit (input fiyatı %10'a düşer). Yalnızca system >= 1024 token (Sonnet/
        Opus) veya >= 2048 token (Haiku) olduğunda etkili — daha kısa
        prefix'lerde Anthropic cache yazmayı reddeder, ek maliyet doğurmaz.
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
            system_text = "\n\n".join(system_parts)
            if cache_system:
                # Content block listesi formatı — cache_control ephemeral (5 dk TTL)
                payload["system"] = [
                    {
                        "type": "text",
                        "text": system_text,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            else:
                payload["system"] = system_text

        # Extended thinking ayarı modele göre iki farklı payload:
        #   1) Manual mode  → thinking: {type:"enabled", budget_tokens:N}
        #      Modeller: Sonnet 4.6, Opus 4.6, Sonnet 4.5 ve önceki sürümler.
        #      Anthropic API zorunluluğu: max_tokens > budget_tokens, temperature=1.0
        #   2) Adaptive mode → thinking: {type:"adaptive"}
        #      Modeller: Opus 4.7, Opus 4.8, Fable 5, Mythos 5, Haiku 4.5
        #      (effort seviyesi yok, budget_tokens yok).
        #      Adaptive modda kullanıcının seçtiği effort seviyesi taşımaz —
        #      model dinamik olarak karar verir.
        #   3) Thinking yok → eski modeller (Haiku 3.5 vb.) veya thinking=off.
        effective_thinking = thinking if thinking is not None else self._default_thinking
        effective_effort = effort if effort in _EFFORT_BUDGETS else self._default_effort
        if effective_thinking:
            if _supports_manual_thinking(resolved_model) and effective_effort:
                budget = _EFFORT_BUDGETS[effective_effort]
                payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
                # max_tokens budget'ı aşmak zorunda — yetersizse otomatik artır
                min_required = budget + 1024
                if payload["max_tokens"] < min_required:
                    payload["max_tokens"] = min_required
                payload["temperature"] = 1.0
            elif _supports_adaptive_thinking(resolved_model):
                # Opus 4.7/4.8 / Fable 5 / Mythos 5 / Haiku 4.5 için manual yok — adaptive kullan.
                # Effort seviyesi modelin kendi adaptive davranışıyla absorbe edilir.
                payload["thinking"] = {"type": "adaptive"}
                if effective_effort and not _supports_manual_thinking(resolved_model):
                    logger.info(
                        "AnthropicProvider: %s effort seviyesini desteklemiyor "
                        "(adaptive thinking aktif, effort=%s bilgi amaçlı kaydedildi)",
                        resolved_model, effective_effort,
                    )
            else:
                logger.info(
                    "AnthropicProvider: %s thinking desteklemiyor — atlanıyor",
                    resolved_model,
                )

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
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

                if resp.is_success:
                    break

                if resp.status_code not in _RETRYABLE_STATUS:
                    logger.error(
                        "AnthropicProvider hata: status=%s body=%.200s",
                        resp.status_code,
                        resp.text,
                    )
                    resp.raise_for_status()

                logger.warning(
                    "AnthropicProvider geçici hata (deneme %d/%d): status=%d",
                    attempt + 1, _MAX_RETRIES, resp.status_code,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    resp.raise_for_status()

            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning(
                    "AnthropicProvider timeout (deneme %d/%d): %s",
                    attempt + 1, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
            except httpx.ConnectError as exc:
                last_exc = exc
                logger.warning(
                    "AnthropicProvider bağlantı hatası (deneme %d/%d): %s",
                    attempt + 1, _MAX_RETRIES, exc,
                )
                if attempt < _MAX_RETRIES - 1:
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise

        if last_exc is not None:
            raise last_exc

        data = resp.json()
        # Extended thinking aktifken content içinde `thinking` blokları da gelir;
        # önce "text" tipli bloğu ara, yoksa ilk "text" alanı olan bloğa düş
        # (eski API yanıtları type alanı olmadan geliyordu — backward compat).
        try:
            blocks = data["content"]
            text_block = next(
                (b for b in blocks if b.get("type") == "text"),
                None,
            )
            if text_block is None:
                text_block = next(b for b in blocks if "text" in b)
            text = text_block["text"]
        except (KeyError, StopIteration, TypeError) as exc:
            raise RuntimeError(f"Anthropic yanıt parse hatası: {data}") from exc

        usage = data.get("usage", {})
        return CompletionResult(
            text=text,
            model_id=resolved_model,
            model_name=_MODEL_NAMES.get(resolved_model, resolved_model),
            backend="anthropic",
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
            cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
        )
