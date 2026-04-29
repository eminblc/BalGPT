"""Medya indirme ve yerel depolama (SRP).

WhatsApp'tan gelen görseller, sesler, videolar ve belgeler indirilerek
data/media/YYYY-MM/ altına kaydedilir. Bridge'e dosya yolu bildirilir.

Hiçbir medya silinmez — kalıcı arşiv.
"""
from __future__ import annotations

import logging
import mimetypes
import time
from pathlib import Path

from ..adapters.media import get_media_downloader

logger = logging.getLogger(__name__)

_MIME_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png":  ".png",
    "image/webp": ".webp",
    "audio/ogg":  ".ogg",
    "audio/mpeg": ".mp3",
    "audio/mp4":  ".m4a",
    "video/mp4":  ".mp4",
    "application/pdf": ".pdf",
}


def _media_root() -> Path:
    base = Path(__file__).parent.parent.parent.parent  # 99-root/
    return base / "data" / "media"


def _monthly_dir() -> Path:
    month = time.strftime("%Y-%m")
    d = _media_root() / month
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_media(media_id: str, mime_type: str) -> Path:
    """WhatsApp medyasını indir, yerel diske kaydet. Yolu döndür."""
    ext = _MIME_EXT.get(mime_type) or mimetypes.guess_extension(mime_type) or ".bin"
    dest = _monthly_dir() / f"{media_id}{ext}"

    if dest.exists():
        logger.debug("Medya zaten var: %s", dest)
        return dest

    logger.info("Medya indiriliyor: media_id=%s mime=%s", media_id, mime_type)
    content, _ = await get_media_downloader().download(media_id)
    dest.write_bytes(content)
    logger.info("Medya kaydedildi: %s (%d bytes)", dest, len(content))
    return dest


async def handle_image(sender: str, msg: dict, session: dict) -> tuple[str, str, str | None]:
    """Gelen görseli kaydet; Bridge için açıklama döndür."""
    image = msg.get("image", {})
    media_id  = image.get("id", "")
    mime_type = image.get("mime_type", "image/jpeg")
    caption   = image.get("caption", "")

    path: Path | None = None
    try:
        path = await save_media(media_id, mime_type)
        desc = f"[Kullanıcı görsel gönderdi. Yerel yol: {path}]"
        if caption:
            # PI-FIX-1: caption üçüncü taraf içerik içerebilir — [BELGE] bloğuyla izole et
            desc += f"\n[BELGE]\n{caption[:500]}\n[/BELGE]"
        logger.info("handle_image OK: sender=%s path=%s", sender, path)
    except Exception as exc:
        logger.error("handle_image hata: %s", exc)
        desc = "[Kullanıcı görsel gönderdi fakat indirilemedi.]"

    return desc, media_id, str(path) if path is not None else None


async def handle_audio(sender: str, msg: dict, session: dict) -> tuple[str, str, str | None]:
    """Gelen sesi kaydet; Bridge için açıklama döndür."""
    audio = msg.get("audio", {})
    media_id  = audio.get("id", "")
    mime_type = audio.get("mime_type", "audio/ogg")

    try:
        path = await save_media(media_id, mime_type)
        desc = f"[Kullanıcı ses mesajı gönderdi. Yerel yol: {path}]"
        logger.info("handle_audio OK: sender=%s path=%s", sender, path)
        return desc, media_id, str(path)
    except Exception as exc:
        logger.error("handle_audio hata: %s", exc)
        return "[Kullanıcı ses mesajı gönderdi fakat kaydedilemedi.]", media_id, None


async def handle_video(sender: str, msg: dict, session: dict) -> tuple[str, str, str | None]:
    """Gelen videoyu kaydet; Bridge için açıklama döndür."""
    video = msg.get("video", {})
    media_id  = video.get("id", "")
    mime_type = video.get("mime_type", "video/mp4")
    caption   = video.get("caption", "")

    try:
        path = await save_media(media_id, mime_type)
        desc = f"[Kullanıcı video gönderdi. Yerel yol: {path}]"
        if caption:
            # PI-FIX-1: caption üçüncü taraf içerik içerebilir — [BELGE] bloğuyla izole et
            desc += f"\n[BELGE]\n{caption[:500]}\n[/BELGE]"
        logger.info("handle_video OK: sender=%s path=%s", sender, path)
        return desc, media_id, str(path)
    except Exception as exc:
        logger.error("handle_video hata: %s", exc)
        return "[Kullanıcı video gönderdi fakat kaydedilemedi.]", media_id, None


def handle_location(msg: dict) -> str:
    """Konum mesajını metne çevir."""
    loc  = msg.get("location", {})
    lat  = loc.get("latitude", "?")
    lng  = loc.get("longitude", "?")
    name = loc.get("name", "")
    addr = loc.get("address", "")
    desc = f"[Kullanıcı konum paylaştı: lat={lat} lng={lng} | Google Maps: https://maps.google.com/?q={lat},{lng}]"
    if name or addr:
        # PI-FIX-2: name/addr üçüncü taraf veri (Google Maps, WA Business) — [BELGE] izolasyonu
        belge_parts = []
        if name:
            belge_parts.append(f"Ad: {name[:200]}")
        if addr:
            belge_parts.append(f"Adres: {addr[:300]}")
        desc += f"\n[BELGE]\n" + "\n".join(belge_parts) + "\n[/BELGE]"
    return desc


def handle_sticker(msg: dict) -> str:
    sticker = msg.get("sticker", {})
    media_id = sticker.get("id", "")
    return f"[Kullanıcı sticker gönderdi (media_id={media_id})]"


def handle_reaction(msg: dict) -> str:
    reaction = msg.get("reaction", {})
    emoji    = reaction.get("emoji", "")
    msg_id   = reaction.get("message_id", "")
    return f"[Kullanıcı '{emoji}' tepkisi verdi (mesaj_id={msg_id})]"
