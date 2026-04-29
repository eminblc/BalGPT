"""Desktop router — localhost kısıtlaması ve xdotool aksiyonları testleri.

Tüm sistem çağrıları (xdotool, scrot, tesseract) mock'lanır; gerçek GUI işlemi yapılmaz.
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


@pytest.fixture(autouse=True)
def _bypass_desktop_totp_gate():
    """Admin TOTP gate'i testler için unlock açar (TTL=1 saat).

    Gerçek endpoint ilk çağrıda TOTP ister; testler bu akışı ayrıca test eder
    (`test_totp_gate_*`). Diğer tüm testler davranışsal testtir, TOTP ile
    ilgilenmez.
    """
    from backend.routers._desktop_totp_gate import get_desktop_totp_gate
    gate = get_desktop_totp_gate()
    gate._unlock_until = time.time() + 3600
    yield
    gate.reset()


def _make_app():
    from backend.routers.desktop_router import router
    app = FastAPI()
    app.include_router(router)
    return app


# ── Localhost kısıtlaması ─────────────────────────────────────────

async def test_external_ip_returns_403():
    """Harici IP → 403."""
    from backend.routers import desktop_router
    from fastapi.responses import JSONResponse

    mock_request = MagicMock()
    mock_request.client.host = "10.0.0.5"

    with patch("backend.routers.desktop_router.is_localhost", return_value=False):
        resp = await desktop_router.desktop_action(
            desktop_router.DesktopRequest(action="screenshot"),
            mock_request,
        )

    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 403


# ── Geçersiz aksiyon → 422 ───────────────────────────────────────

async def test_invalid_action_returns_422():
    """Geçersiz action → Pydantic validator 422 fırlatır."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/internal/desktop",
            json={"action": "nonexistent-action"},
        )
    assert resp.status_code == 422


# ── Desktop devre dışı ────────────────────────────────────────────

async def test_desktop_disabled_returns_ok_false():
    """DESKTOP_ENABLED=false → {ok: false}."""
    from backend.routers import desktop_router

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"

    mock_settings = MagicMock()
    mock_settings.desktop_enabled = False

    with patch("backend.routers.desktop_router.is_localhost", return_value=True), \
         patch("backend.routers.desktop_router.settings", mock_settings):
        resp = await desktop_router.desktop_action(
            desktop_router.DesktopRequest(action="screenshot"),
            mock_request,
        )

    assert resp["ok"] is False
    assert "devre dışı" in resp["message"].lower() or "disabled" in resp["message"].lower()


# ── screenshot aksiyonu ───────────────────────────────────────────

async def test_screenshot_with_mock_returns_ok():
    """screenshot → capture_screen mock ile ok=True ve path döner."""
    from backend.routers import desktop_router

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"

    mock_settings = MagicMock()
    mock_settings.desktop_enabled = True

    with patch("backend.routers.desktop_router.is_localhost", return_value=True), \
         patch("backend.routers.desktop_router.settings", mock_settings), \
         patch("backend.features.desktop.capture_all_monitors",
               AsyncMock(return_value=[("monitor0", "/tmp/screenshot_123.png")])):
        resp = await desktop_router.desktop_action(
            desktop_router.DesktopRequest(action="screenshot"),
            mock_request,
        )

    assert resp["ok"] is True


# ── type aksiyonu ─────────────────────────────────────────────────

async def test_type_text_with_mock_returns_ok():
    """type aksiyonu → type_text mock ile ok=True."""
    from backend.routers import desktop_router

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"

    mock_settings = MagicMock()
    mock_settings.desktop_enabled = True

    with patch("backend.routers.desktop_router.is_localhost", return_value=True), \
         patch("backend.routers.desktop_router.settings", mock_settings), \
         patch("backend.features.desktop.xdotool_type",
               AsyncMock(return_value="✅ Metin yazıldı")):
        resp = await desktop_router.desktop_action(
            desktop_router.DesktopRequest(action="type", text="merhaba dünya"),
            mock_request,
        )

    assert resp["ok"] is True
    assert "✅" in resp["message"]
