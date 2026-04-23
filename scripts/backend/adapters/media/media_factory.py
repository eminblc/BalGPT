"""Medya indirici fabrikası.

OCP: Yeni platform için register_downloader() ile kayıt; mevcut kod değişmez.
DIP: Tüketiciler bu factory üzerinden MediaDownloaderProtocol alır, somut sınıfa bağımlı olmaz.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import MediaDownloaderProtocol

logger = logging.getLogger(__name__)

_instance: MediaDownloaderProtocol | None = None


def register_downloader(name: str, cls: type) -> None:
    """Yeni medya indirici backend'i kaydet (OCP genişletme noktası)."""
    _DOWNLOADERS[name] = cls
    logger.debug("MediaDownloader kaydedildi: %s", name)


def get_media_downloader() -> MediaDownloaderProtocol:
    """Yapılandırılmış medya indiriciyi döndür (singleton)."""
    global _instance
    if _instance is None:
        from .whatsapp_downloader import WhatsAppMediaDownloader
        _instance = WhatsAppMediaDownloader()
        logger.debug("MediaDownloader: %s", type(_instance).__name__)
    return _instance


_DOWNLOADERS: dict[str, type] = {}
