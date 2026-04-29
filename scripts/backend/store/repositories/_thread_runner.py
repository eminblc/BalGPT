"""asyncio.to_thread wrapper with structured error logging (SOLID-ERR-1).

Repository'lerin asyncio.to_thread() çağrıları bu yardımcıyı kullanır.
Hata gerçekleştiğinde fonksiyon adıyla birlikte loglanır, exception yine fırlatılır —
çağıran katman (feature) uygun şekilde handle eder.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


async def run_in_thread(fn: Callable[..., _T], *args: Any) -> _T:
    """Senkron fonksiyonu asyncio thread pool'da çalıştırır.

    asyncio.to_thread'den farkı: exception oluşursa fonksiyon adı ve hata
    logger.error ile kaydedilir, ardından exception yeniden fırlatılır.
    Bu sayede repository hataları kaynakta iz bırakır.
    """
    try:
        return await asyncio.to_thread(fn, *args)
    except Exception as exc:
        logger.error("Repository thread error [%s]: %s", fn.__name__, exc)
        raise
