"""Playwright session yaşam döngüsü — aç, kapat, listele (SRP).

Sorumluluk: Browser/context/page oluşturma, kapama ve session listesi.
"""
from __future__ import annotations

import logging

from ._session_store import BrowserSession, _session_store
from ._paths import _get_storage_state_path

logger = logging.getLogger(__name__)


async def _get_or_create_session(session_id: str, headless: bool = True) -> BrowserSession:
    """Mevcut session'ı döndürür; yoksa yeni Playwright browser açar.

    Diskte kayıtlı storage state varsa context'e yüklenir (FEAT-15).
    Thread-safe: _session_store.lock ile korunur.
    """
    async with _session_store.lock:
        if session_id in _session_store:
            sess = _session_store.get(session_id)
            try:
                _ = sess["page"].url
                return sess
            except Exception:
                logger.warning("browser: session %r geçersiz, yeniden başlatılıyor", session_id)
                await _close_session_internal(session_id)

        from ...config import settings
        max_sess = settings.browser_max_sessions
        active_count = len(_session_store.keys())
        if active_count >= max_sess:
            raise RuntimeError(
                f"Maksimum browser session sayısına ulaşıldı ({max_sess}). "
                f"Mevcut session'lardan birini kapatın (close aksiyonu)."
            )

        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = None
        context = None
        try:
            browser = await pw.chromium.launch(headless=headless)
            storage_path = _get_storage_state_path(session_id)
            context_kwargs: dict = {
                "viewport": {"width": 1280, "height": 800},
                "user_agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
            if storage_path.exists():
                context_kwargs["storage_state"] = str(storage_path)
                logger.info(
                    "browser: kayıtlı storage state yüklendi: %r (%d bytes)",
                    session_id, storage_path.stat().st_size,
                )
            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()
        except Exception:
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
            try:
                await pw.stop()
            except Exception:
                pass
            raise

        sess = BrowserSession(playwright=pw, browser=browser, context=context, page=page)
        _session_store.set(session_id, sess)
        logger.info(
            "browser: yeni session açıldı: %r (headless=%s, saved_state=%s)",
            session_id, headless, _get_storage_state_path(session_id).exists(),
        )
        return sess


async def _close_session_internal(session_id: str) -> None:
    """Lock dışından veya içinden çağrılır — lock almaz."""
    sess = _session_store.pop(session_id)
    if not sess:
        return
    try:
        await sess["browser"].close()
    except Exception as e:
        logger.debug("browser close hata: %s", e)
    try:
        await sess["playwright"].stop()
    except Exception as e:
        logger.debug("playwright stop hata: %s", e)
    logger.info("browser: session kapatıldı: %r", session_id)


async def browser_close(session_id: str = "default") -> tuple[bool, str]:
    """Belirli bir session'ı kapat."""
    async with _session_store.lock:
        if session_id not in _session_store:
            return False, f"❌ Session bulunamadı: {session_id!r}"
        await _close_session_internal(session_id)
    return True, f"✅ Session kapatıldı: {session_id}"


async def browser_close_all() -> tuple[bool, str]:
    """Tüm açık session'ları kapat. FastAPI lifespan shutdown'ında çağrılır."""
    async with _session_store.lock:
        ids = _session_store.keys()
        for sid in ids:
            await _close_session_internal(sid)
    count = len(ids)
    if count:
        logger.info("browser: %d session kapatıldı", count)
    return True, f"✅ {count} session kapatıldı."


async def browser_list_sessions() -> list[dict]:
    """Açık session'ları ve mevcut URL'lerini listele."""
    result = []
    async with _session_store.lock:
        for sid, sess in _session_store.items():
            try:
                url = sess["page"].url
            except Exception:
                url = "(bilinmiyor)"
            saved = _get_storage_state_path(sid).exists()
            result.append({"session_id": sid, "url": url, "saved_state": saved})
    return result


async def lifecycle_shutdown() -> None:
    """Feature registry shutdown hook'u — tüm session'ları kapat."""
    try:
        await browser_close_all()
    except Exception as exc:
        logger.warning("Browser session kapatma hatası: %s", exc)
