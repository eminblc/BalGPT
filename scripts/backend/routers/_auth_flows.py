"""TOTP ve matematik challenge doğrulama akışları — whatsapp_router'dan ayrıştırıldı (REF-3).

Sorumluluk (SRP):
  - Matematik challenge yanıtını doğrulama (_handle_math_challenge)
  - Sahip TOTP doğrulaması (_handle_totp)

Bağımlılık yönü: Auth flows → Bridge client (forward_locked)
Döngüsel import önleme: _bridge_client.forward_locked doğrudan çağrılır.
"""
from __future__ import annotations

import logging
import time

from ..guards import get_perm_mgr
from ..guards.commands import registry as cmd_registry
from ..store.message_logger import log_inbound, log_outbound, _mask_phone
from ..adapters.messenger.messenger_factory import get_messenger
from ..i18n import t

from ..constants import TOTP_MAX_ATTEMPTS, MATH_MAX_ATTEMPTS

logger = logging.getLogger(__name__)


# ── Yardımcı ──────────────────────────────────────────────────────

def clear_math_state(session: dict) -> None:
    """Matematik challenge durumunu temizle — SessionState.clear_math_challenge() wrapper."""
    session.clear_math_challenge()


# ── Matematik challenge ────────────────────────────────────────────

async def handle_math_challenge(sender: str, msg: dict, session: dict) -> None:
    """Matematik challenge yanıtını doğrula.

    Doğruysa TOTP adımına geç. Yanlışsa sayacı artır, 3 hatada iptal et.
    Bu adım prompt injection alarm zili işlevi görür.
    """
    from . import _bridge_client  # döngüsel import önleme — geç içe aktarım
    context_id = session.get("active_context", "main")
    lang       = session.get("lang", "tr")
    user_input = msg.get("text", {}).get("body", "").strip()

    try:
        user_answer = int(user_input)
    except ValueError:
        fail = session.get("math_fail_count", 0) + 1
        session["math_fail_count"] = fail
        remaining = MATH_MAX_ATTEMPTS - fail
        if remaining <= 0:
            session.clear_math_challenge()
            await get_messenger().send_text(sender, t("auth.math.too_many", lang))
            log_outbound(sender, "text", "math_cancelled", context_id=context_id)
        else:
            await get_messenger().send_text(sender, t("auth.math.invalid_input", lang, remaining=remaining))
            log_outbound(sender, "text", "math_invalid_input", context_id=context_id)
        return

    expected = session.get("math_challenge_answer", -1)
    if user_answer == expected:
        cmd = session.get("math_challenge_command", "")
        session.clear_math_challenge()
        session.start_totp(cmd=cmd)
        await get_messenger().send_text(sender, t("auth.math.ok", lang))
        log_outbound(sender, "text", "math_ok_totp_prompt", context_id=context_id)
    else:
        fail = session.get("math_fail_count", 0) + 1
        session["math_fail_count"] = fail
        remaining = MATH_MAX_ATTEMPTS - fail
        if remaining <= 0:
            session.clear_math_challenge()
            await get_messenger().send_text(sender, t("auth.math.too_many_wrong", lang))
            log_outbound(sender, "text", "math_cancelled", context_id=context_id)
        else:
            await get_messenger().send_text(sender, t("auth.math.wrong", lang, remaining=remaining))
            log_outbound(sender, "text", "math_wrong", context_id=context_id)


# ── Sahip TOTP ─────────────────────────────────────────────────────

async def handle_totp(sender: str, msg: dict, session: dict) -> None:
    """Sahip TOTP doğrulaması."""
    from . import _bridge_client  # döngüsel import önleme — geç içe aktarım
    from ..store.sqlite_wrapper import store as db  # DIP: wrapper üzerinden erişim
    context_id = session.get("active_context", "main")
    lang       = session.get("lang", "tr")

    _, lockout_until = await db.totp_get_lockout(sender, "owner")
    if lockout_until and time.time() < lockout_until:
        remaining = int(lockout_until - time.time())
        await get_messenger().send_text(sender, t("auth.totp.locked", lang, minutes=remaining // 60 + 1))
        log_outbound(sender, "text", "totp_locked", context_id=context_id)
        return

    code = msg.get("text", {}).get("body", "").strip()
    log_inbound(msg.get("id", ""), sender, "totp", content="[REDACTED]",
                context_id=context_id)

    if get_perm_mgr().verify_totp(code):
        pending        = session.pop("pending_command", "")   # clear_totp'tan önce al
        pending_bridge = session.pop("pending_bridge_message", "")
        _saved_terminal_cmd = session.pop("_terminal_pending_cmd", None)
        session.clear_totp()
        await db.totp_reset_lockout(sender, "owner")
        await get_messenger().send_text(sender, t("auth.totp.ok", lang))
        log_outbound(sender, "text", "totp_ok", context_id=context_id)
        if pending:
            cmd     = pending.split()[0].lower()
            command = cmd_registry.get(cmd)
            if command:
                if _saved_terminal_cmd is not None:
                    session.set_terminal_pending(_saved_terminal_cmd)
                arg = pending[len(cmd):].strip()
                await command.execute(sender, arg, session)
            else:
                await _bridge_client.forward_locked(sender, pending, session)
        elif pending_bridge:
            logger.info("Onaylı bridge mesajı iletiliyor: '%s'", pending_bridge[:40])
            await _bridge_client.forward_locked(sender, pending_bridge, session)
    else:
        fail_count, locked_until = await db.totp_record_failure(sender, "owner")
        if locked_until:
            session.clear_totp()
            logger.warning("TOTP brute-force kilidi: sender=%s", _mask_phone(sender))
            await get_messenger().send_text(sender, t("auth.totp.lockout", lang))
            log_outbound(sender, "text", "totp_lockout", context_id=context_id)
        else:
            remaining_tries = TOTP_MAX_ATTEMPTS - fail_count
            await get_messenger().send_text(sender, t("auth.totp.invalid", lang, remaining=remaining_tries))
            log_outbound(sender, "text", "totp_fail", context_id=context_id)
            # awaiting_totp True kalır — kullanıcı tekrar deneyebilir


# ── Desktop TOTP (DESK-TOTP-2) ─────────────────────────────────────

async def handle_desktop_totp(sender: str, msg: dict, session: dict) -> None:
    """Desktop gate TOTP doğrulaması — sunucu tarafından yönetilir, LLM dahil değil.

    Başarılı doğrulamadan sonra gate TTL boyunca açılır; kullanıcı desktop işlemini
    tekrar istediğinde LLM direkt endpoint'i çağırır (TOTP sormadan).
    """
    from ._desktop_totp_gate import get_desktop_totp_gate, clear_totp_request_sent

    lang = session.get("lang", "tr")
    code = msg.get("text", {}).get("body", "").strip()
    log_inbound(msg.get("id", ""), sender, "desktop_totp", content="[REDACTED]")

    gate = get_desktop_totp_gate()
    valid, lockout_remaining = await gate.try_unlock(code)

    if valid:
        session.clear_desktop_totp()
        clear_totp_request_sent()
        ttl_min = int(gate.ttl_seconds) // 60
        await get_messenger().send_text(
            sender,
            t("auth.desktop_totp.ok", lang, minutes=ttl_min),
        )
        log_outbound(sender, "text", "desktop_totp_ok")
    elif lockout_remaining is not None:
        mins = max(1, lockout_remaining // 60)
        session.clear_desktop_totp()
        clear_totp_request_sent()
        await get_messenger().send_text(
            sender,
            t("auth.desktop_totp.lockout", lang, minutes=mins),
        )
        log_outbound(sender, "text", "desktop_totp_lockout")
    else:
        # awaiting_desktop_totp True kalır — kullanıcı tekrar deneyebilir
        await get_messenger().send_text(
            sender,
            t("auth.desktop_totp.invalid", lang),
        )
        log_outbound(sender, "text", "desktop_totp_fail")
