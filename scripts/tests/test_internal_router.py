"""Internal router — localhost kısıtlaması ve admin TOTP doğrulaması testleri."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI

_NO_LOCKOUT = AsyncMock(return_value=(0, 0.0))
_RESET_LOCKOUT = AsyncMock(return_value=None)
_RECORD_FAILURE = AsyncMock(return_value=(1, None))


def _make_app():
    from backend.routers.internal_router import router
    from backend.routers._schedule_router import router as schedule_router
    app = FastAPI()
    app.include_router(router)
    app.include_router(schedule_router)
    return app


# ── Localhost kısıtlaması ─────────────────────────────────────────

async def test_localhost_access_allowed():
    """127.0.0.1'den gelen istek → erişim izni (geçerli TOTP mock'u ile)."""
    app = _make_app()
    mock_perm = MagicMock()
    mock_perm.verify_totp.return_value = True
    with patch("backend.routers.internal_router.get_perm_mgr", return_value=mock_perm), \
         patch("backend.store.sqlite_store.totp_get_lockout", AsyncMock(return_value=(0, 0.0))), \
         patch("backend.store.sqlite_store.totp_reset_lockout", AsyncMock(return_value=None)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/verify-admin-totp",
                json={"code": "123456"},
            )
    assert resp.status_code == 200
    assert resp.json() == {"valid": True}


async def test_external_ip_blocked():
    """Harici IP → 403 Localhost only."""
    app = _make_app()
    transport = ASGITransport(app=app)
    # httpx ASGITransport, client host'unu testclient'ın bağlantı adresinden alır.
    # Bunu test etmek için _require_localhost fonksiyonunu doğrudan test ederiz.
    from backend.routers.internal_router import _require_localhost
    from fastapi import HTTPException

    mock_req = MagicMock()
    mock_req.client.host = "192.168.1.100"
    with pytest.raises(HTTPException) as exc_info:
        _require_localhost(mock_req)
    assert exc_info.value.status_code == 403


async def test_localhost_ipv6_allowed():
    """::1 (IPv6 localhost) da geçerli."""
    from backend.routers.internal_router import _require_localhost
    mock_req = MagicMock()
    mock_req.client.host = "::1"
    # Hata fırlatmamalı
    _require_localhost(mock_req)


async def test_localhost_ipv4_mapped_ipv6_allowed():
    """::ffff:127.0.0.1 de geçerli."""
    from backend.routers.internal_router import _require_localhost
    mock_req = MagicMock()
    mock_req.client.host = "::ffff:127.0.0.1"
    _require_localhost(mock_req)


async def test_no_client_blocked():
    """request.client yok → 403."""
    from backend.routers.internal_router import _require_localhost
    from fastapi import HTTPException
    mock_req = MagicMock()
    mock_req.client = None
    with pytest.raises(HTTPException):
        _require_localhost(mock_req)


# ── TOTP doğrulaması ──────────────────────────────────────────────

async def test_valid_admin_totp_returns_true():
    app = _make_app()
    mock_perm = MagicMock()
    mock_perm.verify_totp.return_value = True
    with patch("backend.routers.internal_router.get_perm_mgr", return_value=mock_perm), \
         patch("backend.store.sqlite_store.totp_get_lockout", AsyncMock(return_value=(0, 0.0))), \
         patch("backend.store.sqlite_store.totp_reset_lockout", AsyncMock(return_value=None)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/verify-admin-totp",
                json={"code": "123456"},
            )
    assert resp.json() == {"valid": True}


async def test_invalid_admin_totp_returns_false():
    app = _make_app()
    mock_perm = MagicMock()
    mock_perm.verify_totp.return_value = False
    with patch("backend.routers.internal_router.get_perm_mgr", return_value=mock_perm), \
         patch("backend.store.sqlite_store.totp_get_lockout", AsyncMock(return_value=(0, 0.0))), \
         patch("backend.store.sqlite_store.totp_record_failure", AsyncMock(return_value=(1, None))):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/verify-admin-totp",
                json={"code": "000000"},
            )
    assert resp.json() == {"valid": False}


# ── /internal/send_permission_prompt ─────────────────────────────

async def test_send_permission_prompt_ok():
    """send_permission_prompt localhost'tan → 200, messenger.send_buttons çağrılır."""
    app = _make_app()
    mock_messenger = MagicMock()
    mock_messenger.send_buttons = AsyncMock()

    with patch("backend.routers.internal_router.get_messenger",
               return_value=mock_messenger), \
         patch("backend.routers.internal_router.settings") as mock_settings, \
         patch("backend.routers.internal_router.get_session_mgr",
               return_value=MagicMock(get=MagicMock(return_value={"lang": "tr"}))):
        mock_settings.owner_id = "+905300000000"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/send_permission_prompt",
                json={
                    "session_id": "sess-1",
                    "request_id": "tool-req-1",
                    "tool_name": "Bash",
                    "tool_detail": "ls -la",
                },
            )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_messenger.send_buttons.assert_awaited_once()


async def test_send_permission_prompt_blocked_from_external():
    """send_permission_prompt harici IP → 403."""
    from backend.routers.internal_router import _require_localhost
    from fastapi import HTTPException
    mock_req = MagicMock()
    mock_req.client.host = "10.0.0.1"
    with pytest.raises(HTTPException) as exc_info:
        _require_localhost(mock_req)
    assert exc_info.value.status_code == 403


# ── /internal/send_message ────────────────────────────────────────

async def test_internal_send_message_ok():
    """/internal/send_message localhost'tan → 200, messenger.send_text çağrılır."""
    app = _make_app()
    mock_messenger = MagicMock()
    mock_messenger.send_text = AsyncMock()

    with patch("backend.routers.internal_router.get_messenger",
               return_value=mock_messenger):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/send_message",
                json={"to": "+905300000000", "text": "Merhaba"},
            )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    mock_messenger.send_text.assert_awaited_once_with("+905300000000", "Merhaba")


# ── /internal/schedule — CRUD ─────────────────────────────────────

async def test_create_cron_schedule_returns_task():
    """cron_expr verilince cron job oluşturulur."""
    app = _make_app()
    fake_task = {"id": "task-1", "description": "Test", "status": "scheduled"}

    with patch("backend.features.scheduler.create_scheduled_task",
               AsyncMock(return_value=fake_task)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/schedule",
                json={
                    "description": "Test cron",
                    "cron_expr": "0 9 * * *",
                    "action_type": "send_message",
                    "message": "Sabah hatırlatıcı",
                },
            )
    assert resp.status_code == 200
    assert resp.json()["id"] == "task-1"


async def test_create_oneshot_schedule_returns_task():
    """run_at verilince one-shot job oluşturulur."""
    import time
    app = _make_app()
    fake_task = {"id": "task-2", "description": "Oneshot", "status": "scheduled"}

    with patch("backend.features.scheduler.create_one_shot_task",
               AsyncMock(return_value=fake_task)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/schedule",
                json={
                    "description": "Oneshot test",
                    "run_at": time.time() + 3600,
                    "action_type": "send_message",
                    "message": "Sonra hatırlat",
                },
            )
    assert resp.status_code == 200
    assert resp.json()["id"] == "task-2"


async def test_past_run_at_returns_400():
    """Geçmiş run_at → 400."""
    import time
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/internal/schedule",
            json={
                "description": "Geçmiş test",
                "run_at": time.time() - 3600,
            },
        )
    assert resp.status_code == 400


async def test_both_cron_and_run_at_returns_400():
    """cron_expr ve run_at aynı anda → 400."""
    import time
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/internal/schedule",
            json={
                "description": "Çift parametre",
                "cron_expr": "0 9 * * *",
                "run_at": time.time() + 3600,
            },
        )
    assert resp.status_code == 400


async def test_neither_cron_nor_run_at_returns_400():
    """cron_expr ve run_at ikisi de yok → 400."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/internal/schedule",
            json={"description": "Eksik parametre"},
        )
    assert resp.status_code == 400


async def test_delete_schedule_returns_deleted():
    """DELETE /internal/schedule/{id} → {status: deleted}."""
    app = _make_app()
    with patch("backend.features.scheduler.soft_delete_job", AsyncMock()):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.delete("/internal/schedule/task-abc")
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"
    assert resp.json()["id"] == "task-abc"


async def test_list_schedules_returns_list():
    """GET /internal/schedules → list döner."""
    app = _make_app()
    fake_list = [{"id": "t1"}, {"id": "t2"}]
    with patch("backend.features.scheduler.list_cron_jobs", return_value=fake_list):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.get("/internal/schedules")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_update_schedule_returns_new_task():
    """PUT /internal/schedule/{id} → eski silinir + yeni oluşturulur."""
    app = _make_app()
    fake_task = {"id": "task-new", "description": "Güncellendi"}
    with patch("backend.features.scheduler.soft_delete_job", AsyncMock()), \
         patch("backend.features.scheduler.create_scheduled_task",
               AsyncMock(return_value=fake_task)):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.put(
                "/internal/schedule/task-old",
                json={
                    "description": "Güncellendi",
                    "cron_expr": "0 10 * * *",
                    "action_type": "run_bridge",
                    "message": "Yeni prompt",
                },
            )
    assert resp.status_code == 200
    assert resp.json()["id"] == "task-new"


# ── /internal/send_media ──────────────────────────────────────────

async def test_send_media_no_path_returns_400():
    """/internal/send_media — path ve paths ikisi de yok → 400."""
    app = _make_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        resp = await client.post(
            "/internal/send_media",
            json={"caption": "test"},
        )
    assert resp.status_code == 400


async def test_send_media_file_not_found_returns_error_result():
    """/internal/send_media — dosya bulunamadı → ok=False result."""
    app = _make_app()
    mock_messenger = MagicMock()
    mock_messenger.send_text = AsyncMock()

    with patch("backend.routers.internal_router.get_messenger", return_value=mock_messenger), \
         patch("backend.routers.internal_router.settings") as mock_settings:
        mock_settings.owner_id = "+905300000000"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/send_media",
                json={"path": "/tmp/nonexistent_test_file_99root.png"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert data["results"][0]["ok"] is False


async def test_send_media_non_media_messenger_text_fallback():
    """/internal/send_media — MediaMessenger olmayan messenger → metin fallback."""
    import tempfile, os
    app = _make_app()

    # MediaMessenger Protocol'ünü uygulamayan basit bir mock
    mock_messenger = MagicMock(spec=[])  # hiçbir spec → isinstance(m, MediaMessenger) → False
    mock_messenger.send_text = AsyncMock()

    # Geçici dosya oluştur
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"fake image data")
        tmp_path = f.name

    try:
        with patch("backend.routers.internal_router.get_messenger", return_value=mock_messenger), \
             patch("backend.routers.internal_router.settings") as mock_settings:
            mock_settings.owner_id = "+905300000000"

            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
                resp = await client.post(
                    "/internal/send_media",
                    json={"path": tmp_path, "caption": "Test görsel"},
                )
    finally:
        os.unlink(tmp_path)

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["results"][0].get("fallback") == "text"
    mock_messenger.send_text.assert_awaited_once()
