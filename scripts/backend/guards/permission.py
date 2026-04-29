"""Yetki kontrolü — komut → izin seviyesi eşlemesi (SRP).

Tek kullanıcı sistemi: settings.owner_id dışındaki kimlikler OWNER komutlarına erişemez.

İzin seviyesi SSOT: Her komut kendi sınıfında `perm` attribute'u taşır.
required_perm() önce registry'den okur; kayıtlı değilse None döner.
"""
from __future__ import annotations

import logging
from enum import Enum

import pyotp

from ..config import settings

logger = logging.getLogger(__name__)


class Perm(str, Enum):
    PUBLIC          = "public"       # Herkese açık (şu an sadece owner var, ilerisi için)
    OWNER           = "owner"        # Sadece owner
    OWNER_TOTP      = "owner_totp"   # Owner + TOTP doğrulaması


class PermissionManager:
    """Komut yetki kontrolü ve TOTP doğrulaması."""

    def is_owner(self, number: str) -> bool:
        # owner_id messenger tipine göre doğru kimliği döndürür (WhatsApp: telefon, Telegram: chat_id)
        owner = settings.owner_id.lstrip("+")
        return number.lstrip("+") == owner

    def required_perm(self, cmd: str) -> Perm | None:
        """Komut için gereken izin seviyesini döndürür.

        Komut sınıfındaki `perm` attribute'undan okur (SSOT).
        Kayıtlı komut yoksa None döner.
        """
        # Geç import — guards/__init__.py yüklenirken commands henüz hazır olmayabilir
        from .commands.registry import registry
        command = registry.get(cmd)
        if command is not None:
            return getattr(command, "perm", None)
        return None

    def verify_totp(self, code: str) -> bool:
        if not settings.totp_secret:
            logger.warning("TOTP secret tanımlı değil")
            return False
        if not code or len(code) < 6 or not code.isdigit():
            return False
        secret = settings.totp_secret.get_secret_value().strip()
        try:
            secret.encode("ascii")
        except UnicodeEncodeError:
            logger.error("TOTP secret ASCII olmayan karakter içeriyor — .env dosyasını kontrol et")
            return False
        totp = pyotp.TOTP(secret)
        result = totp.verify(code, valid_window=1)
        if not result:
            import time as _time
            now = int(_time.time())
            logger.warning(
                "TOTP verify failed: code_len=%d secret_len=%d ts=%d window0=%s window-1=%s window+1=%s",
                len(code), len(secret), now,
                totp.at(now), totp.at(now - 30), totp.at(now + 30),
            )
        return result

