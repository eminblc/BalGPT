"""Terminal router — localhost kısıtlaması, komut çalıştırma ve tehlikeli komut testleri.

execute_command ve is_dangerous, terminal_router içinde lazily import edilir
(from ..features.terminal import ...); bu yüzden patch adresi
backend.features.terminal.* olmalı.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI
from fastapi.responses import JSONResponse


def _make_app():
    from backend.routers.terminal_router import router
    app = FastAPI()
    app.include_router(router)
    return app


# ── Localhost kısıtlaması ──────────────────────────────────────────

async def test_localhost_access_allowed():
    """127.0.0.1'den komut çalıştırma → 200."""
    fake_result = MagicMock()
    fake_result.stdout = "hello"
    fake_result.returncode = 0
    fake_result.timed_out = False

    from backend.routers import terminal_router

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"

    with patch("backend.features.terminal.execute_command",
               AsyncMock(return_value=fake_result)), \
         patch("backend.features.terminal.is_dangerous", return_value=False):
        resp = await terminal_router.terminal_run(
            terminal_router.TerminalRequest(cmd="echo hello"),
            mock_request,
        )

    assert resp["ok"] is True
    assert resp["timed_out"] is False


async def test_external_ip_blocked():
    """Harici IP → JSONResponse 403."""
    from backend.routers import terminal_router

    mock_request = MagicMock()
    mock_request.client.host = "10.0.0.5"

    resp = await terminal_router.terminal_run(
        terminal_router.TerminalRequest(cmd="echo hi"),
        mock_request,
    )

    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 403


async def test_localhost_set_contains_127():
    """is_localhost() 127.0.0.1/::1 için True, harici IP için False döner."""
    from backend.routers._localhost_guard import is_localhost

    def _req(host: str):
        r = MagicMock()
        r.client.host = host
        return r

    assert is_localhost(_req("127.0.0.1")) is True
    assert is_localhost(_req("::1")) is True
    assert is_localhost(_req("::ffff:127.0.0.1")) is True
    assert is_localhost(_req("192.168.1.100")) is False


# ── Geçerli komut ──────────────────────────────────────────────────

async def test_valid_cmd_returns_ok_true():
    """Başarılı komut → ok=True, returncode=0."""
    fake_result = MagicMock()
    fake_result.stdout = "world"
    fake_result.returncode = 0
    fake_result.timed_out = False

    from backend.routers import terminal_router
    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"

    with patch("backend.features.terminal.execute_command",
               AsyncMock(return_value=fake_result)), \
         patch("backend.features.terminal.is_dangerous", return_value=False):
        result = await terminal_router.terminal_run(
            terminal_router.TerminalRequest(cmd="echo world"),
            mock_request,
        )

    assert result["ok"] is True
    assert result["stdout"] == "world"
    assert result["returncode"] == 0
    assert result["dangerous"] is False


# ── Boş komut ─────────────────────────────────────────────────────

async def test_empty_cmd_returns_422():
    """Boş cmd → Pydantic validator 422 fırlatır."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/internal/terminal",
            json={"cmd": ""},
        )
    assert resp.status_code == 422


# ── Zaman aşımı ───────────────────────────────────────────────────

async def test_timed_out_cmd_returns_ok_false():
    """timed_out=True → ok=False."""
    fake_result = MagicMock()
    fake_result.stdout = "⏱️ Zaman aşımı"
    fake_result.returncode = -1
    fake_result.timed_out = True

    from backend.routers import terminal_router
    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"

    with patch("backend.features.terminal.execute_command",
               AsyncMock(return_value=fake_result)), \
         patch("backend.features.terminal.is_dangerous", return_value=False):
        result = await terminal_router.terminal_run(
            terminal_router.TerminalRequest(cmd="sleep 99", timeout=1),
            mock_request,
        )

    assert result["ok"] is False
    assert result["timed_out"] is True


# ── Tehlikeli komut ───────────────────────────────────────────────

async def test_dangerous_flag_set_in_response():
    """Tehlikeli komut → dangerous=True (yine çalıştırılır)."""
    fake_result = MagicMock()
    fake_result.stdout = "done"
    fake_result.returncode = 0
    fake_result.timed_out = False

    from backend.routers import terminal_router
    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"

    with patch("backend.features.terminal.execute_command",
               AsyncMock(return_value=fake_result)), \
         patch("backend.features.terminal.is_dangerous", return_value=True):
        result = await terminal_router.terminal_run(
            terminal_router.TerminalRequest(cmd="rm -rf /tmp/test"),
            mock_request,
        )

    assert result["dangerous"] is True
    assert result["ok"] is True
