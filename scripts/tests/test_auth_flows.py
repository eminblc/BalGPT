"""_auth_flows.py — handle_math_challenge, handle_admin_totp, handle_totp testleri.

Lazy import notu:
  _auth_flows içindeki db ve _bridge_client, her fonksiyon içinde lazy import edilir.
  Bu nedenle patch hedefleri kaynak modülleri olmalıdır:
    - db  → backend.store.sqlite_store (her metod ayrı patch)
    - _bridge_client → backend.routers._bridge_client
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.app_types import SessionState

# _bridge_client'ı önceden import ederek sys.modules'a kaydedelim
import backend.routers._bridge_client  # noqa: F401


def _make_session(**kwargs) -> SessionState:
    defaults = dict(active_context="main", awaiting_totp=False,
                    awaiting_math_challenge=False,
                    awaiting_guardrail_confirm=False, pending_command="", menu_page=0)
    defaults.update(kwargs)
    return SessionState(**defaults)


def _msg(text: str, msg_id: str = "msg-001") -> dict:
    return {"id": msg_id, "type": "text", "text": {"body": text}}


def _patch_messenger():
    mock = AsyncMock()
    return patch("backend.routers._auth_flows.get_messenger", return_value=mock), mock


# ═══════════════════════════════════════════════════════════════════
# handle_math_challenge
# ═══════════════════════════════════════════════════════════════════

async def test_math_correct_answer_transitions_to_totp():
    """Doğru yanıt → clear_math_challenge + start_totp."""
    session = _make_session(awaiting_math_challenge=True,
                            math_challenge_answer=42,
                            math_challenge_command="!shutdown")
    patcher_m, mock_msg = _patch_messenger()

    with patcher_m, \
         patch("backend.routers._auth_flows.log_inbound"), \
         patch("backend.routers._auth_flows.log_outbound"):
        from backend.routers import _auth_flows
        await _auth_flows.handle_math_challenge("905001234567", _msg("42"), session)

    assert session.get("awaiting_math_challenge") is False
    assert session.get("awaiting_totp") is True
    assert session.get("pending_command") == "!shutdown"
    mock_msg.send_text.assert_awaited_once()


async def test_math_wrong_answer_increments_fail_count():
    """Yanlış yanıt → fail_count artar, math challenge devam eder."""
    session = _make_session(awaiting_math_challenge=True,
                            math_challenge_answer=42,
                            math_challenge_command="!shutdown")
    patcher_m, mock_msg = _patch_messenger()

    with patcher_m, \
         patch("backend.routers._auth_flows.log_inbound"), \
         patch("backend.routers._auth_flows.log_outbound"):
        from backend.routers import _auth_flows
        await _auth_flows.handle_math_challenge("905001234567", _msg("99"), session)

    assert session.get("awaiting_math_challenge") is True
    assert session.get("math_fail_count", 0) == 1
    mock_msg.send_text.assert_awaited_once()
    assert "Yanlış" in mock_msg.send_text.call_args[0][1]


async def test_math_non_digit_input_increments_fail_count():
    """Sayı olmayan giriş → fail_count artar."""
    session = _make_session(awaiting_math_challenge=True, math_challenge_answer=42,
                            math_challenge_command="!shutdown")
    patcher_m, mock_msg = _patch_messenger()

    with patcher_m, \
         patch("backend.routers._auth_flows.log_inbound"), \
         patch("backend.routers._auth_flows.log_outbound"):
        from backend.routers import _auth_flows
        await _auth_flows.handle_math_challenge("905001234567", _msg("abc"), session)

    assert session.get("math_fail_count", 0) == 1


async def test_math_three_wrong_cancels():
    """3 yanlış yanıt → math challenge iptal edilir."""
    session = _make_session(awaiting_math_challenge=True,
                            math_challenge_answer=42,
                            math_challenge_command="!shutdown",
                            math_fail_count=2)  # 2. hatadan sonra 3. hata → iptal
    patcher_m, mock_msg = _patch_messenger()

    with patcher_m, \
         patch("backend.routers._auth_flows.log_inbound"), \
         patch("backend.routers._auth_flows.log_outbound"):
        from backend.routers import _auth_flows
        await _auth_flows.handle_math_challenge("905001234567", _msg("99"), session)

    assert session.get("awaiting_math_challenge") is False
    assert "iptal" in mock_msg.send_text.call_args[0][1].lower()


# ═══════════════════════════════════════════════════════════════════
# handle_totp
# ═══════════════════════════════════════════════════════════════════

async def test_totp_correct_clears_state_and_sends_ok():
    """Doğru TOTP → awaiting_totp temizlenir, onay mesajı gönderilir."""
    session = _make_session(awaiting_totp=True, pending_command="!help")
    patcher_m, mock_msg = _patch_messenger()

    mock_perm = MagicMock()
    mock_perm.verify_totp.return_value = True
    with patcher_m, \
         patch("backend.store.sqlite_store.totp_get_lockout",
               AsyncMock(return_value=(0, None))), \
         patch("backend.store.sqlite_store.totp_reset_lockout", AsyncMock()), \
         patch("backend.store.sqlite_store.totp_record_failure",
               AsyncMock(return_value=(1, None))), \
         patch("backend.routers._auth_flows.get_perm_mgr", return_value=mock_perm), \
         patch("backend.routers._auth_flows.cmd_registry") as mock_reg, \
         patch("backend.routers._auth_flows.log_inbound"), \
         patch("backend.routers._auth_flows.log_outbound"):
        # !help komutunu bulduğunda execute çağırılır — mock ile durdur
        mock_cmd = MagicMock()
        mock_cmd.execute = AsyncMock()
        mock_reg.get.return_value = mock_cmd
        from backend.routers import _auth_flows
        await _auth_flows.handle_totp("905001234567", _msg("123456"), session)

    assert session.get("awaiting_totp") is False
    # İlk send_text çağrısı "Doğrulandı" mesajı olmalı
    first_call = mock_msg.send_text.call_args_list[0][0][1]
    assert "Doğrulandı" in first_call


async def test_totp_wrong_sends_fail_message():
    """Yanlış TOTP → hata mesajı, awaiting_totp True kalır."""
    session = _make_session(awaiting_totp=True, pending_command="!restart")
    patcher_m, mock_msg = _patch_messenger()

    mock_perm = MagicMock()
    mock_perm.verify_totp.return_value = False
    with patcher_m, \
         patch("backend.store.sqlite_store.totp_get_lockout",
               AsyncMock(return_value=(0, None))), \
         patch("backend.store.sqlite_store.totp_record_failure",
               AsyncMock(return_value=(1, None))), \
         patch("backend.routers._auth_flows.get_perm_mgr", return_value=mock_perm), \
         patch("backend.routers._auth_flows.log_inbound"), \
         patch("backend.routers._auth_flows.log_outbound"):
        from backend.routers import _auth_flows
        await _auth_flows.handle_totp("905001234567", _msg("000000"), session)

    assert session.get("awaiting_totp") is True
    mock_msg.send_text.assert_awaited_once()
    assert "Geçersiz" in mock_msg.send_text.call_args[0][1]


async def test_totp_lockout_sends_lock_message():
    """Lockout aktifken → kilit mesajı, TOTP doğrulaması yapılmaz."""
    import time
    session = _make_session(awaiting_totp=True, pending_command="!restart")
    patcher_m, mock_msg = _patch_messenger()

    mock_perm = MagicMock()
    with patcher_m, \
         patch("backend.store.sqlite_store.totp_get_lockout",
               AsyncMock(return_value=(3, time.time() + 900))), \
         patch("backend.routers._auth_flows.get_perm_mgr", return_value=mock_perm), \
         patch("backend.routers._auth_flows.log_inbound"), \
         patch("backend.routers._auth_flows.log_outbound"):
        from backend.routers import _auth_flows
        await _auth_flows.handle_totp("905001234567", _msg("123456"), session)

    mock_perm.verify_totp.assert_not_called()
    assert "🔒" in mock_msg.send_text.call_args[0][1]


async def test_totp_brute_force_lockout_triggered():
    """3. hatalı denemede kilit devreye girmeli."""
    import time
    session = _make_session(awaiting_totp=True, pending_command="!restart")
    patcher_m, mock_msg = _patch_messenger()

    mock_perm = MagicMock()
    mock_perm.verify_totp.return_value = False
    with patcher_m, \
         patch("backend.store.sqlite_store.totp_get_lockout",
               AsyncMock(return_value=(0, None))), \
         patch("backend.store.sqlite_store.totp_record_failure",
               AsyncMock(return_value=(3, time.time() + 900))), \
         patch("backend.routers._auth_flows.get_perm_mgr", return_value=mock_perm), \
         patch("backend.routers._auth_flows.log_inbound"), \
         patch("backend.routers._auth_flows.log_outbound"):
        from backend.routers import _auth_flows
        await _auth_flows.handle_totp("905001234567", _msg("000000"), session)

    assert session.get("awaiting_totp") is False  # kilit aktif → False
    assert "🔒" in mock_msg.send_text.call_args[0][1]


