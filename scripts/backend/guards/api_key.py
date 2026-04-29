"""Internal API key guard — HTTP endpoint'leri için (SRP).

X-Api-Key header'ı settings.api_key ile karşılaştırır.
api_key boş bırakılırsa guard devre dışı kalır (dev modu).
"""
from __future__ import annotations

import logging
import secrets

from fastapi import Header, HTTPException
from fastapi.security import APIKeyHeader

from ..config import settings

logger = logging.getLogger(__name__)

_scheme = APIKeyHeader(name="X-Api-Key", auto_error=False)


async def require_api_key(x_api_key: str | None = Header(default=None, alias="X-Api-Key")) -> None:
    """FastAPI dependency: settings.api_key tanımlıysa header'ı doğrula."""
    if not settings.api_key:
        if settings.environment == "production":
            raise HTTPException(status_code=500, detail="Sunucu yapılandırma hatası")
        logger.critical("GÜVENLİK UYARISI: api_key tanımlı değil — tüm /agent/* endpoint'leri korumasız!")
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key.get_secret_value()):
        logger.warning("Geçersiz veya eksik X-Api-Key")
        raise HTTPException(status_code=401, detail="Yetkisiz")
