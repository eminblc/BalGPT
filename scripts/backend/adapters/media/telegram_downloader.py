"""Telegram Bot API üzerinden dosya indiren somut implementasyon."""
from __future__ import annotations

import logging
import mimetypes

import httpx

logger = logging.getLogger(__name__)


class TelegramMediaDownloader:
    """MediaDownloaderProtocol — Telegram Bot API implementasyonu.

    Telegram file_id → getFile → dosya indir; (bytes, mime_type) döndür.
    """

    async def download(self, file_id: str) -> tuple[bytes, str]:
        """Telegram file_id'sini indir; (dosya_bytes, mime_type) döndür."""
        from ...config import settings

        token = settings.telegram_bot_token.get_secret_value()
        base = f"https://api.telegram.org/bot{token}"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{base}/getFile", params={"file_id": file_id})
            resp.raise_for_status()
            data = resp.json()

        if not data.get("ok"):
            raise ValueError(f"Telegram getFile başarısız: {data.get('description', data)}")

        file_path: str = data["result"]["file_path"]
        logger.debug("TelegramMediaDownloader: file_id=%s → path=%s", file_id, file_path)

        async with httpx.AsyncClient(timeout=60) as client:
            dl = await client.get(
                f"https://api.telegram.org/file/bot{token}/{file_path}"
            )
            dl.raise_for_status()
            content = dl.content

        mime, _ = mimetypes.guess_type(file_path)
        return content, mime or "application/octet-stream"
