"""Telegram messenger adaptörü — Telegram Bot API (webhook modu, httpx).

Polling kullanılmaz; gelen güncellemeler FastAPI webhook endpoint'i üzerinden
alınır (entegrasyon bir sonraki adımda). Bu sınıf yalnızca GÖNDERME işlemlerini
kapsar.

Env değişkenleri (config.py üzerinden okunur):
  TELEGRAM_BOT_TOKEN  — BotFather'dan alınan token (ör. 123456:ABC-DEF...)
  TELEGRAM_CHAT_ID    — Varsayılan hedef chat (tek kullanıcı modunda owner chat_id)
"""
from __future__ import annotations

import logging
import mimetypes
import os

import httpx

from ...config import settings
from ...constants import TG_MAX_LEN

logger = logging.getLogger(__name__)


def _split_text(text: str, limit: int = TG_MAX_LEN) -> list[str]:
    """Metni Telegram karakter limitine böl; satır sınırlarını koru."""
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    while text:
        if len(text) <= limit:
            parts.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    return parts


def _sections_to_text(header: str, sections: list[dict]) -> str:
    """sections listesini Telegram'da okunabilir düz metne dönüştür.

    Çıktı örneği:
        Hangi projeyi seçmek istersiniz?

        *Aktif Projeler*
        • Website Yenileme — tasarım ve geliştirme
        • API Entegrasyonu

        *Bekleyen Projeler*
        • Mobil Uygulama
    """
    lines = [header, ""]
    for section in sections:
        title = section.get("title", "")
        if title:
            lines.append(f"*{title}*")
        for row in section.get("rows", []):
            row_title = row.get("title", "")
            description = row.get("description", "")
            if description:
                lines.append(f"• {row_title} — {description}")
            else:
                lines.append(f"• {row_title}")
        lines.append("")
    return "\n".join(lines).rstrip()


class TelegramMessenger:
    """Telegram Bot API üzerinden mesajlaşma (webhook modu)."""

    supports_interactive_buttons: bool = True  # InlineKeyboard destekler; send_list → düz metin fallback
    supports_media: bool = True

    def __init__(self) -> None:
        self._token = settings.telegram_bot_token.get_secret_value()
        self._base = f"https://api.telegram.org/bot{self._token}"

    async def send_text(self, to: str, text: str) -> None:
        """to: Telegram chat_id."""
        parts = _split_text(text)
        async with httpx.AsyncClient(timeout=15) as client:
            for part in parts:
                res = await client.post(
                    f"{self._base}/sendMessage",
                    json={"chat_id": to, "text": part, "parse_mode": "Markdown"},
                )
                if not res.is_success:
                    logger.error(
                        "Telegram send_text başarısız: to=%s status=%d body=%s",
                        to, res.status_code, res.text[:200],
                    )
                res.raise_for_status()

    async def send_buttons(self, to: str, text: str, buttons: list[dict]) -> None:
        """InlineKeyboard butonu olarak gönder.

        buttons: [{"id": "btn_id", "title": "Başlık"}, ...]
        Her buton ayrı satıra yerleştirilir.
        """
        inline_keyboard = [
            [{"text": b["title"], "callback_data": b["id"]}]
            for b in buttons
        ]
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                f"{self._base}/sendMessage",
                json={
                    "chat_id": to,
                    "text": text,
                    "reply_markup": {"inline_keyboard": inline_keyboard},
                },
            )
            if not res.is_success:
                logger.error(
                    "Telegram send_buttons başarısız: to=%s status=%d body=%s",
                    to, res.status_code, res.text[:200],
                )
            res.raise_for_status()

    async def send_list(self, to: str, text: str, sections: list[dict]) -> None:
        """sections'ı InlineKeyboard butonları olarak gönder.

        Section başlıkları keyboard içinde tam genişlik ayraç satırı olarak
        gösterilir; içerik satırları 2'li gruplara yerleştirilir.
        """
        keyboard: list[list[dict]] = []
        for section in sections:
            section_title = section.get("title", "")
            if section_title:
                keyboard.append([{"text": f"── {section_title} ──", "callback_data": "noop"}])
            rows = section.get("rows", [])
            for i in range(0, len(rows), 2):
                pair = rows[i : i + 2]
                keyboard.append([
                    {"text": r.get("title", ""), "callback_data": r.get("id", "noop")}
                    for r in pair
                ])

        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                f"{self._base}/sendMessage",
                json={
                    "chat_id": to,
                    "text": text or "​",
                    "parse_mode": "Markdown",
                    "reply_markup": {"inline_keyboard": keyboard},
                },
            )
            if not res.is_success:
                logger.warning(
                    "Telegram send_list başarısız, düz metin fallback: status=%d body=%s",
                    res.status_code, res.text[:200],
                )
                formatted = _sections_to_text(text, sections)
                await self.send_text(to, formatted)

    async def send_typing(self, to: str) -> None:
        """Telegram 'yazıyor…' göstergesi — yaklaşık 5 saniye aktif kalır."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(
                    f"{self._base}/sendChatAction",
                    json={"chat_id": to, "action": "typing"},
                )
        except Exception as exc:
            logger.debug("send_typing başarısız (görmezden geliniyor): %s", exc)

    async def set_webhook(self, url: str) -> dict:
        """Telegram webhook URL'sini kaydet.

        Kurulum sırasında veya URL değiştiğinde bir kez çağrılır.
        url: HTTPS endpoint (ör. https://yourdomain.com/telegram/webhook)
        """
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                f"{self._base}/setWebhook",
                json={"url": url, "allowed_updates": ["message", "callback_query"]},
            )
            res.raise_for_status()
            result = res.json()
            logger.info("Telegram webhook ayarlandı: %s → %s", url, result)
            return result

    async def send_image(self, to: str, source: str, caption: str = "") -> None:
        """Görsel gönder. source: yerel yol veya https:// URL."""
        async with httpx.AsyncClient(timeout=60) as client:
            if source.startswith("http"):
                res = await client.post(
                    f"{self._base}/sendPhoto",
                    json={"chat_id": to, "photo": source, "caption": caption},
                )
            else:
                mime_type, _ = mimetypes.guess_type(source)
                filename = os.path.basename(source)
                with open(source, "rb") as fh:
                    res = await client.post(
                        f"{self._base}/sendPhoto",
                        data={"chat_id": to, "caption": caption},
                        files={"photo": (filename, fh, mime_type or "image/jpeg")},
                    )
            if not res.is_success:
                logger.error("Telegram send_image başarısız: to=%s status=%d body=%s",
                             to, res.status_code, res.text[:200])
            res.raise_for_status()

    async def send_video(self, to: str, source: str, caption: str = "") -> None:
        """Video gönder. source: yerel yol veya https:// URL."""
        async with httpx.AsyncClient(timeout=60) as client:
            if source.startswith("http"):
                res = await client.post(
                    f"{self._base}/sendVideo",
                    json={"chat_id": to, "video": source, "caption": caption},
                )
            else:
                mime_type, _ = mimetypes.guess_type(source)
                filename = os.path.basename(source)
                with open(source, "rb") as fh:
                    res = await client.post(
                        f"{self._base}/sendVideo",
                        data={"chat_id": to, "caption": caption},
                        files={"video": (filename, fh, mime_type or "video/mp4")},
                    )
            if not res.is_success:
                logger.error("Telegram send_video başarısız: to=%s status=%d body=%s",
                             to, res.status_code, res.text[:200])
            res.raise_for_status()

    async def send_document(self, to: str, source: str, filename: str, caption: str = "") -> None:
        """Belge gönder. source: yerel yol veya https:// URL."""
        async with httpx.AsyncClient(timeout=60) as client:
            if source.startswith("http"):
                res = await client.post(
                    f"{self._base}/sendDocument",
                    json={"chat_id": to, "document": source, "caption": caption},
                )
            else:
                mime_type, _ = mimetypes.guess_type(source)
                with open(source, "rb") as fh:
                    res = await client.post(
                        f"{self._base}/sendDocument",
                        data={"chat_id": to, "caption": caption},
                        files={"document": (filename, fh, mime_type or "application/octet-stream")},
                    )
            if not res.is_success:
                logger.error("Telegram send_document başarısız: to=%s status=%d body=%s",
                             to, res.status_code, res.text[:200])
            res.raise_for_status()

    async def delete_webhook(self) -> dict:
        """Webhook'u kaldır (polling moduna geçiş veya temizlik için)."""
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(f"{self._base}/deleteWebhook")
            res.raise_for_status()
            return res.json()
