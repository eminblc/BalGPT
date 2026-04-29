"""WhatsApp router — HMAC imza doğrulaması ve webhook GET testleri.

_verify_signature() saf fonksiyon olduğundan doğrudan test edilir.
Webhook GET doğrulaması ve POST routing httpx.AsyncClient ile test edilir.
"""
import hashlib
import hmac as hmac_module
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── _verify_signature ─────────────────────────────────────────────

def _make_sig(body: bytes, secret: str) -> str:
    return "sha256=" + hmac_module.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_verify_signature_valid():
    from backend.routers.whatsapp_router import _verify_signature
    body = b'{"test": true}'
    secret = "test_secret_123"
    sig = _make_sig(body, secret)
    with patch("backend.routers.whatsapp_router.settings") as s:
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = secret
        s.whatsapp_app_secret = mock_secret
        s.environment = "development"
        assert _verify_signature(body, sig) is True


def test_verify_signature_invalid():
    from backend.routers.whatsapp_router import _verify_signature
    body = b'{"test": true}'
    with patch("backend.routers.whatsapp_router.settings") as s:
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = "test_secret_123"
        s.whatsapp_app_secret = mock_secret
        s.environment = "development"
        assert _verify_signature(body, "sha256=deadbeef") is False


def test_verify_signature_missing_prefix():
    """sha256= prefix'i olmayan imza → reddedilmeli."""
    from backend.routers.whatsapp_router import _verify_signature
    body = b'{"test": true}'
    with patch("backend.routers.whatsapp_router.settings") as s:
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = "test_secret_123"
        s.whatsapp_app_secret = mock_secret
        s.environment = "development"
        assert _verify_signature(body, "deadbeef") is False


def test_verify_signature_no_secret_dev_mode():
    """Secret tanımlı değil + dev → True (geliştirme modu atlatma)."""
    from backend.routers.whatsapp_router import _verify_signature
    with patch("backend.routers.whatsapp_router.settings") as s:
        s.whatsapp_app_secret = None
        s.environment = "development"
        assert _verify_signature(b"body", "") is True


def test_verify_signature_no_secret_production():
    """Secret tanımlı değil + production → False (red)."""
    from backend.routers.whatsapp_router import _verify_signature
    with patch("backend.routers.whatsapp_router.settings") as s:
        s.whatsapp_app_secret = None
        s.environment = "production"
        assert _verify_signature(b"body", "") is False


def test_verify_signature_tampering():
    """Gövde değiştirilirse imza geçersiz olmalı."""
    from backend.routers.whatsapp_router import _verify_signature
    original_body = b'{"original": true}'
    tampered_body = b'{"tampered": true}'
    secret = "my_secret"
    sig = _make_sig(original_body, secret)
    with patch("backend.routers.whatsapp_router.settings") as s:
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = secret
        s.whatsapp_app_secret = mock_secret
        s.environment = "development"
        assert _verify_signature(tampered_body, sig) is False


# ── Webhook GET ───────────────────────────────────────────────────

async def test_webhook_verify_get_success():
    """Doğru verify token → hub.challenge döner."""
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from backend.routers.whatsapp_router import router

    app = FastAPI()
    app.include_router(router, prefix="/whatsapp")

    with patch("backend.routers.whatsapp_router.settings") as s:
        s.whatsapp_verify_token = "my_verify_token"
        s.whatsapp_app_secret = None
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/whatsapp/webhook",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "my_verify_token",
                    "hub.challenge": "challenge_abc",
                },
            )
    assert resp.status_code == 200
    assert resp.text == "challenge_abc"


async def test_webhook_verify_get_wrong_token():
    """Yanlış verify token → 403."""
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from backend.routers.whatsapp_router import router

    app = FastAPI()
    app.include_router(router, prefix="/whatsapp")

    with patch("backend.routers.whatsapp_router.settings") as s:
        s.whatsapp_verify_token = "correct_token"
        s.whatsapp_app_secret = None
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/whatsapp/webhook",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "wrong_token",
                    "hub.challenge": "challenge_abc",
                },
            )
    assert resp.status_code == 403


# ── Webhook POST — imza kontrolü ─────────────────────────────────

async def test_webhook_post_invalid_signature_returns_403():
    """Geçersiz HMAC imzası → 403."""
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from backend.routers.whatsapp_router import router

    app = FastAPI()
    app.include_router(router, prefix="/whatsapp")

    body = b'{"entry": []}'
    with patch("backend.routers.whatsapp_router.settings") as s:
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = "real_secret"
        s.whatsapp_app_secret = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/whatsapp/webhook",
                content=body,
                headers={"X-Hub-Signature-256": "sha256=invalidsig"},
            )
    assert resp.status_code == 403


async def test_webhook_post_valid_signature_empty_entry_returns_ok():
    """Geçerli HMAC, boş entry listesi → 200 ok."""
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from backend.routers.whatsapp_router import router

    app = FastAPI()
    app.include_router(router, prefix="/whatsapp")

    secret = "webhook_secret"
    body = json.dumps({"entry": []}).encode()
    sig = _make_sig(body, secret)

    with patch("backend.routers.whatsapp_router.settings") as s:
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = secret
        s.whatsapp_app_secret = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/whatsapp/webhook",
                content=body,
                headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
            )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ── Guard zinciri entegrasyon testleri ───────────────────────────

def _make_whatsapp_app_with_chain(guard_chain):
    """Dependency override'lı test uygulaması oluşturur."""
    from fastapi import FastAPI
    from backend.routers.whatsapp_router import router, get_guard_chain
    from backend.guards import get_session_mgr

    app = FastAPI()
    app.include_router(router, prefix="/whatsapp")
    app.dependency_overrides[get_guard_chain] = lambda: guard_chain
    mock_s_mgr = MagicMock()
    mock_s_mgr.get.return_value = {"lang": "tr", "active_context": "main"}
    app.dependency_overrides[get_session_mgr] = lambda: mock_s_mgr
    return app


def _text_message_body(secret: str) -> tuple[bytes, str]:
    """Tek text mesajı içeren WhatsApp webhook gövdesi ve imzasını döner."""
    body = json.dumps({
        "entry": [{"changes": [{"value": {"messages": [
            {
                "from": "+905300000000",
                "id": "msg-test-1",
                "type": "text",
                "text": {"body": "merhaba"},
            }
        ]}}]}]
    }).encode()
    sig = _make_sig(body, secret)
    return body, sig


async def test_webhook_post_guard_rejects_dispatcher_not_called():
    """Guard zinciri mesajı engeller → handle_common_message çağrılmaz, 200 döner."""
    from httpx import AsyncClient, ASGITransport
    from backend.guards.guard_chain import GuardChain, GuardResult

    class _RejectAll:
        async def check(self, ctx):
            return GuardResult(passed=False, reason="test_block")

    app = _make_whatsapp_app_with_chain(GuardChain([_RejectAll()]))

    secret = "test_secret"
    body, sig = _text_message_body(secret)

    with patch("backend.routers.whatsapp_router.settings") as s, \
         patch("backend.routers._dispatcher.handle_common_message", AsyncMock()) as mock_dispatch:
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = secret
        s.whatsapp_app_secret = mock_secret
        s.environment = "development"
        s.default_language = "tr"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/whatsapp/webhook",
                content=body,
                headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
            )

    assert resp.status_code == 200
    mock_dispatch.assert_not_awaited()


async def test_webhook_post_guard_passes_dispatcher_called():
    """Guard zinciri geçer → handle_common_message text mesajıyla çağrılır."""
    from httpx import AsyncClient, ASGITransport
    from backend.guards.guard_chain import GuardChain, GuardResult

    class _PassAll:
        async def check(self, ctx):
            return GuardResult(passed=True)

    app = _make_whatsapp_app_with_chain(GuardChain([_PassAll()]))

    secret = "test_secret"
    body, sig = _text_message_body(secret)

    with patch("backend.routers.whatsapp_router.settings") as s, \
         patch("backend.routers._dispatcher.handle_common_message", AsyncMock()) as mock_dispatch:
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = secret
        s.whatsapp_app_secret = mock_secret
        s.environment = "development"
        s.default_language = "tr"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/whatsapp/webhook",
                content=body,
                headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
            )

    assert resp.status_code == 200
    mock_dispatch.assert_awaited_once()


async def test_webhook_post_invalid_json_returns_400():
    """Bozuk JSON gövdesi + geçerli HMAC → 400."""
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from backend.routers.whatsapp_router import router

    app = FastAPI()
    app.include_router(router, prefix="/whatsapp")

    secret = "test_secret"
    body = b"not valid json {"
    sig = _make_sig(body, secret)

    with patch("backend.routers.whatsapp_router.settings") as s:
        mock_secret = MagicMock()
        mock_secret.get_secret_value.return_value = secret
        s.whatsapp_app_secret = mock_secret
        s.environment = "development"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/whatsapp/webhook",
                content=body,
                headers={"X-Hub-Signature-256": sig, "Content-Type": "application/json"},
            )

    assert resp.status_code == 400


async def test_whatsapp_send_without_api_key_returns_401():
    """/whatsapp/send — API key yok → 401."""
    from httpx import AsyncClient, ASGITransport
    from fastapi import FastAPI
    from backend.routers.whatsapp_router import router

    app = FastAPI()
    app.include_router(router, prefix="/whatsapp")

    mock_api_key = MagicMock()
    mock_api_key.get_secret_value.return_value = "real-key"
    with patch("backend.guards.api_key.settings") as s:
        s.api_key = mock_api_key
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/whatsapp/send",
                json={"to": "+905300000000", "text": "test"},
            )

    assert resp.status_code == 401
