"""features/desktop/ alt paket yapısı testleri.

Amaç:
- desktop/ dizini __init__.py ile paket olarak importlanabilmeli
- Beklenen tüm public semboller __all__ listesinde ve gerçekten erişilebilir olmalı
- Alt-paket refaktörüyle eklenen yeni re-export'lar (is_screen_locked, record_screen,
  record_all_monitors, check_size_mb) doğru çalışmalı

Bu testler gerçek X11 / xdotool / scrot çağrısı yapmaz — sadece Python import yapısını doğrular.
"""
from __future__ import annotations

import importlib
import sys


# ── 1. Paket import ───────────────────────────────────────────────────────────

def test_desktop_package_importable():
    """backend.features.desktop paketi hatasız import edilebilmeli."""
    import backend.features.desktop as pkg  # noqa: F401
    assert pkg is not None


def test_desktop_package_is_package():
    """backend.features.desktop bir paket olmalı (dosya değil, dizin)."""
    import backend.features.desktop as pkg
    assert hasattr(pkg, "__path__"), "desktop bir package (dizin) olmalı, modül (dosya) değil"


# ── 2. __all__ tam listesi ────────────────────────────────────────────────────

_EXPECTED_SYMBOLS = [
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
    # System
    "open_path",
    "unlock_screen",
    "sudo_exec",
    "run_installer",
    "get_windows",
    "focus_window",
    # Popup
    "start_watch_popup",
    "stop_watch_popup",
    "list_watch_popups",
    # Yeni re-export'lar (alt-paket refaktörüyle eklendi)
    "is_screen_locked",
    "record_screen",
    "record_all_monitors",
    "check_size_mb",
]


def test_desktop_all_contains_expected_symbols():
    """__all__ beklenen tüm sembolleri içermeli."""
    import backend.features.desktop as pkg
    missing = [s for s in _EXPECTED_SYMBOLS if s not in pkg.__all__]
    assert not missing, f"__all__'da eksik semboller: {missing}"


def test_desktop_symbols_are_accessible():
    """__all__'daki her sembol getattr ile erişilebilir olmalı."""
    import backend.features.desktop as pkg
    inaccessible = []
    for sym in _EXPECTED_SYMBOLS:
        try:
            obj = getattr(pkg, sym)
            assert obj is not None or sym in ("clear_bbox_cache",)  # fonksiyon her zaman var
        except AttributeError:
            inaccessible.append(sym)
    assert not inaccessible, f"Erişilemeyen semboller: {inaccessible}"


# ── 3. Yeni re-export'lar callable kontrolü ──────────────────────────────────

def test_is_screen_locked_is_callable():
    """is_screen_locked coroutine function olmalı."""
    import asyncio
    import inspect
    from backend.features.desktop import is_screen_locked
    assert inspect.iscoroutinefunction(is_screen_locked), \
        "is_screen_locked async def olmalı"


def test_record_screen_is_callable():
    from backend.features.desktop import record_screen
    import inspect
    assert inspect.iscoroutinefunction(record_screen)


def test_record_all_monitors_is_callable():
    from backend.features.desktop import record_all_monitors
    import inspect
    assert inspect.iscoroutinefunction(record_all_monitors)


def test_check_size_mb_is_callable():
    from backend.features.desktop import check_size_mb
    import inspect
    assert callable(check_size_mb) and not inspect.iscoroutinefunction(check_size_mb), \
        "check_size_mb normal (sync) fonksiyon olmalı"


# ── 4. Alt-modüller import edilebilir ─────────────────────────────────────────

def test_desktop_common_importable():
    import backend.features.desktop.desktop_common  # noqa: F401


def test_desktop_capture_importable():
    import backend.features.desktop.desktop_capture  # noqa: F401


def test_desktop_input_importable():
    import backend.features.desktop.desktop_input  # noqa: F401


def test_desktop_system_importable():
    import backend.features.desktop.desktop_system  # noqa: F401


def test_desktop_vision_importable():
    import backend.features.desktop.desktop_vision  # noqa: F401


def test_desktop_recording_importable():
    import backend.features.desktop.desktop_recording  # noqa: F401


def test_desktop_atspi_importable():
    import backend.features.desktop.desktop_atspi  # noqa: F401


def test_desktop_popup_importable():
    import backend.features.desktop.desktop_popup  # noqa: F401
