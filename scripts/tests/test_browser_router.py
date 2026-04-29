"""Browser router — localhost kısıtlaması ve Playwright aksiyonları testleri.

Playwright tamamen mock'lanır; gerçek tarayıcı başlatılmaz.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


def _make_app():
    from backend.routers.browser_router import router
    app = FastAPI()
    app.include_router(router)
    return app


# ── Localhost kısıtlaması ─────────────────────────────────────────

async def test_external_ip_returns_403():
    """Harici IP → 403."""
    from backend.routers import browser_router

    mock_request = MagicMock()
    mock_request.client.host = "10.0.0.5"

    with patch("backend.routers.browser_router.is_localhost", return_value=False):
        resp = await browser_router.browser_action(
            browser_router.BrowserRequest(action="list_sessions"),
            mock_request,
        )
    from fastapi.responses import JSONResponse
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 403


# ── Geçersiz aksiyon → 422 ───────────────────────────────────────

async def test_invalid_action_returns_422():
    """Geçersiz action → Pydantic validator 422 fırlatır."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/internal/browser",
            json={"action": "invalid-action-xyz"},
        )
    assert resp.status_code == 422


# ── Tarayıcı devre dışı ───────────────────────────────────────────

async def test_browser_disabled_returns_ok_false():
    """BROWSER_ENABLED=false → {ok: false}."""
    from backend.routers import browser_router

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"

    mock_settings = MagicMock()
    mock_settings.browser_enabled = False

    with patch("backend.routers.browser_router.is_localhost", return_value=True), \
         patch("backend.routers.browser_router.settings", mock_settings):
        resp = await browser_router.browser_action(
            browser_router.BrowserRequest(action="goto", url="https://example.com"),
            mock_request,
        )

    assert resp["ok"] is False
    assert "devre dışı" in resp["message"].lower() or "disabled" in resp["message"].lower()


# ── list_sessions ─────────────────────────────────────────────────

async def test_list_sessions_returns_sessions():
    """list_sessions → session listesi döner."""
    from backend.routers import browser_router

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"

    mock_settings = MagicMock()
    mock_settings.browser_enabled = True

    with patch("backend.routers.browser_router.is_localhost", return_value=True), \
         patch("backend.routers.browser_router.settings", mock_settings), \
         patch("backend.features.browser.browser_list_sessions",
               return_value=["default", "session-2"]):
        resp = await browser_router.browser_action(
            browser_router.BrowserRequest(action="list_sessions"),
            mock_request,
        )

    assert resp["ok"] is True
    assert "sessions" in resp
    assert "default" in resp["sessions"]


# ── goto ile mock ─────────────────────────────────────────────────

async def test_goto_with_mock_returns_ok():
    """goto aksiyonu → browser_goto mock ile ok=True."""
    from backend.routers import browser_router

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"

    mock_settings = MagicMock()
    mock_settings.browser_enabled = True

    with patch("backend.routers.browser_router.is_localhost", return_value=True), \
         patch("backend.routers.browser_router.settings", mock_settings), \
         patch("backend.features.browser.browser_goto",
               AsyncMock(return_value=(True, "✅ Sayfaya gidildi: https://example.com"))):
        resp = await browser_router.browser_action(
            browser_router.BrowserRequest(action="goto", url="https://example.com"),
            mock_request,
        )

    assert resp["ok"] is True
    assert "example.com" in resp["message"]
