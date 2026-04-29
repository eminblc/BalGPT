"""WhatsApp messenger adaptörü — cloud_api.py'yi AbstractMessenger üzerine sarar.

cloud_api.py'ye dokunulmaz; bu katman yalnızca onu çağırır.
"""
from __future__ import annotations

import mimetypes

from ...whatsapp import cloud_api

_DEFAULT_LIST_LABEL = "Seçenekler"


class WhatsAppMessenger:
    """Meta Cloud API üzerinden WhatsApp mesajlaşması."""

    supports_interactive_buttons: bool = True
    supports_media: bool = True

    async def send_text(self, to: str, text: str) -> None:
        await cloud_api.send_text(to, text)

    async def send_buttons(self, to: str, text: str, buttons: list[dict]) -> None:
        """buttons: [{"id": "btn_id", "title": "Başlık"}, ...] — max 3 buton."""
        await cloud_api.send_buttons(to, text, buttons)

    async def send_typing(self, to: str) -> None:
        """WhatsApp Cloud API'de native typing action yok — no-op."""

    async def send_list(self, to: str, text: str, sections: list[dict]) -> None:
        """WhatsApp açılır liste menüsü olarak gönder.

        sections: [{"title": "Bölüm", "rows": [{"id": "...", "title": "...", "description": "..."}]}]
        Buton etiketi sabit "Seçenekler" olarak kullanılır; platform sözleşmesinde yer almaz.
        """
        await cloud_api.send_list(to, text, _DEFAULT_LIST_LABEL, sections)

    async def send_image(self, to: str, source: str, caption: str = "") -> None:
        """Görsel gönder. source: yerel yol veya https:// URL."""
        if source.startswith("http"):
            await cloud_api.send_image(to, source, caption)
        else:
            mime_type, _ = mimetypes.guess_type(source)
            media_id = await cloud_api.upload_media(source, mime_type or "image/jpeg")
            await cloud_api.send_image_by_id(to, media_id, caption)

    async def send_video(self, to: str, source: str, caption: str = "") -> None:
        """Video gönder. source: yerel yol (Meta video URL desteklemez)."""
        mime_type, _ = mimetypes.guess_type(source)
        media_id = await cloud_api.upload_media(source, mime_type or "video/mp4")
        await cloud_api.send_video_by_id(to, media_id, caption)

    async def send_document(self, to: str, source: str, filename: str, caption: str = "") -> None:
        """Belge gönder. source: yerel yol."""
        mime_type, _ = mimetypes.guess_type(source)
        media_id = await cloud_api.upload_media(source, mime_type or "application/octet-stream")
        await cloud_api.send_document_by_id(to, media_id, filename, caption)
