"""_dispatcher.py — auth akışı handler'ları ve _AUTH_FLOW_REGISTRY testleri (OCP-3).

Dispatcher'ın tüm dış bağımlılıkları (messenger, session_mgr, _auth_flows) mock'lanır;
böylece routing mantığı izole edilmiş şekilde test edilir.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from backend.app_types import SessionState, InboundMessage


# ── Yardımcılar ───────────────────────────────────────────────────

def _make_session(**kwargs) -> SessionState:
    defaults = dict(
        active_context="main",
        awaiting_totp=False,
        awaiting_math_challenge=False,
        awaiting_guardrail_confirm=False,
        pending_command="",
        menu_page=0,
    )
    defaults.update(kwargs)
    return SessionState(**defaults)


def _patch_messenger():
    """get_messenger() → AsyncMock; hem _dispatcher hem _auth_dispatcher'da yamalanır."""
    from contextlib import ExitStack
    mock = AsyncMock()

    class _CM:
        def __enter__(self):
            self._stack = ExitStack()
            self._stack.enter_context(
                patch("backend.routers._dispatcher.get_messenger", return_value=mock)
            )
            self._stack.enter_context(
                patch("backend.routers._auth_dispatcher.get_messenger", return_value=mock)
            )
            return self

        def __exit__(self, *args):
            return self._stack.__exit__(*args)

    return _CM(), mock


# ── _AUTH_FLOW_REGISTRY ───────────────────────────────────────────

def test_registry_contains_all_keys():
    from backend.routers._auth_dispatcher import _AUTH_FLOW_REGISTRY
    expected = {
        "awaiting_math_challenge",
        "awaiting_totp",
        "awaiting_guardrail_confirm",
        "awaiting_desktop_totp",  # DESK-TOTP-2
    }
    assert set(_AUTH_FLOW_REGISTRY.keys()) == expected


def test_registry_values_are_callable():
    from backend.routers._auth_dispatcher import _AUTH_FLOW_REGISTRY
    for key, handler in _AUTH_FLOW_REGISTRY.items():
        assert callable(handler), f"{key} handler callable değil"


# ── handle_common_message: auth state routing ─────────────────────

@pytest.mark.asyncio
async def test_awaiting_totp_skips_text_routing():
    """awaiting_totp=True → _route_text çağrılmamalı (auth handler devralır)."""
    session = _make_session(awaiting_totp=True, pending_command="/restart")

    mock_route_text = AsyncMock()
    mock_handle_totp = AsyncMock()
    patcher_m, _ = _patch_messenger()

    # _AUTH_FLOW_REGISTRY zaten import zamanında oluşturuldu; patch yerine
    # _auth_flows.handle_totp'u patch'le — handler'ın gerçekte ne çağırdığını test et
    mock_smgr = MagicMock()
    mock_lock = MagicMock()
    mock_lock.__aenter__ = AsyncMock(return_value=None)
    mock_lock.__aexit__ = AsyncMock(return_value=False)
    mock_smgr.lock.return_value = mock_lock
    with patcher_m, \
         patch("backend.routers._dispatcher._route_text", mock_route_text), \
         patch("backend.routers._auth_flows.handle_totp", mock_handle_totp), \
         patch("backend.routers._dispatcher.log_inbound"), \
         patch("backend.routers._dispatcher.get_session_mgr", return_value=mock_smgr):
        from backend.routers import _dispatcher
        await _dispatcher.handle_common_message(
            "905001234567", "msg-001", "text", session, InboundMessage(text="123456")
        )

    # text routing bypass edildi
    mock_route_text.assert_not_awaited()
    # gerçek totp handler çağrıldı
    mock_handle_totp.assert_awaited_once()


@pytest.mark.asyncio
async def test_awaiting_math_skips_text_routing():
    """awaiting_math_challenge=True → _route_text çağrılmamalı."""
    session = _make_session(awaiting_math_challenge=True, math_challenge_answer=42)

    mock_route_text = AsyncMock()
    mock_handle_math = AsyncMock()
    patcher_m, _ = _patch_messenger()

    mock_smgr = MagicMock()
    mock_lock = MagicMock()
    mock_lock.__aenter__ = AsyncMock(return_value=None)
    mock_lock.__aexit__ = AsyncMock(return_value=False)
    mock_smgr.lock.return_value = mock_lock
    with patcher_m, \
         patch("backend.routers._dispatcher._route_text", mock_route_text), \
         patch("backend.routers._auth_flows.handle_math_challenge", mock_handle_math), \
         patch("backend.routers._dispatcher.log_inbound"), \
         patch("backend.routers._dispatcher.get_session_mgr", return_value=mock_smgr):
        from backend.routers import _dispatcher
        await _dispatcher.handle_common_message(
            "905001234567", "msg-001", "text", session, InboundMessage(text="42")
        )

    mock_route_text.assert_not_awaited()
    mock_handle_math.assert_awaited_once()


@pytest.mark.asyncio
async def test_awaiting_guardrail_skips_text_routing():
    """awaiting_guardrail_confirm=True → _route_text çağrılmamalı; yanıt istenir."""
    # Belirsiz yanıt gönder → guardrail handler yanıt sorar ama route_text'e gitmez
    session = _make_session(awaiting_guardrail_confirm=True, pending_guardrail_action="test")

    mock_route_text = AsyncMock()
    patcher_m, mock_msg = _patch_messenger()

    mock_lock = MagicMock()
    mock_lock.__aenter__ = AsyncMock(return_value=None)
    mock_lock.__aexit__ = AsyncMock(return_value=False)

    mock_smgr = MagicMock()
    mock_smgr.lock.return_value = mock_lock
    with patcher_m, \
         patch("backend.routers._dispatcher._route_text", mock_route_text), \
         patch("backend.routers._dispatcher.log_inbound"), \
         patch("backend.routers._dispatcher.log_outbound"), \
         patch("backend.routers._auth_dispatcher.log_outbound"), \
         patch("backend.routers._dispatcher.get_session_mgr", return_value=mock_smgr), \
         patch("backend.routers._auth_dispatcher.get_session_mgr", return_value=mock_smgr):
        from backend.routers import _dispatcher
        await _dispatcher.handle_common_message(
            "905001234567", "msg-001", "text", session, InboundMessage(text="belki")
        )

    mock_route_text.assert_not_awaited()
    # guardrail handler yanıt beklediğini bildiriyor
    mock_msg.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_no_auth_state_routes_to_text(monkeypatch):
    """Auth state yok → _route_text çağrılmalı."""
    session = _make_session()

    mock_route_text = AsyncMock()
    patcher_m, _ = _patch_messenger()

    with patcher_m, \
         patch("backend.routers._dispatcher._route_text", mock_route_text), \
         patch("backend.routers._dispatcher.log_inbound"), \
         patch("backend.routers._dispatcher.is_locked", return_value=False):
        from backend.routers import _dispatcher
        await _dispatcher.handle_common_message(
            "905001234567", "msg-001", "text", session, InboundMessage(text="merhaba")
        )

    mock_route_text.assert_awaited_once_with("905001234567", "merhaba", session)


# ── Cancel sözcükleri ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_word_clears_totp_state():
    """!cancel geldiğinde TOTP akışı iptal edilmeli."""
    session = _make_session(awaiting_totp=True, pending_command="/restart")

    patcher_m, mock_msg = _patch_messenger()
    mock_lock = MagicMock()
    mock_lock.__aenter__ = AsyncMock(return_value=None)
    mock_lock.__aexit__ = AsyncMock(return_value=False)
    mock_session_mgr = MagicMock()
    mock_session_mgr.lock.return_value = mock_lock

    with patcher_m, \
         patch("backend.routers._dispatcher.get_session_mgr", return_value=mock_session_mgr), \
         patch("backend.routers._auth_dispatcher.get_session_mgr", return_value=mock_session_mgr), \
         patch("backend.routers._dispatcher.log_inbound"):
        from backend.routers import _dispatcher
        await _dispatcher.handle_common_message(
            "905001234567", "msg-001", "text", session, InboundMessage(text="/cancel")
        )

    assert session.get("awaiting_totp") is False
    mock_msg.send_text.assert_awaited_once()
    assert "iptal" in mock_msg.send_text.call_args[0][1]


@pytest.mark.asyncio
async def test_cancel_word_clears_totp_state():
    session = _make_session(awaiting_totp=True, pending_command="!shutdown")

    patcher_m, mock_msg = _patch_messenger()
    mock_lock = MagicMock()
    mock_lock.__aenter__ = AsyncMock(return_value=None)
    mock_lock.__aexit__ = AsyncMock(return_value=False)
    mock_session_mgr = MagicMock()
    mock_session_mgr.lock.return_value = mock_lock

    with patcher_m, \
         patch("backend.routers._dispatcher.get_session_mgr", return_value=mock_session_mgr), \
         patch("backend.routers._auth_dispatcher.get_session_mgr", return_value=mock_session_mgr), \
         patch("backend.routers._dispatcher.log_inbound"):
        from backend.routers import _dispatcher
        await _dispatcher.handle_common_message(
            "905001234567", "msg-001", "text", session, InboundMessage(text="iptal")
        )

    assert session.get("awaiting_totp") is False
    mock_msg.send_text.assert_awaited_once()


# ── Guardrail confirm handler ─────────────────────────────────────

@pytest.mark.asyncio
async def test_guardrail_no_answer_prompts_again():
    """Belirsiz yanıt → evet/hayır tekrar istenmeli."""
    session = _make_session(awaiting_guardrail_confirm=True, pending_guardrail_action="test action")

    patcher_m, mock_msg = _patch_messenger()
    mock_lock = MagicMock()
    mock_lock.__aenter__ = AsyncMock(return_value=None)
    mock_lock.__aexit__ = AsyncMock(return_value=False)
    mock_session_mgr = MagicMock()
    mock_session_mgr.lock.return_value = mock_lock

    with patcher_m, \
         patch("backend.routers._dispatcher.get_session_mgr", return_value=mock_session_mgr), \
         patch("backend.routers._auth_dispatcher.get_session_mgr", return_value=mock_session_mgr), \
         patch("backend.routers._dispatcher.log_inbound"), \
         patch("backend.routers._dispatcher.log_outbound"), \
         patch("backend.routers._auth_dispatcher.log_outbound"):
        from backend.routers import _dispatcher
        await _dispatcher.handle_common_message(
            "905001234567", "msg-001", "text", session, InboundMessage(text="belki")
        )

    # session hâlâ guardrail bekliyor
    assert session.get("awaiting_guardrail_confirm") is True
    mock_msg.send_text.assert_awaited_once()
    assert "evet" in mock_msg.send_text.call_args[0][1]


@pytest.mark.asyncio
async def test_guardrail_yes_transitions_to_owner_totp():
    """evet yanıtı → owner TOTP akışına geçmeli."""
    session = _make_session(awaiting_guardrail_confirm=True, pending_guardrail_action="rm -rf /tmp/x")

    patcher_m, mock_msg = _patch_messenger()
    mock_lock = MagicMock()
    mock_lock.__aenter__ = AsyncMock(return_value=None)
    mock_lock.__aexit__ = AsyncMock(return_value=False)
    mock_session_mgr = MagicMock()
    mock_session_mgr.lock.return_value = mock_lock

    with patcher_m, \
         patch("backend.routers._dispatcher.get_session_mgr", return_value=mock_session_mgr), \
         patch("backend.routers._auth_dispatcher.get_session_mgr", return_value=mock_session_mgr), \
         patch("backend.routers._dispatcher.log_inbound"), \
         patch("backend.routers._dispatcher.log_outbound"), \
         patch("backend.routers._auth_dispatcher.log_outbound"):
        from backend.routers import _dispatcher
        await _dispatcher.handle_common_message(
            "905001234567", "msg-001", "text", session, InboundMessage(text="evet")
        )

    assert session.get("awaiting_guardrail_confirm") is False
    assert session.get("awaiting_totp") is True
    assert session.get("pending_bridge_message") == "rm -rf /tmp/x"
    mock_msg.send_text.assert_awaited_once()
    assert "TOTP" in mock_msg.send_text.call_args[0][1]


# ── Mesaj tipi routing ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sticker_message_sends_ack():
    session = _make_session()
    patcher_m, mock_msg = _patch_messenger()

    with patcher_m, \
         patch("backend.routers._dispatcher.log_inbound"), \
         patch("backend.routers._dispatcher.log_outbound"), \
         patch("backend.routers._dispatcher.is_locked", return_value=False):
        from backend.routers import _dispatcher
        await _dispatcher.handle_common_message(
            "905001234567", "msg-001", "sticker", session, InboundMessage(extra_desc="🎉")
        )

    mock_msg.send_text.assert_awaited_once()
    assert "Sticker" in mock_msg.send_text.call_args[0][1]


@pytest.mark.asyncio
async def test_unknown_message_type_sends_warning():
    session = _make_session()
    patcher_m, mock_msg = _patch_messenger()

    with patcher_m, \
         patch("backend.routers._dispatcher.log_inbound"), \
         patch("backend.routers._dispatcher.is_locked", return_value=False):
        from backend.routers import _dispatcher
        await _dispatcher.handle_common_message(
            "905001234567", "msg-001", "unknown_type", session
        )

    mock_msg.send_text.assert_awaited_once()
    assert "unknown_type" in mock_msg.send_text.call_args[0][1]
