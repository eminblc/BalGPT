"""Platform-bağımsız mesaj dispatch — WhatsApp ve Telegram router'larının ortak giriş noktası.

Sorumluluk (SRP):
  - Mesaj tipine göre yönlendirme: text / interactive / location / sticker / reaction
  - Interactive (buton/liste) yönlendirme ve beta mod proje iletimi

Alt modüller:
  _auth_dispatcher.py — Auth state akışları (math_challenge, admin_totp, totp, guardrail)
  _text_router.py     — Metin yönlendirme (!komutlar, wizard, niyet, Bridge)

OCP-3: Auth state dispatch _AUTH_FLOW_REGISTRY dict ile yönetilir.
  Yeni auth adımı = yeni handler fonksiyonu + _auth_dispatcher._AUTH_FLOW_REGISTRY'ye kayıt.

Bağımlılık yönü: Dispatcher → Guards → Features → Store
"""
from __future__ import annotations

import logging

from ..config import settings
from ..guards import get_session_mgr
from ..guards.runtime_state import is_locked
from ..store.message_logger import log_inbound, log_outbound
from ..adapters.messenger.messenger_factory import get_messenger
from ..i18n import t
from ..app_types import InboundMessage
from ._auth_dispatcher import handle_auth_flow, has_active_auth_flow
from ._text_router import _route_text, _forward_to_bridge

logger = logging.getLogger(__name__)


async def handle_common_message(
    sender: str,
    msg_id: str,
    msg_type: str,
    session: dict,
    inbound: InboundMessage | None = None,
) -> None:
    """Guard zinciri tamamlandıktan sonra çağrılır; platform-bağımsız tüm routing buradadır.

    Args:
        sender:   Gönderen kimliği (WhatsApp numarası veya Telegram chat_id).
        msg_id:   Platform-özel mesaj/update ID (dedup için kullanılmaz; logging için).
        msg_type: "text" | "interactive" | "location" | "sticker" | "reaction" | diğer.
        session:  Mevcut oturum dict'i (session_mgr.get(sender)).
        inbound:  InboundMessage — text, reply_id, extra_desc, raw_payload (REFAC-19).
    """
    inbound      = inbound or {}
    text         = inbound.get("text", "")
    reply_id     = inbound.get("reply_id", "")
    extra_desc   = inbound.get("extra_desc", "")
    raw_payload  = inbound.get("raw_payload")
    context_id   = session.get("active_context", "main")
    messenger    = get_messenger()
    lang         = session.get("lang", "tr")

    # ── Kilit kontrolü ────────────────────────────────────────────────
    if is_locked():
        has_auth_flow = has_active_auth_flow(session)
        is_unlock_cmd = msg_type == "text" and text.strip().lower().startswith("!unlock")
        if not has_auth_flow and not is_unlock_cmd:
            await messenger.send_text(sender, t("lock.locked_msg", lang))
            return

    # ── Auth state akışları (SRP-V2: _auth_dispatcher.handle_auth_flow) ─────
    if await handle_auth_flow(sender, text, msg_type, msg_id, session):
        return

    # ── Mesaj tipine göre yönlendir ───────────────────────────────
    if msg_type == "text":
        if settings.conv_history_enabled:
            log_inbound(msg_id, sender, "text", content=text,
                        context_id=context_id, raw_payload=raw_payload)
        await _route_text(sender, text, session)

    elif msg_type == "interactive":
        if settings.conv_history_enabled:
            log_inbound(msg_id, sender, "interactive", content=reply_id,
                        context_id=context_id, raw_payload=raw_payload)
        # FEAT-4: Araç onayı butonları session kilidini beklemeden hemen işlenmeli.
        # forward_locked zaten kilidi tutuyor olabilir (Bridge yanıtı bekleniyor);
        # lock altında _route_interactive çağırmak deadlock'a yol açar.
        if reply_id.startswith("perm_a:") or reply_id.startswith("perm_d:"):
            short_id   = reply_id[7:]
            allowed    = reply_id.startswith("perm_a:")
            session_id = "main" if context_id == "main" else context_id.replace(":", "_")
            from ._bridge_client import send_permission_response
            await send_permission_response(short_id, session_id, allowed)
            msg_key = "permission.allowed" if allowed else "permission.denied"
            await messenger.send_text(sender, t(msg_key, lang))
            return
        async with get_session_mgr().lock(sender):
            await _route_interactive(sender, reply_id, session)

    elif msg_type == "location":
        if settings.conv_history_enabled:
            log_inbound(msg_id, sender, "location", content=extra_desc,
                        context_id=context_id, raw_payload=raw_payload)
        await _forward_to_bridge(sender, extra_desc, session)

    elif msg_type == "sticker":
        lang = session.get("lang", "tr")
        if settings.conv_history_enabled:
            log_inbound(msg_id, sender, "sticker", content=extra_desc,
                        context_id=context_id, raw_payload=raw_payload)
        await messenger.send_text(sender, t("msg.sticker_ack", lang))
        if settings.conv_history_enabled:
            log_outbound(sender, "text", "sticker_ack", context_id=context_id)

    elif msg_type == "reaction":
        if settings.conv_history_enabled:
            log_inbound(msg_id, sender, "reaction", content=extra_desc,
                        context_id=context_id, raw_payload=raw_payload)
        logger.info("Reaction: sender=%s %s", sender, extra_desc)

    else:
        lang = session.get("lang", "tr")
        logger.info("Desteklenmeyen mesaj tipi: %s sender=%s", msg_type, sender)
        if settings.conv_history_enabled:
            log_inbound(msg_id, sender, msg_type,
                        context_id=context_id, raw_payload=raw_payload)
        await messenger.send_text(sender, t("msg.unsupported_type", lang, msg_type=msg_type))


# ── Interactive yönlendirme ───────────────────────────────────────

async def _route_interactive(sender: str, reply_id: str, session: dict) -> None:
    # REFAC-10: perm_a/perm_d butonları handle_common_message'da önceden işlenir ve return
    # edilir; bu fonksiyona asla ulaşmaz — duplike kontrol kaldırıldı.
    from ..guards.commands import registry as cmd_registry
    from ..features.menu import handle_menu_reply, is_handled_locally

    # Komut kısayolları her zaman yerel olarak işlenir (beta modundan bağımsız).
    _CMD_SHORTCUTS = {
        c.button_id: c.cmd_id
        for cid in cmd_registry.all_ids()
        if hasattr(c := cmd_registry.get(cid), "button_id")
    }
    if reply_id in _CMD_SHORTCUTS:
        await _route_text(sender, _CMD_SHORTCUTS[reply_id], session)
        return

    # Yerel menü handler'ları (project_start_*, project_stop_* vb.) beta modunda da
    # yerel olarak işlenir — böylece servis kapalıyken bile başlatma butonu çalışır.
    project_id = session.get("beta_project_id")
    if project_id and not is_handled_locally(reply_id):
        await _forward_interactive_to_project(sender, reply_id, session, project_id)
        return

    await handle_menu_reply(sender, reply_id, session)


async def _forward_interactive_to_project(
    sender: str, reply_id: str, session: dict, project_id: str
) -> None:
    """Beta modunda interactive buton seçimini projenin FastAPI'sine ilet."""
    import httpx
    from ._bridge_client import _discover_project_api_port

    api_port = await _discover_project_api_port(project_id)
    lang = session.get("lang", "tr")
    if not api_port:
        await get_messenger().send_text(sender, t("dispatcher.project_port_not_found", lang))
        return
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"http://localhost:{api_port}/whatsapp/internal/message",
                json={"sender": sender, "text": "", "reply_id": reply_id},
            )
            r.raise_for_status()
    except Exception:
        await get_messenger().send_text(sender, t("dispatcher.project_connect_error", lang))
