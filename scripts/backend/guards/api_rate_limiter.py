"""SEC-H3: /agent/* endpoint'leri için IP tabanlı rate limiter (SRP).

WhatsApp rate limiter (number bazlı) ile aynı sliding window algoritması;
burada client IP kullanılır — Bridge veya N8N'in agresif çağrılarını sınırlar.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException, Request

from .rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Dakikada 60 istek — Bridge normal kullanımı için yeterli
_api_limiter = RateLimiter(max_per_minute=60)


async def require_api_rate_limit(request: Request) -> None:
    """FastAPI dependency: client IP başına 60 istek/dakika sınırı."""
    if request.client:
        client_ip = request.client.host
    else:
        forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        real_ip = request.headers.get("X-Real-IP", "").strip()
        client_ip = forwarded_for or real_ip or "anon"
        if client_ip == "anon":
            logger.warning(
                "API rate limit: client IP belirlenemedi — 'anon' olarak işleniyor, path=%s",
                request.url.path,
            )
    if not _api_limiter.check(client_ip):
        logger.warning("API rate limit aşıldı: ip=%s path=%s", client_ip, request.url.path)
        raise HTTPException(status_code=429, detail="Çok fazla istek — lütfen bekleyin")
