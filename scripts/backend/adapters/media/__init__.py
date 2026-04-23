"""Medya indirme soyutlama katmanı.

ISP uyumu: yalnızca download() metodunu içeren minimal Protocol.
DIP uyumu: feature katmanı somut WhatsApp implementasyonuna değil bu Protocol'e bağımlıdır.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MediaDownloaderProtocol(Protocol):
    """Medya indirme sözleşmesi."""

    async def download(self, media_id: str) -> tuple[bytes, str]:
        """media_id'yi indir; (içerik_bytes, mime_type) döndür."""
        ...


from .whatsapp_downloader import WhatsAppMediaDownloader  # noqa: E402
from .media_factory import get_media_downloader, register_downloader  # noqa: E402

__all__ = [
    "MediaDownloaderProtocol",
    "WhatsAppMediaDownloader",
    "get_media_downloader",
    "register_downloader",
]
