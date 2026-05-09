"""Desktop TOTP gate — oturum bazlı unlock davranışı testleri.

Kapsam:
- Gate başlangıçta kilitli
- `code` alanı yoksa endpoint TOTP bekler (requires_totp=True)
- Geçerli kod → TTL boyunca unlock
- Geçersiz kod → kilit artar, brute-force sonrası lockout
- TTL dolduğunda yeniden kilitlenir
- Batch endpoint için de aynı gate uygulanır
"""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def _reset_gate():
    """Her test için taze bir gate (unlock sıfırlı) ve lockout DB reset."""
    from backend.routers._desktop_totp_gate import get_desktop_totp_gate
    gate = get_desktop_totp_gate()
    gate.reset()
    yield
    gate.reset()


# ── DesktopTotpGate sınıf davranışı ────────────────────────────────

async def test_gate_starts_locked():
    from backend.routers._desktop_totp_gate import DesktopTotpGate
    gate = DesktopTotpGate(ttl_seconds=900)
    assert gate.is_unlocked() is False
    assert gate.remaining_seconds() == 0


async def test_gate_unlock_success_sets_ttl_window():
    """Geçerli TOTP → unlock + TTL."""
    from backend.routers import _desktop_totp_gate as mod

    gate = mod.DesktopTotpGate(ttl_seconds=60)

    mock_perm = MagicMock()
    mock_perm.verify_admin_totp.return_value = True

    with patch.object(mod, "get_perm_mgr", return_value=mock_perm), \
         patch("backend.store.sqlite_store.totp_get_lockout",
               AsyncMock(return_value=(0, 0))), \
         patch("backend.store.sqlite_store.totp_reset_lockout",
               AsyncMock(return_value=None)):
        valid, remaining = await gate.try_unlock("123456")

    assert valid is True
    assert remaining is None
    assert gate.is_unlocked() is True
    assert gate.remaining_seconds() > 0


async def test_gate_unlock_failure_returns_false():
    """Geçersiz TOTP → unlock olmaz."""
    from backend.routers import _desktop_totp_gate as mod

    gate = mod.DesktopTotpGate(ttl_seconds=60)

    mock_perm = MagicMock()
    mock_perm.verify_totp.return_value = False

    with patch.object(mod, "get_perm_mgr", return_value=mock_perm), \
         patch("backend.store.sqlite_store.totp_get_lockout",
               AsyncMock(return_value=(0, 0))), \
         patch("backend.store.sqlite_store.totp_record_failure",
               AsyncMock(return_value=(1, None))):
        valid, remaining = await gate.try_unlock("000000")

    assert valid is False
    assert remaining is None
    assert gate.is_unlocked() is False


async def test_gate_active_lockout_blocks_even_valid_code():
    """Brute-force kilidi aktifken doğru kod bile red."""
    from backend.routers import _desktop_totp_gate as mod

    gate = mod.DesktopTotpGate(ttl_seconds=60)
    future = time.time() + 300

    with patch("backend.store.sqlite_store.totp_get_lockout",
               AsyncMock(return_value=(3, future))):
        valid, remaining = await gate.try_unlock("123456")

    assert valid is False
    assert remaining is not None and remaining > 0
    assert gate.is_unlocked() is False


async def test_gate_ttl_expiry_relocks():
    """TTL dolduğunda unlock kapanır."""
    from backend.routers._desktop_totp_gate import DesktopTotpGate

    gate = DesktopTotpGate(ttl_seconds=60)
    gate._unlock_until = time.time() - 1
    assert gate.is_unlocked() is False


# ── Endpoint entegrasyonu ──────────────────────────────────────────

async def test_desktop_action_without_code_returns_totp_required():
    """code yok ve gate kilitli → requires_totp=True, handler çalışmaz."""
    from backend.routers import desktop_router

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_settings = MagicMock()
    mock_settings.desktop_enabled = True

    # capture mock'unun çağrılmadığını doğrulamak için spy
    capture_mock = AsyncMock(return_value="/tmp/x.png")

    with patch("backend.routers.desktop_router.is_localhost", return_value=True), \
         patch("backend.routers.desktop_router.settings", mock_settings), \
         patch("backend.routers.desktop_router.request_desktop_totp", AsyncMock()), \
         patch("backend.features.desktop.capture_screen", capture_mock):
        resp = await desktop_router.desktop_action(
            desktop_router.DesktopRequest(action="screenshot"),
            mock_request,
        )

    assert resp["ok"] is False
    assert resp.get("requires_totp") is True
    capture_mock.assert_not_called()


async def test_desktop_action_with_valid_code_unlocks_and_runs():
    """Geçerli code → gate unlock + handler çalışır."""
    from backend.routers import desktop_router, _desktop_totp_gate as gate_mod

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_settings = MagicMock()
    mock_settings.desktop_enabled = True

    mock_perm = MagicMock()
    mock_perm.verify_admin_totp.return_value = True

    with patch("backend.routers.desktop_router.is_localhost", return_value=True), \
         patch("backend.routers.desktop_router.settings", mock_settings), \
         patch.object(gate_mod, "get_perm_mgr", return_value=mock_perm), \
         patch("backend.store.sqlite_store.totp_get_lockout",
               AsyncMock(return_value=(0, 0))), \
         patch("backend.store.sqlite_store.totp_reset_lockout",
               AsyncMock(return_value=None)), \
         patch("backend.features.desktop.capture_all_monitors",
               AsyncMock(return_value=[("monitor0", "/tmp/x.png")])):
        resp = await desktop_router.desktop_action(
            desktop_router.DesktopRequest(action="screenshot", code="123456"),
            mock_request,
        )

    assert resp["ok"] is True


async def test_desktop_action_invalid_code_returns_invalid_message():
    """Geçersiz code → requires_totp ve hata mesajı."""
    from backend.routers import desktop_router, _desktop_totp_gate as gate_mod

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_settings = MagicMock()
    mock_settings.desktop_enabled = True

    mock_perm = MagicMock()
    mock_perm.verify_totp.return_value = False

    with patch("backend.routers.desktop_router.is_localhost", return_value=True), \
         patch("backend.routers.desktop_router.settings", mock_settings), \
         patch("backend.routers.desktop_router.request_desktop_totp", AsyncMock()), \
         patch.object(gate_mod, "get_perm_mgr", return_value=mock_perm), \
         patch("backend.store.sqlite_store.totp_get_lockout",
               AsyncMock(return_value=(0, 0))), \
         patch("backend.store.sqlite_store.totp_record_failure",
               AsyncMock(return_value=(1, None))):
        resp = await desktop_router.desktop_action(
            desktop_router.DesktopRequest(action="screenshot", code="000000"),
            mock_request,
        )

    assert resp["ok"] is False
    assert resp.get("requires_totp") is True
    assert "Geçersiz" in resp["message"] or "geçersiz" in resp["message"].lower()


async def test_desktop_action_second_call_does_not_require_code():
    """Başarılı unlock sonrası TTL içinde ikinci çağrı code'suz geçer."""
    from backend.routers import desktop_router, _desktop_totp_gate as gate_mod

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_settings = MagicMock()
    mock_settings.desktop_enabled = True

    mock_perm = MagicMock()
    mock_perm.verify_admin_totp.return_value = True

    common_patches = [
        patch("backend.routers.desktop_router.is_localhost", return_value=True),
        patch("backend.routers.desktop_router.settings", mock_settings),
        patch.object(gate_mod, "get_perm_mgr", return_value=mock_perm),
        patch("backend.store.sqlite_store.totp_get_lockout",
              AsyncMock(return_value=(0, 0))),
        patch("backend.store.sqlite_store.totp_reset_lockout",
              AsyncMock(return_value=None)),
        patch("backend.features.desktop.capture_all_monitors",
              AsyncMock(return_value=[("monitor0", "/tmp/x.png")])),
    ]
    for p in common_patches:
        p.start()
    try:
        # İlk çağrı: code ile unlock
        r1 = await desktop_router.desktop_action(
            desktop_router.DesktopRequest(action="screenshot", code="123456"),
            mock_request,
        )
        # İkinci çağrı: code yok
        r2 = await desktop_router.desktop_action(
            desktop_router.DesktopRequest(action="screenshot"),
            mock_request,
        )
    finally:
        for p in common_patches:
            p.stop()

    assert r1["ok"] is True
    assert r2["ok"] is True


async def test_desktop_batch_without_code_blocks_all_actions():
    """Batch: code yok → requires_totp; handler çağrılmaz."""
    from backend.routers import desktop_router

    mock_request = MagicMock()
    mock_request.client.host = "127.0.0.1"
    mock_settings = MagicMock()
    mock_settings.desktop_enabled = True

    capture_mock = AsyncMock(return_value="/tmp/x.png")

    body = desktop_router.DesktopBatchRequest(
        actions=[
            desktop_router.DesktopRequest(action="screenshot"),
            desktop_router.DesktopRequest(action="screenshot"),
        ],
    )

    with patch("backend.routers.desktop_router.is_localhost", return_value=True), \
         patch("backend.routers.desktop_router.settings", mock_settings), \
         patch("backend.routers.desktop_router.request_desktop_totp", AsyncMock()), \
         patch("backend.features.desktop.capture_screen", capture_mock):
        resp = await desktop_router.desktop_batch(body, mock_request)

    assert resp["ok"] is False
    assert resp.get("requires_totp") is True
    capture_mock.assert_not_called()
