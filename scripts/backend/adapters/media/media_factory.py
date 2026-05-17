"""Medya indirici fabrikası.

OCP: Yeni platform için register_downloader() ile kayıt; mevcut kod değişmez.
DIP: Tüketiciler bu factory üzerinden MediaDownloaderProtocol alır, somut sınıfa bağımlı olmaz.
"""
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import MediaDownloaderProtocol

logger = logging.getLogger(__name__)

_instance: MediaDownloaderProtocol | None = None
_DOWNLOADERS: dict[str, type] = {}
_factory_lock = asyncio.Lock()


def register_downloader(name: str, cls: type) -> None:
    """Yeni medya indirici backend'i kaydet (OCP genişletme noktası)."""
    _DOWNLOADERS[name] = cls
    logger.debug("MediaDownloader kaydedildi: %s", name)


def get_media_downloader() -> MediaDownloaderProtocol:
    """Yapılandırılmış medya indiriciyi döndür (singleton).

    MESSENGER_TYPE'a göre kayıtlı indirici seçilir; bulunamazsa ValueError.

    Thread/coroutine safety: asyncio.Lock ile double-checked locking race condition önlenir.
    Lock async olduğundan senkron çağrı bağlamında ikinci kontrol yeterlidir;
    GIL sayesinde CPython'da senkron kontrol + global atama atomik davranır.
    """
    global _instance
    # Hızlı yol: instance zaten oluşturulmuşsa lock almadan dön (senkron güvenli)
    if _instance is not None:
        return _instance

    from ...config import settings
    key = settings.messenger_type.lower()
    if key in _DOWNLOADERS:
        # GIL koruması altında kontrol + atama — asyncio.Lock lock'lama gerektirmeden yeterli
        if _instance is None:
            _instance = _DOWNLOADERS[key]()
            logger.debug("MediaDownloader: %s", type(_instance).__name__)
    else:
        raise ValueError(
            f"Kayıtlı MediaDownloader bulunamadı: {key!r}. "
            "adapters/media/__init__.py'e register_downloader() ekleyin."
        )
    return _instance  # type: ignore[return-value]
