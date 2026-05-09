"""Telegram webhook router — gelen güncellemeleri alır, dispatcher'a yönlendirir.

Sorumluluk (SRP):
  - Telegram Update payload parse (message + callback_query)
  - Webhook güvenlik doğrulaması (X-Telegram-Bot-Api-Secret-Token)
  - Guard zinciri: dedup → blacklist → permission → rate limit → capability (GuardChain)
  - Callback query yanıtlama (answerCallbackQuery — buton spinner'ını kaldırır)
  - Metin / interactive → _dispatcher.handle_common_message
  - /telegram/send endpoint'i (Bridge bildirimleri için)

Paylaşılan dispatch mantığı (auth states, _route_text, _route_interactive)
_dispatcher modülündedir; WhatsApp ve Telegram ortak kullanır.

Telegram Update formatı:
  message.from.id         → sender (chat_id olarak str'e çevrilir)
  update_id               → msg_id (dedup için)
  message.text            → text
  callback_query.data     → reply_id (buton seçimi)
  callback_query.id       → answerCallbackQuery için gerekli
"""
from __future__ import annotations

import logging
import secrets

import httpx
from fastapi import APIRouter, Depends, Request, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..services.telegram_command_sync import build_tg_command_map
from ..guards import (
    blacklist_mgr, rate_limiter, perm_mgr, dedup,
    record_status, capability_guard,
    get_session_mgr,
)
from ..guards.guard_chain import GuardChain, GuardContext as _GuardContext
from ..guards.message_guards import (
    DedupMessageGuard, BlacklistMessageGuard,
    OwnerPermissionGuard, RateLimitMessageGuard,
)
from ..guards.session import SessionManager
from ..guards.api_key import require_api_key
from ..store.message_logger import log_outbound, _mask_phone
from ..adapters.messenger.messenger_factory import get_messenger
from ..i18n import t
from . import _dispatcher
from ..app_types import InboundMessage

logger = logging.getLogger(__name__)
router = APIRouter()

def _resolve_tg_command(text: str) -> str:
    """Telegram slash komutunu /komut formatına çevirir.

    '/root_reset arg' → '/root-reset arg'
    '/help'           → '/help'
    '/start'          → '/help'
    Slash ile başlamayan metinler değişmeden döner.
    """
    if not text.startswith("/"):
        return text
    tg_map = build_tg_command_map()  # lru_cache — ilk çağrıdan sonra bedava
    parts = text[1:].split(None, 1)
    tg_name = parts[0].lower().split("@")[0]  # /cmd@botname → cmd
    cmd_id = tg_map.get(tg_name)
    remainder = (" " + parts[1]) if len(parts) > 1 else ""
    if cmd_id:
        return cmd_id + remainder
    return "/" + tg_name.replace("_", "-") + remainder

# OCP-1: guard'lar inject edilen örneklerden oluşan zincir — WhatsApp router ile simetrik.
# Telegram'a özgü fark: notification_target olarak telegram_chat_id kullanılır.
_guard_chain = GuardChain([
    DedupMessageGuard(dedup),
    BlacklistMessageGuard(blacklist_mgr),
    OwnerPermissionGuard(perm_mgr, settings, get_messenger, notification_target=settings.telegram_chat_id),
    RateLimitMessageGuard(rate_limiter, get_messenger),
    capability_guard,   # FEAT-3: yetenek kısıtlamaları (owner doğrulandıktan sonra)
])


def get_guard_chain() -> GuardChain:
    """Guard zinciri provider'ı — testlerde app.dependency_overrides ile mock'lanır."""
    return _guard_chain


# ── /telegram/send ────────────────────────────────────────────────
# Bridge'in Telegram üzerinden mesaj göndermesi için (MESSENGER_TYPE=telegram iken aktif).

class _SendRequest(BaseModel):
    to: str
    text: str


@router.post("/send", dependencies=[Depends(require_api_key)])
async def send_endpoint(req: _SendRequest):
    """Bridge'in Telegram mesajı göndermesi için."""
    record_status(req.to, req.text)
    await get_messenger().send_text(req.to, req.text)
    if settings.conv_history_enabled:
        log_outbound(req.to, "text", req.text, context_id="api")
    return {"status": "ok"}


# ── Webhook (POST) ────────────────────────────────────────────────

@router.post("/webhook")
async def receive_webhook(
    request: Request,
    guard_chain: GuardChain = Depends(get_guard_chain),
    s_mgr: SessionManager = Depends(get_session_mgr),
):
    """Telegram Bot API'nin POST ettiği Update nesnelerini alır.

    Güvenlik: TELEGRAM_WEBHOOK_SECRET ayarlandıysa
    X-Telegram-Bot-Api-Secret-Token header'ı doğrulanır.
    Ayarlanmadıysa geliştirme modunda atlanır; production'da uyarı loglanır.
    """
    _verify_secret(request)

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Geçersiz JSON")

    try:
        await _handle_update(payload, guard_chain=guard_chain, s_mgr=s_mgr)
    except Exception as exc:
        logger.exception("Telegram update işlenirken beklenmedik hata: %s", exc)

    # Telegram 200 dışı yanıt alırsa güncellemeyi yeniden gönderir — her zaman 200 dön.
    return {"ok": True}


def _verify_secret(request: Request) -> None:
    """Telegram webhook secret token doğrulaması."""
    secret = settings.telegram_webhook_secret.get_secret_value()
    if not secret:
        if settings.environment == "production":
            logger.error(
                "GÜVENLIK: telegram_webhook_secret tanımlı değil — "
                "production'da webhook isteği reddedildi!"
            )
            raise HTTPException(status_code=403, detail="Webhook koruması yapılandırılmamış")
        return  # geliştirme modunda atla

    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not secrets.compare_digest(token, secret):
        logger.warning("Geçersiz Telegram webhook secret token")
        raise HTTPException(status_code=403, detail="Geçersiz secret token")


# ── Update işleyici ───────────────────────────────────────────────

async def _handle_update(
    update: dict,
    *,
    guard_chain: GuardChain,
    s_mgr: SessionManager,
) -> None:
    """Telegram Update nesnesini parse ederek guard zincirinden geçirir."""
    update_id = str(update.get("update_id", ""))

    # ── message: düz metin veya diğer içerik ──────────────────────
    if "message" in update:
        msg    = update["message"]
        sender = str(msg.get("from", {}).get("id", ""))
        if not sender:
            logger.debug("Telegram update'te from.id yok, atlanıyor")
            return

        msg_type   = _classify_tg_message(msg)
        text       = msg.get("text", "").strip() if msg_type == "text" else ""
        text       = _resolve_tg_command(text)
        extra_desc = _describe_tg_media(msg, msg_type)
        file_id    = _extract_tg_file_id(msg, msg_type)
        raw_payload = {**update, "tg_file_id": file_id} if file_id else update

        await _process(
            sender=sender,
            msg_id=f"tg_{update_id}",
            msg_type=msg_type,
            text=text,
            reply_id="",
            extra_desc=extra_desc,
            raw_payload=raw_payload,
            guard_chain=guard_chain,
            s_mgr=s_mgr,
        )

    # ── callback_query: inline buton tıklaması ────────────────────
    elif "callback_query" in update:
        cq     = update["callback_query"]
        sender = str(cq.get("from", {}).get("id", ""))
        if not sender:
            return

        callback_id = cq.get("id", "")
        reply_id    = cq.get("data", "")

        # Telegram'a callback yanıtı gönder (buton spinner'ını kaldırır)
        await _answer_callback(callback_id)

        await _process(
            sender=sender,
            msg_id=f"tg_{update_id}",
            msg_type="interactive",
            text="",
            reply_id=reply_id,
            extra_desc="",
            raw_payload=update,
            guard_chain=guard_chain,
            s_mgr=s_mgr,
        )

    else:
        logger.debug("Bilinmeyen Telegram update tipi: %s", list(update.keys()))


async def _process(
    sender: str,
    msg_id: str,
    msg_type: str,
    text: str,
    reply_id: str,
    extra_desc: str,
    raw_payload: dict | None,
    *,
    guard_chain: GuardChain,
    s_mgr: SessionManager,
) -> None:
    """Guard zinciri + dispatcher çağrısı."""
    logger.debug(
        "TG_MSG sender=%s type=%s id=%s",
        _mask_phone(sender), msg_type, msg_id,
    )

    # Guard zinciri — session tek seferinde alınır; tüm guard'lar ve dispatcher paylaşır
    session = s_mgr.get(sender)
    lang    = session.get("lang", "tr") if session else "tr"

    ctx = _GuardContext(
        sender=sender, msg_id=msg_id, msg_type=msg_type,
        msg={"text": {"body": text}},
        lang=lang,
    )
    if not (await guard_chain.check(ctx)).passed:
        return

    await _dispatcher.handle_common_message(
        sender, msg_id, msg_type, session,
        InboundMessage(text=text, reply_id=reply_id, extra_desc=extra_desc, raw_payload=raw_payload),
    )


# ── Telegram yardımcıları ─────────────────────────────────────────

def _classify_tg_message(msg: dict) -> str:
    """Telegram message nesnesinden platform-bağımsız msg_type üretir."""
    if "text" in msg:
        return "text"
    if "photo" in msg:
        return "image"
    if "voice" in msg or "audio" in msg:
        return "audio"
    if "video" in msg:
        return "video"
    if "document" in msg:
        return "document"
    if "location" in msg:
        return "location"
    if "sticker" in msg:
        return "sticker"
    return "unknown"


def _extract_tg_file_id(msg: dict, msg_type: str) -> str | None:
    """Telegram message nesnesinden file_id çıkar; medya olmayan tiplerde None döner."""
    if msg_type == "image":
        photos = msg.get("photo", [])
        return photos[-1]["file_id"] if photos else None
    if msg_type == "audio":
        media_obj = msg.get("voice") or msg.get("audio")
        return (media_obj or {}).get("file_id")
    if msg_type == "video":
        return (msg.get("video") or {}).get("file_id")
    if msg_type == "document":
        return (msg.get("document") or {}).get("file_id")
    return None


def _describe_tg_media(msg: dict, msg_type: str) -> str:
    """Medya içeren Telegram mesajları için açıklama metni üretir."""
    caption = msg.get("caption", "")
    if msg_type == "image":
        return f"[Kullanıcı fotoğraf gönderdi{': ' + caption if caption else ''}]"
    if msg_type == "audio":
        return f"[Kullanıcı ses mesajı gönderdi{': ' + caption if caption else ''}]"
    if msg_type == "video":
        return f"[Kullanıcı video gönderdi{': ' + caption if caption else ''}]"
    if msg_type == "document":
        filename = (msg.get("document") or {}).get("file_name", "")
        return f"[Kullanıcı dosya gönderdi: {filename or 'dosya'}]"
    if msg_type == "location":
        loc = msg.get("location", {})
        lat, lon = loc.get("latitude", "?"), loc.get("longitude", "?")
        return f"[Konum: {lat}, {lon}]"
    if msg_type == "sticker":
        emoji = (msg.get("sticker") or {}).get("emoji", "")
        return f"[Sticker{': ' + emoji if emoji else ''}]"
    return ""


async def _answer_callback(callback_query_id: str) -> None:
    """Telegram'a callback query yanıtı gönder; buton yüklenme animasyonunu kaldırır."""
    token = settings.telegram_bot_token.get_secret_value()
    if not token or not callback_query_id:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(
                f"https://api.telegram.org/bot{token}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id},
            )
    except Exception as exc:
        logger.warning("answerCallbackQuery başarısız: %s", exc)
