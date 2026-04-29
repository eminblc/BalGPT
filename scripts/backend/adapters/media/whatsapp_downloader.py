"""WhatsApp Media API üzerinden dosya indiren somut implementasyon."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class WhatsAppMediaDownloader:
    """MediaDownloaderProtocol — WhatsApp Cloud API implementasyonu."""

    async def download(self, media_id: str) -> tuple[bytes, str]:
        """WhatsApp media_id'sini indir; (dosya_bytes, mime_type) döndür."""
        from ...whatsapp.cloud_api import download_media
        return await download_media(media_id)
