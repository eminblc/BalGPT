"""Sohbet özelliği — Bridge'e mesaj iletir ve yanıt döndürür (SRP).

Bu modül yalnızca Bridge iletişimini yönetir. Session ve routing
whatsapp_router.py'e aittir.
"""
from __future__ import annotations

import logging

import httpx

from ..config import get_settings
from ..i18n import t

logger = logging.getLogger(__name__)


async def send_to_bridge(session_id: str, message: str, init_prompt: str = "", lang: str = "tr") -> str:
    """Bridge'e mesaj gönder, metin yanıt döndür."""
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            r = await client.post(
                f"{get_settings().claude_bridge_url}/query",
                headers={"X-Api-Key": get_settings().api_key.get_secret_value()},
                json={"session_id": session_id, "message": message, "init_prompt": init_prompt},
            )
            r.raise_for_status()
            answer = r.json().get("answer", "")
            # CLI'den dönen ham API hata stringini kullanıcıya iletme
            if answer.startswith("API Error:"):
                logger.error("Claude CLI API hatası (session: %s): %s", session_id, answer[:200])
                return t("chat.bridge_api_error", lang)
            return answer
    except httpx.TimeoutException:
        logger.error("Bridge timeout (session: %s)", session_id)
        return t("bridge.timeout", lang)
    except Exception as e:
        logger.error("Bridge hatası: %s", e)
        return t("bridge.unavailable", lang)


async def reset_bridge_session(session_id: str) -> bool:
    """Bridge oturumunu sıfırla. Başarılıysa True, hata olursa False döner."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{get_settings().claude_bridge_url}/reset",
                headers={"X-Api-Key": get_settings().api_key.get_secret_value()},
                json={"session_id": session_id},
            )
            r.raise_for_status()
        return True
    except Exception as e:
        logger.error("Bridge session sıfırlama başarısız (session=%s): %s", session_id, e)
        return False
