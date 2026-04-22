"""Vision ve AI perception aksiyonları — desktop_router.py'den SRP ayrımı (SOLID-v2-6).

Handler'lar:
    vision_query     — Ekran görüntüsü + Claude Vision API ile serbest soru
    check_vision     — Vision API kullanılabilirlik kontrolü
    clear_bbox_cache — Bounding box cache temizleme
    bbox_cache_stats — Bounding box cache istatistikleri
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from .desktop_router import DesktopRequest

logger = logging.getLogger(__name__)


# ── Handler'lar ───────────────────────────────────────────────────────

async def _handle_vision_query(body: DesktopRequest) -> dict:
    if not body.question:
        return {"ok": False, "message": "vision_query aksiyonu için 'question' gerekli."}
    from ..features.desktop import vision_query
    vq_region = tuple(body.region) if body.region else None  # type: ignore[arg-type]
    answer = await vision_query(
        body.question,
        model=body.vision_model,
        region=vq_region,
        use_cache=body.use_cache,
        session_id=body.session_id,
    )
    ok = not answer.startswith("❌")
    cached = "[cache]" if body.use_cache else "[no-cache]"
    logger.info(
        "desktop/vision_query %s: model=%s, soru=%r, region=%s → %s (%d karakter)",
        cached, body.vision_model, body.question[:60], vq_region, "ok" if ok else "hata", len(answer),
    )
    return {"ok": ok, "message": answer, "text": answer}


async def _handle_check_vision(body: DesktopRequest) -> dict:
    """Vision API kullanılabilirliğini kontrol eder — görev başında proaktif çağrı için (DESK-LOGIN-3)."""
    from ..features.desktop import check_vision_status
    status = check_vision_status()
    logger.info("desktop/check_vision: available=%s", status["available"])
    return {"ok": True, **status}


async def _handle_clear_bbox_cache(body: DesktopRequest) -> dict:
    from ..features.desktop import clear_bbox_cache
    count = clear_bbox_cache()
    logger.info("desktop/clear_bbox_cache: %d girdi silindi", count)
    return {"ok": True, "message": f"✅ Bounding box cache temizlendi ({count} girdi silindi)."}


async def _handle_bbox_cache_stats(body: DesktopRequest) -> dict:
    from ..features.desktop import get_bbox_cache_stats
    stats = get_bbox_cache_stats()
    msg = (
        f"Cache istatistikleri:\n"
        f"  Toplam: {stats['total']}\n"
        f"  Aktif (TTL içinde): {stats['active']}\n"
        f"  Süresi dolmuş: {stats['expired']}\n"
        f"  TTL: {stats['ttl_seconds']}s"
    )
    logger.info("desktop/bbox_cache_stats: %s", stats)
    return {"ok": True, "message": msg, "stats": stats}


# ── Export ────────────────────────────────────────────────────────────

HANDLERS: dict[str, Callable[..., Awaitable[dict]]] = {
    "vision_query":     _handle_vision_query,
    "check_vision":     _handle_check_vision,
    "clear_bbox_cache": _handle_clear_bbox_cache,
    "bbox_cache_stats": _handle_bbox_cache_stats,
}

PARAM_EXTRACTORS: dict[str, Callable] = {
    "vision_query": lambda b: {
        "question": (b.question or "")[:80],
        "model": b.vision_model,
        "region": b.region,
        "use_cache": b.use_cache,
    },
}
