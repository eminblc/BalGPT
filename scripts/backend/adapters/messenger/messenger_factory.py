"""Messenger factory — MESSENGER_TYPE env değerine göre uygun adaptörü döndürür.

OCP-5: _MESSENGERS dict registry — yeni platform = yeni dosya + register_messenger() çağrısı.
llm_factory.py ile aynı pattern.

Singleton instance döndürür; uygulama boyunca tek örnek kullanılır.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...config import settings
from .whatsapp_messenger import WhatsAppMessenger
from .telegram_messenger import TelegramMessenger
from .cli_messenger import CLIMessenger

if TYPE_CHECKING:
    from . import AbstractMessenger

logger = logging.getLogger(__name__)

_instance: AbstractMessenger | None = None

_MESSENGERS: dict[str, type] = {
    "whatsapp": WhatsAppMessenger,
    "telegram": TelegramMessenger,
    "cli":      CLIMessenger,
}


def register_messenger(name: str, cls: type) -> None:
    """Yeni messenger backend'i kaydet (OCP: mevcut kodu değiştirmeden genişletme)."""
    _MESSENGERS[name] = cls


def get_messenger() -> AbstractMessenger:
    """Yapılandırılmış messenger adaptörünü döndür (singleton)."""
    global _instance
    if _instance is None:
        messenger_type = settings.messenger_type.lower()
        cls = _MESSENGERS.get(messenger_type)
        if cls is None:
            if settings.environment == "production":
                raise ValueError(
                    f"Bilinmeyen MESSENGER_TYPE={messenger_type!r}. "
                    "Geçerli değerler: whatsapp, telegram, cli"
                )
            logger.warning(
                "Bilinmeyen MESSENGER_TYPE=%r — varsayılan 'whatsapp' kullanılıyor",
                messenger_type,
            )
            cls = WhatsAppMessenger
        _instance = cls()
        logger.info("Messenger: %s", cls.__name__)
    return _instance


def set_messenger(instance: AbstractMessenger) -> None:
    """Test enjeksiyonu için singleton'ı override et.

    Kullanım (pytest):
        set_messenger(mock_messenger)
        yield
        reset_messenger()

    Production kodunda çağrılmamalı.
    """
    global _instance
    _instance = instance


def reset_messenger() -> None:
    """Test izolasyonu için singleton'ı sıfırla — bir sonraki get_messenger() yeniden oluşturur.

    Production kodunda çağrılmamalı.
    """
    global _instance
    _instance = None
