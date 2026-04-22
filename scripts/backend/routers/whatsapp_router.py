"""WhatsApp webhook router — gelen mesajları alır, context'e göre yönlendirir.

Sorumluluk (SRP):
  - Meta webhook doğrulama (GET) ve HMAC imza kontrolü (POST)
  - Guard zinciri: dedup → blacklist → rate limit → permission
  - Medya işleme: image | audio | video | document (WhatsApp-özel)
  - Metin / interactive / diğer tipler → _dispatcher.handle_common_message
  - /whatsapp/send endpoint'i (Bridge bildirimleri için)

Paylaşılan dispatch mantığı (auth states, _route_text, _route_interactive)
_dispatcher modülündedir; WhatsApp ve Telegram ortak kullanır.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ..config import settings
from ..guards import (
    session_mgr, dedup, blacklist_mgr, rate_limiter, perm_mgr,
    record_status, capability_guard,
    get_session_mgr,
)
from ..guards.api_key import require_api_key
from ..guards.guard_chain import GuardChain, GuardContext
from ..guards.message_guards import (
    DedupMessageGuard, BlacklistMessageGuard,
    OwnerPermissionGuard, RateLimitMessageGuard,
)
from ..guards.session import SessionManager
from ..store.message_logger import log_outbound, _mask_phone
from ..whatsapp.cloud_api import send_text as _wa_send_text
from ..adapters.messenger.messenger_factory import get_messenger
from ..i18n import t
from . import _dispatcher, _media_handlers
from ..app_types import InboundMessage

# OCP-1: guard'lar inject edilen örneklerden oluşan zincir.
# Yeni guard tipi = message_guards.py'e yeni sınıf + buraya kayıt.
# DIP-2: get_guard_chain() provider testi app.dependency_overrides ile override edilebilir.
_guard_chain = GuardChain([
    DedupMessageGuard(dedup),
    BlacklistMessageGuard(blacklist_mgr),
    OwnerPermissionGuard(perm_mgr, settings, get_messenger),
    RateLimitMessageGuard(rate_limiter, get_messenger),
    capability_guard,   # FEAT-3: yetenek kısıtlamaları (owner doğrulandıktan sonra)
])


def get_guard_chain() -> GuardChain:
    """Guard zinciri provider'ı — testlerde app.dependency_overrides ile mock'lanır."""
    return _guard_chain

logger = logging.getLogger(__name__)
router = APIRouter()


# ── /whatsapp/send ────────────────────────────────────────────────
# Bridge'in WhatsApp üzerinden mesaj göndermesi için — WhatsApp'a özgü endpoint.

class _SendRequest(BaseModel):
    to: str
    text: str


@router.post("/send", dependencies=[Depends(require_api_key)])
async def send_endpoint(req: _SendRequest):
    """Bridge'in WhatsApp mesajı göndermesi için."""
    record_status(req.to, req.text)
    await _wa_send_text(req.to, req.text)
    if settings.conv_history_enabled:
        log_outbound(req.to, "text", req.text, context_id="api")
    return {"status": "ok"}


# ── Webhook doğrulama (GET) ───────────────────────────────────────

@router.get("/webhook")
async def verify_webhook(request: Request):
    params = request.query_params
    if (params.get("hub.mode") == "subscribe"
            and secrets.compare_digest(
                params.get("hub.verify_token", ""),
                settings.whatsapp_verify_token,
            )):
        logger.info("Webhook doğrulandı")
        return PlainTextResponse(params.get("hub.challenge", ""))
    logger.warning("Webhook doğrulama başarısız")
    raise HTTPException(status_code=403, detail="Doğrulama başarısız")


# ── Webhook (POST) ────────────────────────────────────────────────

@router.post("/webhook")
async def receive_webhook(
    request: Request,
    guard_chain: GuardChain = Depends(get_guard_chain),
    s_mgr: SessionManager = Depends(get_session_mgr),
):
    raw_body = await request.body()
    sig = request.headers.get("X-Hub-Signature-256", "")
    if not _verify_signature(raw_body, sig):
        logger.warning("Geçersiz webhook imzası")
        raise HTTPException(status_code=403, detail="İmza geçersiz")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Geçersiz JSON")

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                try:
                    await _handle_message(
                        msg, value, raw_payload=payload,
                        guard_chain=guard_chain, s_mgr=s_mgr,
                    )
                except Exception as exc:
                    sender = msg.get("from", "")
                    logger.exception(
                        "Mesaj işlenirken beklenmedik hata: sender=%s exc=%s",
                        _mask_phone(sender), exc,
                    )
                    if sender:
                        try:
                            session = s_mgr.get(sender)
                            lang    = session.get("lang", "tr") if session else "tr"
                            await get_messenger().send_text(
                                sender,
                                t("msg.error", lang),
                            )
                        except Exception:
                            pass

    return {"status": "ok"}


def _verify_signature(body: bytes, sig_header: str) -> bool:
    if not settings.whatsapp_app_secret:
        if settings.environment == "production":
            logger.critical("whatsapp_app_secret tanımlı değil — production'da HMAC doğrulaması zorunlu, istek reddedildi")
            return False
        logger.warning("whatsapp_app_secret tanımlı değil — geliştirme modunda HMAC atlanıyor")
        return True
    if not sig_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        settings.whatsapp_app_secret.get_secret_value().encode(), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, sig_header)


# ── Mesaj işleyici ────────────────────────────────────────────────

async def _handle_message(
    msg: dict,
    value: dict,
    raw_payload: dict | None = None,
    *,
    guard_chain: GuardChain,
    s_mgr: SessionManager,
) -> None:
    sender   = msg.get("from", "")
    msg_id   = msg.get("id", "")
    msg_type = msg.get("type", "")

    logger.debug(
        "MSG_RECEIVED sender=%s type=%s id=%s",
        _mask_phone(sender), msg_type, msg_id,
    )

    # OCP-1: guard zinciri — yeni guard tipi router'a dokunmadan eklenir
    # DIP-2: guard_chain ve s_mgr inject edildi; testlerde mock'lanabilir
    session = s_mgr.get(sender)
    lang    = session.get("lang", settings.default_language) if session else settings.default_language
    ctx     = GuardContext(sender=sender, msg_id=msg_id, msg_type=msg_type, msg=msg, lang=lang)
    if not (await guard_chain.check(ctx)).passed:
        return

    # ── WhatsApp-özel medya tipleri ───────────────────────────────
    if msg_type == "image":
        await _media_handlers.handle_image(sender, msg_id, msg, session, raw_payload)
        return
    if msg_type == "audio":
        await _media_handlers.handle_audio(sender, msg_id, msg, session, raw_payload)
        return
    if msg_type == "video":
        await _media_handlers.handle_video(sender, msg_id, msg, session, raw_payload)
        return
    if msg_type == "document":
        await _media_handlers.handle_document(sender, msg_id, msg, session, raw_payload)
        return

    # ── Ortak dispatch: text | interactive | location | sticker | reaction | diğer ──
    text     = msg.get("text", {}).get("body", "").strip() if msg_type == "text" else ""
    reply_id = ""
    if msg_type == "interactive":
        sub      = msg.get("interactive", {})
        sub_data = sub.get("button_reply") or sub.get("list_reply") or {}
        reply_id = sub_data.get("id", "")

    extra_desc = ""
    if msg_type == "location":
        from ..features.media_handler import handle_location
        extra_desc = handle_location(msg)
    elif msg_type == "sticker":
        from ..features.media_handler import handle_sticker
        extra_desc = handle_sticker(msg)
    elif msg_type == "reaction":
        from ..features.media_handler import handle_reaction
        extra_desc = handle_reaction(msg)

    await _dispatcher.handle_common_message(
        sender, msg_id, msg_type, session,
        InboundMessage(text=text, reply_id=reply_id, extra_desc=extra_desc, raw_payload=raw_payload),
    )
