"""Auth state handler'ları ve registry (OCP-3) (SRP).

Sorumluluk: Matematiksel auth, admin TOTP, TOTP, guardrail onayı akışlarını yönetmek.
Genel mesaj dispatch: _dispatcher.py

DIP-V2: handle_auth_flow() ve tüm dahili handler'lar messenger bağımlılığını
parametre olarak alır. Test izolasyonu için mock messenger geçilebilir;
verilmezse get_messenger() lazy fallback çalışır.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from ..guards import get_session_mgr
from ..adapters.messenger import AbstractMessenger
from ..adapters.messenger.messenger_factory import get_messenger
from ..store.message_logger import log_outbound
from ..i18n import t
from . import _auth_flows

logger = logging.getLogger(__name__)

_CANCEL_WORDS = frozenset(("iptal", "cancel", "vazgeç", "/cancel"))


def _messenger(injected: AbstractMessenger | None) -> AbstractMessenger:
    """Enjekte edilen messenger'ı veya singleton fallback'i döndürür."""
    return injected if injected is not None else get_messenger()


async def _handle_math_auth(
    sender: str, text: str, msg_type: str, msg_id: str, session: dict,
    messenger: AbstractMessenger | None = None,
) -> None:
    m = _messenger(messenger)
    lang = session.get("lang", "tr")
    if msg_type == "text" and text.strip().lower() in _CANCEL_WORDS:
        async with get_session_mgr().lock(sender):
            session.clear_math_challenge()
            session.pop("pending_command", None)
            session.pop("pending_bridge_message", None)
        await m.send_text(sender, t("cancel.generic", lang))
        return
    async with get_session_mgr().lock(sender):
        if session.get("awaiting_math_challenge"):
            await _auth_flows.handle_math_challenge(
                sender, {"text": {"body": text}, "id": msg_id}, session
            )


async def _handle_totp_auth(
    sender: str, text: str, msg_type: str, msg_id: str, session: dict,
    messenger: AbstractMessenger | None = None,
) -> None:
    m = _messenger(messenger)
    lang = session.get("lang", "tr")
    if msg_type == "text" and text.strip().lower() in _CANCEL_WORDS:
        async with get_session_mgr().lock(sender):
            session.clear_totp()
        await m.send_text(sender, t("cancel.generic", lang))
        return
    async with get_session_mgr().lock(sender):
        if session.get("awaiting_totp"):
            await _auth_flows.handle_totp(
                sender, {"text": {"body": text}, "id": msg_id}, session
            )


async def _handle_desktop_totp_auth(
    sender: str, text: str, msg_type: str, msg_id: str, session: dict,
    messenger: AbstractMessenger | None = None,
) -> None:
    """Desktop gate TOTP — sunucu tarafı akış (DESK-TOTP-2).

    LLM değil, sunucu TOTP'u yönetir: gate kilitliyse /internal/desktop çağrısında
    sunucu bu session state'i set eder ve WA mesajı gönderir.
    """
    from ._desktop_totp_gate import clear_totp_request_sent

    m = _messenger(messenger)
    lang = session.get("lang", "tr")
    if msg_type == "text" and text.strip().lower() in _CANCEL_WORDS:
        async with get_session_mgr().lock(sender):
            session.clear_desktop_totp()
            clear_totp_request_sent()
        await m.send_text(sender, t("cancel.generic", lang))
        return
    async with get_session_mgr().lock(sender):
        if session.get("awaiting_desktop_totp"):
            await _auth_flows.handle_desktop_totp(
                sender, {"text": {"body": text}, "id": msg_id}, session
            )


async def _handle_guardrail_confirm(
    sender: str, text: str, msg_type: str, msg_id: str, session: dict,
    messenger: AbstractMessenger | None = None,
) -> None:
    m           = _messenger(messenger)
    lang        = session.get("lang", "tr")
    context_id  = session.get("active_context", "main")
    body_lower  = text.strip().lower() if msg_type == "text" else ""

    if body_lower in _CANCEL_WORDS or body_lower in ("hayır", "hayir", "no"):
        async with get_session_mgr().lock(sender):
            session.clear_guardrail()
        await m.send_text(sender, t("cancel.generic", lang))
        log_outbound(sender, "text", "guardrail_cancelled", context_id=context_id)
        return

    if body_lower in ("evet", "yes", "devam", "devam et", "onayla"):
        async with get_session_mgr().lock(sender):
            action = session.pop("pending_guardrail_action", "")
            session.clear_guardrail()
            dict.__setitem__(session, "pending_bridge_message", action)
            session.start_totp(cmd="")
        await m.send_text(sender, t("auth.guardrail.totp_prompt", lang))
        log_outbound(sender, "text", "guardrail_totp_prompt", context_id=context_id)
        return

    await m.send_text(sender, t("auth.guardrail.ask_yn", lang))


# OCP-3: Yeni auth adımı = yeni handler + bu dict'e kayıt. Dispatcher'a dokunma.
_HandlerFn = Callable[..., Coroutine[Any, Any, None]]

_AUTH_FLOW_REGISTRY: dict[str, _HandlerFn] = {
    "awaiting_math_challenge":    _handle_math_auth,
    "awaiting_totp":              _handle_totp_auth,
    "awaiting_guardrail_confirm": _handle_guardrail_confirm,
    # DESK-TOTP-2: Desktop gate TOTP — sunucu tarafı akış
    "awaiting_desktop_totp":      _handle_desktop_totp_auth,
}


def has_active_auth_flow(session: dict) -> bool:
    """Session'da aktif auth state var mı? (kilit bypass kontrolü için)"""
    return any(session.get(k) for k in _AUTH_FLOW_REGISTRY)


async def handle_auth_flow(
    sender: str,
    text: str,
    msg_type: str,
    msg_id: str,
    session: dict,
    messenger: AbstractMessenger | None = None,
) -> bool:
    """Aktif auth state varsa ilgili handler'ı çalıştırır.

    Args:
        messenger: Opsiyonel inject edilmiş messenger. None ise get_messenger() kullanılır.
                   Test izolasyonu için mock messenger geçilebilir.

    Returns:
        True  — auth handler çalıştı; caller return etmeli.
        False — aktif auth state yok; normal dispatch devam etmeli.
    """
    for session_key, auth_handler in _AUTH_FLOW_REGISTRY.items():
        if session.get(session_key):
            await auth_handler(sender, text, msg_type, msg_id, session, messenger)
            return True
    return False
