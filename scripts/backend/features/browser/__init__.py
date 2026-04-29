"""Playwright tabanlı tarayıcı otomasyon paketi — facade (FEAT-13 / FEAT-15).

Alt modüller:
  _session_store  — BrowserSession TypedDict + _BrowserSessionStore sınıfı
  _validation     — URL güvenlik doğrulaması, hassas site koruması, locator yardımcısı
  _paths          — Disk yolu çözümleme (browser_sessions_dir)
  _lifecycle      — Session aç/kapat/listele + lifecycle_shutdown hook
  _persistence    — Disk kalıcılığı: save/delete/list/info
  _actions        — Tüm browser_* aksiyon fonksiyonları

Mevcut çağrı noktaları değişmeden çalışır — tüm public semboller buradan re-export edilir.
"""
from ._session_store import BrowserSession, _BrowserSessionStore, _session_store
from ._validation import (
    _validate_url,
    _make_locator,
    _BLOCKED_SCHEMES,
    _BLOCKED_HOSTS,
    _SENSITIVE_DOMAINS,
)
from ._paths import _resolve_sessions_dir, _get_storage_state_path
from ._lifecycle import (
    _get_or_create_session,
    _close_session_internal,
    browser_close,
    browser_close_all,
    browser_list_sessions,
    lifecycle_shutdown,
)
from ._persistence import (
    browser_save_session,
    browser_delete_saved_session,
    browser_list_saved_sessions,
    browser_session_info,
)
from ._actions import (
    browser_goto,
    browser_fill,
    browser_click,
    browser_screenshot,
    browser_get_text,
    browser_get_content,
    browser_wait_for,
    browser_eval,
    browser_cdp_click,
    browser_select_option,
    browser_check,
    browser_type,
    browser_press,
    browser_hover,
    browser_get_attribute,
    browser_scroll,
    browser_get_url,
    _RISKY_JS_PATTERNS,
)

__all__ = [
    # Types
    "BrowserSession",
    "_BrowserSessionStore",
    "_session_store",
    # Validation
    "_validate_url",
    "_make_locator",
    # Paths
    "_resolve_sessions_dir",
    "_get_storage_state_path",
    # Lifecycle
    "_get_or_create_session",
    "_close_session_internal",
    "browser_close",
    "browser_close_all",
    "browser_list_sessions",
    "lifecycle_shutdown",
    # Persistence
    "browser_save_session",
    "browser_delete_saved_session",
    "browser_list_saved_sessions",
    "browser_session_info",
    # Actions
    "browser_goto",
    "browser_fill",
    "browser_click",
    "browser_screenshot",
    "browser_get_text",
    "browser_get_content",
    "browser_wait_for",
    "browser_eval",
    "browser_cdp_click",
    "browser_select_option",
    "browser_check",
    "browser_type",
    "browser_press",
    "browser_hover",
    "browser_get_attribute",
    "browser_scroll",
    "browser_get_url",
]
