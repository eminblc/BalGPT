"""/cancel — aktif TOTP / doğrulama akışını, bekleyen işlemi veya Bridge sorgusunu iptal et.

TOTP bekleme durumları (awaiting_totp, awaiting_math_challenge,
awaiting_guardrail_confirm) whatsapp_router'da /cancel cancel-word olarak da
yakalanır; bu komut ek güvence olarak residual state'leri de temizler.

FEAT-18: Auth akışı yoksa Bridge'de çalışan aktif sorgu varsa onu da iptal eder.
"""
from __future__ import annotations

import logging

from .registry import registry
from ..permission import Perm

logger = logging.getLogger(__name__)


async def _cancel_bridge_query(session: dict) -> bool:
    """Bridge'deki aktif sorguyu iptal et. Başarılıysa True döner."""
    import httpx
    from ...config import settings

    context    = session.get("active_context", "main")
    session_id = "main" if context == "main" else context.replace(":", "_")

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                f"{settings.claude_bridge_url}/cancel",
                headers={"X-Api-Key": settings.api_key.get_secret_value()},
                json={"session_id": session_id},
            )
            data = r.json()
            return bool(data.get("ok", False))
    except Exception as exc:
        logger.warning("Bridge cancel isteği başarısız: %s", exc)
        return False


class CancelCommand:
    cmd_id      = "/cancel"
    perm   = Perm.OWNER

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        # Residual auth state temizliği (normalde router'da cancel-word dalı yakalar,
        # ama /cancel bu koda ulaştıysa hâlâ kalan state olabilir)
        auth_keys = (
            "awaiting_totp",
            "awaiting_math_challenge",
            "awaiting_guardrail_confirm",
        )
        pending_keys = (
            "pending_command",
            "pending_bridge_message",
            "pending_guardrail_action",
            "math_challenge_answer",
            "math_challenge_command",
            "math_fail_count",
        )

        had_pending = any(session.pop(k, False) for k in auth_keys)

        # Desktop TOTP: _totp_request_sent bayrağını da temizle (DESK-TOTP-2)
        if session.pop("awaiting_desktop_totp", False):
            had_pending = True
            from ...routers._desktop_totp_gate import clear_totp_request_sent
            clear_totp_request_sent()

        for k in pending_keys:
            if session.pop(k, None) is not None:
                had_pending = True

        # Wizard state
        if session.get("wiz_name"):
            from ...features.project_wizard import clear_wizard
            clear_wizard(session)
            had_pending = True

        # TG-WIZ-1: Install wizard SQLite state (chat_id keyed, not session)
        try:
            from ...store.repositories import install_wizard_repo
            iw_state = await install_wizard_repo.get_state(sender)
            if iw_state is not None and iw_state.get("step") != "done":
                await install_wizard_repo.delete_state(sender)
                had_pending = True
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("install_wizard cancel cleanup failed: %s", exc)

        lang = session.get("lang", "tr")

        if had_pending:
            # Auth akışı veya bekleyen işlem vardı — temizlendi
            await get_messenger().send_text(sender, t("cancel.ok", lang))
            return

        # FEAT-18: Auth akışı yoksa → Bridge'de aktif sorgu olup olmadığını kontrol et
        bridge_cancelled = await _cancel_bridge_query(session)
        if bridge_cancelled:
            await get_messenger().send_text(sender, t("cancel.bridge_ok", lang))
            return

        await get_messenger().send_text(sender, t("cancel.nothing", lang))


registry.register(CancelCommand())
