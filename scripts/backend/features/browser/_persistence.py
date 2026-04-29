"""Disk kalıcılığı aksiyonları — session kaydet, sil, listele, bilgi al (SRP, FEAT-15).

Sorumluluk: Playwright storage state (cookies + localStorage) dosya sisteminde yönetmek.
"""
from __future__ import annotations

import logging

from ._session_store import _session_store
from ._paths import _get_storage_state_path, _resolve_sessions_dir

logger = logging.getLogger(__name__)


async def browser_save_session(session_id: str = "default") -> tuple[bool, str]:
    """Mevcut session'ın cookies ve localStorage'ını diske kaydet."""
    async with _session_store.lock:
        sess = _session_store.get(session_id)
        if not sess:
            return False, f"❌ Aktif session bulunamadı: {session_id!r}. Önce oturum açın."
        context = sess["context"]
        storage_path = _get_storage_state_path(session_id)
        try:
            await context.storage_state(path=str(storage_path))
            size = storage_path.stat().st_size
            logger.info(
                "browser/save_session: session=%r → %s (%d bytes)",
                session_id, storage_path, size,
            )
            return True, f"✅ Oturum kaydedildi: {session_id!r} ({size} bytes)"
        except Exception as e:
            logger.warning("browser/save_session hata: session=%r, %s", session_id, e)
            return False, f"❌ Oturum kaydedilemedi: {e}"


async def browser_delete_saved_session(session_id: str = "default") -> tuple[bool, str]:
    """Diskteki kayıtlı storage state'ini sil. Bellekteki aktif session'ı kapatmaz."""
    storage_path = _get_storage_state_path(session_id)
    if not storage_path.exists():
        return False, f"❌ Kayıtlı oturum bulunamadı: {session_id!r}"
    try:
        storage_path.unlink()
        logger.info("browser/delete_saved_session: session=%r silindi", session_id)
        return True, f"✅ Kayıtlı oturum silindi: {session_id!r}"
    except OSError as e:
        logger.warning("browser/delete_saved_session hata: %s", e)
        return False, f"❌ Silinemedi: {e}"


async def browser_list_saved_sessions() -> list[dict]:
    """Diskteki kayıtlı session dosyalarını listele. Bellekteki aktif session'larla bağımsız."""
    sessions_dir = _resolve_sessions_dir()
    if not sessions_dir.exists():
        return []
    result = []
    async with _session_store.lock:
        active_ids = set(_session_store.keys())
    for f in sorted(sessions_dir.glob("*.json")):
        sid = f.stem
        stat = f.stat()
        result.append({
            "session_id": sid,
            "size_bytes": stat.st_size,
            "active": sid in active_ids,
        })
    return result


async def browser_session_info(session_id: str = "default") -> dict:
    """Bir session hakkında detaylı bilgi döndür."""
    storage_path = _get_storage_state_path(session_id)
    saved = storage_path.exists()
    saved_size = storage_path.stat().st_size if saved else 0

    async with _session_store.lock:
        sess = _session_store.get(session_id)

    if not sess:
        return {
            "session_id": session_id,
            "active": False,
            "url": None,
            "title": None,
            "saved_state": saved,
            "saved_size_bytes": saved_size,
        }

    page = sess["page"]
    try:
        url = page.url
        title = await page.title()
    except Exception:
        url = "(bilinmiyor)"
        title = "(bilinmiyor)"

    return {
        "session_id": session_id,
        "active": True,
        "url": url,
        "title": title,
        "saved_state": saved,
        "saved_size_bytes": saved_size,
    }
