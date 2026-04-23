"""BrowserSession TypedDict ve _BrowserSessionStore sınıfı (SRP).

Sorumluluk: Aktif Playwright session'larını ve erişim kilidini kapsüller.
"""
from __future__ import annotations

import asyncio
from typing import Any, TypedDict


class BrowserSession(TypedDict):
    """Tek bir Playwright browser oturumunun bileşenlerini tutan TypedDict."""

    playwright: Any  # playwright.async_api.Playwright
    browser: Any     # playwright.async_api.Browser
    context: Any     # playwright.async_api.BrowserContext
    page: Any        # playwright.async_api.Page


class _BrowserSessionStore:
    """Playwright session'larını ve erişim kilidini tek yerde tutan singleton.

    Modül düzeyinde ham dict + Lock yerine bu sınıf kullanılır; global
    mutable state CLAUDE.md kuralına aykırı olduğundan encapsulation zorunludur.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def get(self, session_id: str) -> BrowserSession | None:
        return self._sessions.get(session_id)

    def set(self, session_id: str, sess: BrowserSession) -> None:
        self._sessions[session_id] = sess

    def pop(self, session_id: str) -> BrowserSession | None:
        return self._sessions.pop(session_id, None)

    def keys(self) -> list[str]:
        return list(self._sessions.keys())

    def items(self) -> list[tuple[str, BrowserSession]]:
        return list(self._sessions.items())

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._sessions


_session_store = _BrowserSessionStore()
