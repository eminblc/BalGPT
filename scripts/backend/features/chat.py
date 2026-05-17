"""Sohbet özelliği — Bridge'e mesaj iletir ve yanıt döndürür (SRP).

Bu modül yalnızca Bridge iletişimini yönetir. Session ve routing
whatsapp_router.py'e aittir.
"""
from __future__ import annotations

import logging
import os

import httpx

from ..config import get_settings
from ..i18n import t

logger = logging.getLogger(__name__)

# IMP-FEAT-6: Bridge API hata prefix'i sabit olarak tanımlandı — kırılgan string literal'dan kaçın
_BRIDGE_API_ERROR_PREFIX = "API Error:"

# IMP-FEAT-17: Bridge HTTP timeout configurable; settings'te BRIDGE_HTTP_TIMEOUT varsa onu kullan,
# yoksa env'den oku, son fallback 90 saniye (WhatsApp için daha makul)
def _get_bridge_timeout() -> float:
    """Bridge HTTP timeout'unu belirle (saniye)."""
    cfg = get_settings()
    # settings'te özel bir bridge_http_timeout alanı varsa onu kullan
    if hasattr(cfg, "bridge_http_timeout"):
        return float(cfg.bridge_http_timeout)
    # Env'den oku; yoksa 90 saniye (300s WhatsApp için çok uzun)
    return float(os.environ.get("BRIDGE_HTTP_TIMEOUT", "90"))


async def send_to_bridge(session_id: str, message: str, init_prompt: str = "", lang: str = "tr") -> str:
    """Bridge'e mesaj gönder, metin yanıt döndür."""
    try:
        timeout = _get_bridge_timeout()
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                f"{get_settings().claude_bridge_url}/query",
                headers={"X-Api-Key": get_settings().api_key.get_secret_value()},
                json={"session_id": session_id, "message": message, "init_prompt": init_prompt},
            )
            r.raise_for_status()
            data = r.json()
            # IMP-FEAT-6: Önce dict üzerinden hata kontrolü; prefix karşılaştırması sabit üzerinden
            answer = data.get("answer", "")
            if data.get("error") or answer.startswith(_BRIDGE_API_ERROR_PREFIX):
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
