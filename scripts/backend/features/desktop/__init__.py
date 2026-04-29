"""
Desktop otomasyon modülü — genel amaçlı facade.

Sorumluluk ayrımı (REFAC-4 / D1):
    desktop_common.py   — paylaşılan yardımcılar (_detect_display, _env, _xdotool*, _wmctrl)
    desktop_capture.py  — ekran görüntüsü ve OCR
    desktop_input.py    — klavye / fare girdisi (xdotool_*)
    desktop_vision.py   — Vision API sorgusu + cache (_BboxCache)
    desktop_atspi.py    — AT-SPI erişilebilirlik ağacı
    desktop_system.py   — sistem operasyonları (open_path, unlock_screen, sudo_exec,
                          run_installer, get_windows, focus_window)

Bu dosya geriye dönük uyumluluk için tüm public fonksiyonları re-export eder.

Kullanım:
    from backend.features.desktop import (
        open_path, run_installer, capture_screen, ocr_screen,
        xdotool_type, xdotool_key, xdotool_click, xdotool_move, xdotool_scroll,
        vision_query, get_windows, focus_window,
    )

Gereksinimler (sistem paketleri):
    sudo apt install scrot tesseract-ocr tesseract-ocr-tur xdg-utils xdotool wmctrl
    sudo apt install wine  # .exe dosyaları için (isteğe bağlı)

DISPLAY ayarı:
    X11 oturumu için DISPLAY=:0 gerekir.
    SSH üzerinden çalışıyorsan: DISPLAY=:0 ayarlı olmalı.
    Headless/Wayland: scrot ve xdotool çalışmaz — Xvfb gerekir.
"""
from __future__ import annotations

import logging
from typing import Optional

from .desktop_common import _detect_display

# ── Private imports (thin wrapper'lar bu adları kullanır) ─────────────
from .desktop_capture import (
    capture_screen as _capture_screen,
    capture_screen_base64_fast as _capture_screen_base64_fast,
    capture_all_monitors as _capture_all_monitors,
    list_monitors as _list_monitors,
    ocr_screen as _ocr_screen,
    run_tesseract_on_file as _run_tesseract_on_file,
)
from .desktop_input import (
    xdotool_click as _xdotool_click,
    xdotool_key as _xdotool_key,
    xdotool_move as _xdotool_move,
    xdotool_scroll as _xdotool_scroll,
    xdotool_type as _xdotool_type,
)
from .desktop_vision import (
    _bbox_cache_key,  # private yardımcı — doğrudan re-export
    check_vision_status as _check_vision_status,
    clear_bbox_cache as _clear_bbox_cache,
    get_bbox_cache_stats as _get_bbox_cache_stats,
    is_vision_available as _is_vision_available,
    vision_query as _vision_query,
)
from .desktop_atspi import (
    atspi_activate_element as _atspi_activate_element,
    atspi_find_element as _atspi_find_element,
    atspi_get_desktop_tree as _atspi_get_desktop_tree,
)
from .desktop_popup import (
    start_watch_popup as _start_watch_popup,
    stop_watch_popup as _stop_watch_popup,
    list_watch_popups as _list_watch_popups,
)
from .desktop_system import (
    open_path,
    unlock_screen,
    sudo_exec,
    run_installer,
    get_windows,
    focus_window,
)
from .desktop_common import is_screen_locked
from .desktop_recording import (
    record_screen,
    record_all_monitors,
    check_size_mb,
)

__all__ = [
    # Capture
    "capture_screen",
    "capture_screen_base64_fast",
    "capture_all_monitors",
    "list_monitors",
    "ocr_screen",
    "run_tesseract_on_file",
    # Input
    "xdotool_type",
    "xdotool_key",
    "xdotool_click",
    "xdotool_move",
    "xdotool_scroll",
    # Vision
    "vision_query",
    "is_vision_available",
    "check_vision_status",
    "clear_bbox_cache",
    "get_bbox_cache_stats",
    # AT-SPI
    "atspi_get_desktop_tree",
    "atspi_find_element",
    "atspi_activate_element",
    # System ops (desktop_system.py)
    "open_path",
    "unlock_screen",
    "sudo_exec",
    "run_installer",
    "get_windows",
    "focus_window",
    # Popup yönetimi (DESK-OPT-8)
    "start_watch_popup",
    "stop_watch_popup",
    "list_watch_popups",
    # Common helpers re-exported for external use
    "is_screen_locked",
    # Recording
    "record_screen",
    "record_all_monitors",
    "check_size_mb",
]

logger = logging.getLogger(__name__)


# ── Thin Wrappers — Capture ───────────────────────────────────────────
# Her wrapper: DEBUG log girişi + Exception yakalama + ERROR log + güvenli fallback (ENC-V3)

async def capture_screen(
    output_path: Optional[str] = None,
    region: Optional[tuple[int, int, int, int]] = None,
) -> Optional[Path]:
    """Ekran görüntüsü al. Başarısızsa None döner."""
    logger.debug("desktop.capture_screen: output_path=%s region=%s", output_path, region)
    try:
        return await _capture_screen(output_path=output_path, region=region)
    except Exception as exc:
        logger.error("capture_screen hatası: %s", exc, exc_info=True)
        return None


async def capture_screen_base64_fast(
    region: Optional[tuple[int, int, int, int]] = None,
) -> Optional[str]:
    """Ekran görüntüsünü Base64 olarak döndür (disk I/O yok). Başarısızsa None döner."""
    logger.debug("desktop.capture_screen_base64_fast: region=%s", region)
    try:
        return await _capture_screen_base64_fast(region=region)
    except Exception as exc:
        logger.error("capture_screen_base64_fast hatası: %s", exc, exc_info=True)
        return None


async def capture_all_monitors(
    output_dir: Optional[str] = None,
) -> list[tuple[str, "Path"]]:
    """Her monitör için ayrı ekran görüntüsü al. Başarısızsa [] döner."""
    logger.debug("desktop.capture_all_monitors: output_dir=%s", output_dir)
    try:
        return await _capture_all_monitors(output_dir=output_dir)
    except Exception as exc:
        logger.error("capture_all_monitors hatası: %s", exc, exc_info=True)
        return []


async def list_monitors() -> list[dict]:
    """Monitör listesini döndür. Başarısızsa [] döner."""
    logger.debug("desktop.list_monitors called")
    try:
        return await _list_monitors()
    except Exception as exc:
        logger.error("list_monitors hatası: %s", exc, exc_info=True)
        return []


async def ocr_screen() -> str:
    """Ekrandan OCR metni çıkar. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.ocr_screen called")
    try:
        return await _ocr_screen()
    except Exception as exc:
        logger.error("ocr_screen hatası: %s", exc, exc_info=True)
        return f"❌ ocr_screen hatası: {exc}"


async def run_tesseract_on_file(image_path: str) -> str:
    """Dosya üzerinde Tesseract OCR çalıştır. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.run_tesseract_on_file: image_path=%s", image_path)
    try:
        return await _run_tesseract_on_file(image_path)
    except Exception as exc:
        logger.error("run_tesseract_on_file hatası: %s", exc, exc_info=True)
        return f"❌ run_tesseract_on_file hatası: {exc}"


# ── Thin Wrappers — Input ─────────────────────────────────────────────

async def xdotool_type(text: str, delay_ms: int = 12) -> str:
    """Aktif pencereye metin yaz. Başarısızsa hata mesajı döner."""
    # text loglanmaz — gizlilik
    logger.debug("desktop.xdotool_type: %d karakter, delay_ms=%d", len(text), delay_ms)
    try:
        return await _xdotool_type(text=text, delay_ms=delay_ms)
    except Exception as exc:
        logger.error("xdotool_type hatası: %s", exc, exc_info=True)
        return f"❌ xdotool_type hatası: {exc}"


async def xdotool_key(key: str) -> str:
    """Tuş/kombinasyon gönder. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.xdotool_key: key=%s", key)
    try:
        return await _xdotool_key(key=key)
    except Exception as exc:
        logger.error("xdotool_key hatası: %s", exc, exc_info=True)
        return f"❌ xdotool_key hatası: {exc}"


async def xdotool_click(x: int, y: int, button: int = 1) -> str:
    """Koordinata fare tıklaması. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.xdotool_click: x=%d y=%d button=%d", x, y, button)
    try:
        return await _xdotool_click(x=x, y=y, button=button)
    except Exception as exc:
        logger.error("xdotool_click hatası: %s", exc, exc_info=True)
        return f"❌ xdotool_click hatası: {exc}"


async def xdotool_move(x: int, y: int) -> str:
    """Fareyi koordinata taşı. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.xdotool_move: x=%d y=%d", x, y)
    try:
        return await _xdotool_move(x=x, y=y)
    except Exception as exc:
        logger.error("xdotool_move hatası: %s", exc, exc_info=True)
        return f"❌ xdotool_move hatası: {exc}"


async def xdotool_scroll(direction: str, amount: int = 3) -> str:
    """Fare tekerleği scroll. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.xdotool_scroll: direction=%s amount=%d", direction, amount)
    try:
        return await _xdotool_scroll(direction=direction, amount=amount)
    except Exception as exc:
        logger.error("xdotool_scroll hatası: %s", exc, exc_info=True)
        return f"❌ xdotool_scroll hatası: {exc}"


# ── Thin Wrappers — Vision ────────────────────────────────────────────

async def vision_query(
    question: str,
    model: str = "claude-haiku-4-5-20251001",
    region: Optional[tuple[int, int, int, int]] = None,
    use_cache: bool = True,
    session_id: Optional[str] = None,
) -> str:
    """Ekran görüntüsü + Vision API sorgusu. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.vision_query: model=%s region=%s use_cache=%s session=%s", model, region, use_cache, session_id)
    try:
        return await _vision_query(
            question=question, model=model, region=region, use_cache=use_cache, session_id=session_id,
        )
    except Exception as exc:
        logger.error("vision_query hatası: %s", exc, exc_info=True)
        return f"❌ vision_query hatası: {exc}"


def is_vision_available() -> bool:
    """Vision API (Anthropic key) mevcut mu? Görev başında proaktif kontrol için."""
    return _is_vision_available()


def check_vision_status() -> dict:
    """Vision API durumu + fallback önerisi. {"available": bool, "fallback": str|None, "message": str}"""
    return _check_vision_status()


def clear_bbox_cache() -> int:
    """Bbox cache'i temizle. Başarısızsa 0 döner."""
    logger.debug("desktop.clear_bbox_cache called")
    try:
        return _clear_bbox_cache()
    except Exception as exc:
        logger.error("clear_bbox_cache hatası: %s", exc, exc_info=True)
        return 0


def get_bbox_cache_stats() -> dict:
    """Bbox cache istatistiklerini döndür. Başarısızsa {} döner."""
    logger.debug("desktop.get_bbox_cache_stats called")
    try:
        return _get_bbox_cache_stats()
    except Exception as exc:
        logger.error("get_bbox_cache_stats hatası: %s", exc, exc_info=True)
        return {}


# ── Thin Wrappers — AT-SPI ────────────────────────────────────────────

async def atspi_get_desktop_tree(max_depth: int = 4) -> dict:
    """AT-SPI accessibility tree'yi döndür. Başarısızsa {} döner."""
    logger.debug("desktop.atspi_get_desktop_tree: max_depth=%d", max_depth)
    try:
        return await _atspi_get_desktop_tree(max_depth=max_depth)
    except Exception as exc:
        logger.error("atspi_get_desktop_tree hatası: %s", exc, exc_info=True)
        return {}


async def atspi_find_element(role: str = "", name: str = "") -> list[dict]:
    """AT-SPI'da element ara. Başarısızsa [] döner."""
    logger.debug("desktop.atspi_find_element: role=%r name=%r", role, name)
    try:
        return await _atspi_find_element(role=role, name=name)
    except Exception as exc:
        logger.error("atspi_find_element hatası: %s", exc, exc_info=True)
        return []


async def atspi_activate_element(role: str = "", name: str = "") -> str:
    """AT-SPI elementini aktive et. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.atspi_activate_element: role=%r name=%r", role, name)
    try:
        return await _atspi_activate_element(role=role, name=name)
    except Exception as exc:
        logger.error("atspi_activate_element hatası: %s", exc, exc_info=True)
        return f"❌ atspi_activate_element hatası: {exc}"


# ── Popup yönetimi (DESK-OPT-8) ──────────────────────────────────────
# System ops (open_path, unlock_screen, sudo_exec, run_installer, get_windows, focus_window)
# → desktop_system.py'ye taşındı. desktop.py re-export eder.


# ── Popup yönetimi (DESK-OPT-8) ──────────────────────────────────────

async def start_watch_popup(
    wm_class_patterns: list[str],
    timeout_s: float = 30.0,
    watcher_id: Optional[str] = None,
) -> tuple[bool, str, str]:
    """X11 MapNotify izleyiciyi başlatır. Döner: (ok, mesaj, watcher_id)."""
    logger.debug("desktop.start_watch_popup: patterns=%s timeout=%.0f", wm_class_patterns, timeout_s)
    try:
        return await _start_watch_popup(
            wm_class_patterns=wm_class_patterns,
            timeout_s=timeout_s,
            watcher_id=watcher_id,
        )
    except Exception as exc:
        logger.error("start_watch_popup hatası: %s", exc, exc_info=True)
        return False, f"❌ İzleyici başlatılamadı: {exc}", ""


async def stop_watch_popup(watcher_id: str) -> tuple[bool, str]:
    """Çalışan popup izleyiciyi durdurur. Döner: (ok, mesaj)."""
    logger.debug("desktop.stop_watch_popup: id=%s", watcher_id)
    try:
        return await _stop_watch_popup(watcher_id)
    except Exception as exc:
        logger.error("stop_watch_popup hatası: %s", exc, exc_info=True)
        return False, f"❌ İzleyici durdurulamadı: {exc}"


def list_watch_popups() -> list[dict]:
    """Aktif popup izleyicileri listeler."""
    try:
        return _list_watch_popups()
    except Exception as exc:
        logger.error("list_watch_popups hatası: %s", exc, exc_info=True)
        return []
