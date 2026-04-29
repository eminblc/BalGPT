"""Telegram router — webhook secret doğrulaması ve /send endpoint testleri.

Tüm dış bağımlılıklar mock'lanır; Telegram Bot API'ye gerçek istek atılmaz.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


def _make_app():
    from backend.routers.telegram_router import router
    app = FastAPI()
    app.include_router(router, prefix="/telegram")
    return app


def _mock_settings(secret: str = "test-secret", env: str = "development",
                   api_key_value: str = "test-api-key"):
    mock = MagicMock()
    mock.telegram_webhook_secret.get_secret_value.return_value = secret
    mock.environment = env
    mock.restrict_conv_history = True
    mock.conv_history_enabled = False
    mock.telegram_chat_id = "123456"
    mock.owner_id = "123456"
    return mock


# ── Webhook secret doğrulaması ────────────────────────────────────

async def test_webhook_valid_secret_returns_200():
    """`X-Telegram-Bot-Api-Secret-Token` doğruysa → 200."""
    app = _make_app()
    with patch("backend.routers.telegram_router.settings", _mock_settings(secret="my-secret")), \
         patch("backend.routers.telegram_router._handle_update", AsyncMock()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/telegram/webhook",
                json={"update_id": 1},
                headers={"X-Telegram-Bot-Api-Secret-Token": "my-secret"},
            )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_webhook_invalid_secret_returns_403():
    """`X-Telegram-Bot-Api-Secret-Token` yanlışsa → 403."""
    app = _make_app()
    with patch("backend.routers.telegram_router.settings", _mock_settings(secret="real-secret")):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/telegram/webhook",
                json={"update_id": 1},
                headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
            )
    assert resp.status_code == 403


async def test_webhook_no_secret_dev_mode_returns_200():
    """Secret tanımlı değil + development → doğrulama atlanır, 200 döner."""
    app = _make_app()
    with patch("backend.routers.telegram_router.settings",
               _mock_settings(secret="", env="development")), \
         patch("backend.routers.telegram_router._handle_update", AsyncMock()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/telegram/webhook",
                json={"update_id": 1},
            )
    assert resp.status_code == 200


async def test_webhook_no_secret_production_returns_403():
    """Secret tanımlı değil + production → 403."""
    app = _make_app()
    with patch("backend.routers.telegram_router.settings",
               _mock_settings(secret="", env="production")):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/telegram/webhook",
                json={"update_id": 1},
            )
    assert resp.status_code == 403


# ── /telegram/send endpoint'i ─────────────────────────────────────

async def test_send_without_api_key_returns_401():
    """/telegram/send — API key yok → 401."""
    app = _make_app()
    mock_api_key = MagicMock()
    mock_api_key.get_secret_value.return_value = "real-key"
    with patch("backend.guards.api_key.settings") as s:
        s.api_key = mock_api_key
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/telegram/send",
                json={"to": "123", "text": "hello"},
            )
    assert resp.status_code == 401


async def test_send_with_valid_api_key_returns_200():
    """/telegram/send — geçerli API key → 200."""
    app = _make_app()
    mock_api_key = MagicMock()
    mock_api_key.get_secret_value.return_value = "real-key"
    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.telegram_router.get_messenger") as mock_gm, \
         patch("backend.routers.telegram_router.settings",
               _mock_settings(secret="")):
        s.api_key = mock_api_key
        s.environment = "development"
        mock_messenger = AsyncMock()
        mock_gm.return_value = mock_messenger
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/telegram/send",
                json={"to": "123", "text": "hello"},
                headers={"X-Api-Key": "real-key"},
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ── callback_query işleme ─────────────────────────────────────────

async def test_webhook_callback_query_processed():
    """callback_query içeren Update → _handle_update çağrılır ve 200 döner."""
    app = _make_app()
    callback_payload = {
        "update_id": 42,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": 99999},
            "data": "perm_a:tool-123",
        },
    }
    with patch("backend.routers.telegram_router.settings",
               _mock_settings(secret="", env="development")), \
         patch("backend.routers.telegram_router._handle_update", AsyncMock()) as mock_handle:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/telegram/webhook",
                json=callback_payload,
            )
    assert resp.status_code == 200
    mock_handle.assert_awaited_once()


# ── Guard zinciri entegrasyon testleri ───────────────────────────

def _make_app_with_chain(guard_chain):
    """Dependency override'lı test uygulaması oluşturur."""
    from backend.routers.telegram_router import router, get_guard_chain
    from backend.guards import get_session_mgr

    app = FastAPI()
    app.include_router(router, prefix="/telegram")
    app.dependency_overrides[get_guard_chain] = lambda: guard_chain
    mock_s_mgr = MagicMock()
    mock_s_mgr.get.return_value = {"lang": "tr", "active_context": "main"}
    app.dependency_overrides[get_session_mgr] = lambda: mock_s_mgr
    return app


async def test_webhook_post_invalid_json_returns_400():
    """Geçerli secret, bozuk JSON gövde → 400."""
    app = _make_app()
    with patch("backend.routers.telegram_router.settings",
               _mock_settings(secret="my-secret", env="development")):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/telegram/webhook",
                content=b"not valid json {",
                headers={
                    "X-Telegram-Bot-Api-Secret-Token": "my-secret",
                    "Content-Type": "application/json",
                },
            )
    assert resp.status_code == 400


async def test_webhook_guard_rejects_dispatcher_not_called():
    """Guard zinciri mesajı engeller → handle_common_message çağrılmaz."""
    from backend.guards.guard_chain import GuardChain, GuardResult

    class _RejectAll:
        async def check(self, ctx):
            return GuardResult(passed=False, reason="test_block")

    app = _make_app_with_chain(GuardChain([_RejectAll()]))
    text_update = {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "from": {"id": 123456, "is_bot": False},
            "text": "merhaba",
        },
    }

    with patch("backend.routers.telegram_router.settings",
               _mock_settings(secret="", env="development")), \
         patch("backend.routers._dispatcher.handle_common_message", AsyncMock()) as mock_dispatch:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/telegram/webhook", json=text_update)

    assert resp.status_code == 200
    mock_dispatch.assert_not_awaited()


async def test_webhook_guard_passes_text_dispatched():
    """Guard zinciri geçer → handle_common_message text mesajıyla çağrılır."""
    from backend.guards.guard_chain import GuardChain, GuardResult

    class _PassAll:
        async def check(self, ctx):
            return GuardResult(passed=True)

    app = _make_app_with_chain(GuardChain([_PassAll()]))
    text_update = {
        "update_id": 2,
        "message": {
            "message_id": 20,
            "from": {"id": 123456, "is_bot": False},
            "text": "merhaba dünya",
        },
    }

    with patch("backend.routers.telegram_router.settings",
               _mock_settings(secret="", env="development")), \
         patch("backend.routers._dispatcher.handle_common_message", AsyncMock()) as mock_dispatch:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/telegram/webhook", json=text_update)

    assert resp.status_code == 200
    mock_dispatch.assert_awaited_once()
