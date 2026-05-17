"""Platform-bağımsız mesaj dispatch — WhatsApp ve Telegram router'larının ortak giriş noktası.

Sorumluluk (SRP):
  - Mesaj tipine göre yönlendirme: text / interactive / location / sticker / reaction
  - Interactive (buton/liste) yönlendirme ve beta mod proje iletimi

Alt modüller:
  _auth_dispatcher.py — Auth state akışları (math_challenge, totp, guardrail)
  _text_router.py     — Metin yönlendirme (!komutlar, wizard, niyet, Bridge)

OCP-3: Auth state dispatch _AUTH_FLOW_REGISTRY dict ile yönetilir.
  Yeni auth adımı = yeni handler fonksiyonu + _auth_dispatcher._AUTH_FLOW_REGISTRY'ye kayıt.

OCP-MSG: Mesaj tipi dispatch _MSG_TYPE_HANDLERS dict ile yönetilir.
  Yeni mesaj tipi = yeni _handle_<type>() fonksiyonu + _MSG_TYPE_HANDLERS kaydı.

Bağımlılık yönü: Dispatcher → Guards → Features → Store
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

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

# SEC-SCAN2-R14: Çok büyük mesajların Bridge forward'ında bellek tüketmesini önlemek için
# maksimum metin uzunluğu sınırı. Bu değeri aşan mesajlar truncate edilir.
_MAX_MESSAGE_LENGTH: int = 32_000


@dataclass
class _MsgCtx:
    """Tek mesaj dispatch turundaki tüm bağlamı taşır (SRP: argüman listesi küçülür)."""
    sender: str
    msg_id: str
    msg_type: str
    text: str
    reply_id: str
    extra_desc: str
    raw_payload: Any
    context_id: str
    session: dict
    lang: str


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
    inbound = inbound or {}

    # SEC-SCAN2-R14: Bellek tüketimini önlemek için çok büyük metinleri truncate et.
    raw_text: str = inbound.get("text", "")
    if len(raw_text) > _MAX_MESSAGE_LENGTH:
        logger.warning(
            "Mesaj truncate edildi: sender=%s original_len=%d max=%d",
            sender, len(raw_text), _MAX_MESSAGE_LENGTH,
        )
        raw_text = raw_text[:_MAX_MESSAGE_LENGTH]

    ctx = _MsgCtx(
        sender=sender,
        msg_id=msg_id,
        msg_type=msg_type,
        text=raw_text,
        reply_id=inbound.get("reply_id", ""),
        extra_desc=inbound.get("extra_desc", ""),
        raw_payload=inbound.get("raw_payload"),
        context_id=session.get("active_context", "main"),
        session=session,
        lang=session.get("lang", "tr"),
    )

    # ── Kilit kontrolü ────────────────────────────────────────────────
    if is_locked():
        has_auth_flow = has_active_auth_flow(session)
        is_unlock_cmd = msg_type == "text" and ctx.text.strip().lower().startswith("/unlock")
        if not has_auth_flow and not is_unlock_cmd:
            await get_messenger().send_text(sender, t("lock.locked_msg", ctx.lang))
            return

    # ── Auth state akışları (SRP-V2: _auth_dispatcher.handle_auth_flow) ─────
    if await handle_auth_flow(sender, ctx.text, msg_type, msg_id, session):
        return

    # ── Mesaj tipine göre yönlendir (OCP-MSG: registry) ──────────────
    handler = _MSG_TYPE_HANDLERS.get(msg_type, _handle_unsupported)
    await handler(ctx)


# ── Mesaj tipi handler'ları ───────────────────────────────────────

_HandlerFn = Callable[[_MsgCtx], Awaitable[None]]


async def _handle_text(ctx: _MsgCtx) -> None:
    if settings.conv_history_enabled:
        log_inbound(ctx.msg_id, ctx.sender, "text", content=ctx.text,
                    context_id=ctx.context_id, raw_payload=ctx.raw_payload)
    await _route_text(ctx.sender, ctx.text, ctx.session)


async def _handle_interactive(ctx: _MsgCtx) -> None:
    if settings.conv_history_enabled:
        log_inbound(ctx.msg_id, ctx.sender, "interactive", content=ctx.reply_id,
                    context_id=ctx.context_id, raw_payload=ctx.raw_payload)
    # FEAT-4: Araç onayı butonları session kilidini beklemeden hemen işlenmeli.
    # forward_locked zaten kilidi tutuyor olabilir (Bridge yanıtı bekleniyor);
    # lock altında _route_interactive çağırmak deadlock'a yol açar.
    if ctx.reply_id.startswith("perm_a:") or ctx.reply_id.startswith("perm_d:"):
        short_id = ctx.reply_id[7:]
        allowed = ctx.reply_id.startswith("perm_a:")
        session_id = "main" if ctx.context_id == "main" else ctx.context_id.replace(":", "_")
        from ._bridge_client import send_permission_response
        await send_permission_response(short_id, session_id, allowed)
        msg_key = "permission.allowed" if allowed else "permission.denied"
        await get_messenger().send_text(ctx.sender, t(msg_key, ctx.lang))
        return
    async with get_session_mgr().lock(ctx.sender):
        await _route_interactive(ctx.sender, ctx.reply_id, ctx.session)


async def _handle_location(ctx: _MsgCtx) -> None:
    if settings.conv_history_enabled:
        log_inbound(ctx.msg_id, ctx.sender, "location", content=ctx.extra_desc,
                    context_id=ctx.context_id, raw_payload=ctx.raw_payload)
    await _forward_to_bridge(ctx.sender, ctx.extra_desc, ctx.session)


async def _handle_sticker(ctx: _MsgCtx) -> None:
    if settings.conv_history_enabled:
        log_inbound(ctx.msg_id, ctx.sender, "sticker", content=ctx.extra_desc,
                    context_id=ctx.context_id, raw_payload=ctx.raw_payload)
    await get_messenger().send_text(ctx.sender, t("msg.sticker_ack", ctx.lang))
    if settings.conv_history_enabled:
        log_outbound(ctx.sender, "text", "sticker_ack", context_id=ctx.context_id)


async def _handle_reaction(ctx: _MsgCtx) -> None:
    if settings.conv_history_enabled:
        log_inbound(ctx.msg_id, ctx.sender, "reaction", content=ctx.extra_desc,
                    context_id=ctx.context_id, raw_payload=ctx.raw_payload)
    logger.info("Reaction: sender=%s %s", ctx.sender, ctx.extra_desc)


async def _handle_media(ctx: _MsgCtx) -> None:
    """Telegram medya mesajları için indirme + Bridge iletimi.

    raw_payload içinde tg_file_id varsa TelegramMediaDownloader ile dosyayı indirir,
    geçici diske yazar ve Bridge'e yol bilgisiyle birlikte iletir.
    file_id yoksa (veya indirme başarısız olursa) metin açıklamasıyla Bridge'e düşer.

    Not: WhatsApp medya tipleri (image/audio/video/document) telegram_router'a hiç
    ulaşmadığından burası yalnızca Telegram (ve gelecekteki) platformları etkiler.
    """
    if settings.conv_history_enabled:
        log_inbound(ctx.msg_id, ctx.sender, ctx.msg_type, content=ctx.extra_desc,
                    context_id=ctx.context_id, raw_payload=ctx.raw_payload)

    file_id: str | None = (ctx.raw_payload or {}).get("tg_file_id")
    if file_id:
        import pathlib
        import tempfile

        from ..adapters.media import get_media_downloader

        try:
            import mimetypes
            content, mime = await get_media_downloader().download(file_id)
            ext = mimetypes.guess_extension(mime) or ""
            tmp = pathlib.Path(tempfile.mktemp(suffix=ext, prefix="tg_media_"))
            tmp.write_bytes(content)
            logger.info(
                "Telegram medya indirildi: type=%s size=%d path=%s",
                ctx.msg_type, len(content), tmp,
            )
            await _forward_to_bridge(
                ctx.sender,
                f"{ctx.extra_desc}\n[Medya kaydedildi: {tmp}]",
                ctx.session,
            )
            return
        except Exception as exc:
            logger.warning("Telegram medya indirme hatası type=%s: %s", ctx.msg_type, exc)
            await get_messenger().send_text(ctx.sender, t("media.download_error", ctx.lang))
            return

    # Fallback: metin açıklamasıyla Bridge'e ilet
    await _forward_to_bridge(ctx.sender, ctx.extra_desc, ctx.session)


async def _handle_unsupported(ctx: _MsgCtx) -> None:
    logger.info("Desteklenmeyen mesaj tipi: %s sender=%s", ctx.msg_type, ctx.sender)
    if settings.conv_history_enabled:
        log_inbound(ctx.msg_id, ctx.sender, ctx.msg_type,
                    context_id=ctx.context_id, raw_payload=ctx.raw_payload)
    await get_messenger().send_text(
        ctx.sender,
        t("msg.unsupported_type", ctx.lang, msg_type=ctx.msg_type),
    )


async def _handle_document(ctx: _MsgCtx) -> None:
    """Telegram belge mesajlarını işler (BACKUP-7 — OCP-MSG genişletme noktası).

    Backup import akışı aktifse Telegram Bot API üzerinden dosyayı indirir;
    akış aktif değilse belge açıklamasını Bridge'e iletir.
    """
    from ._backup_import_handler import is_backup_pending, handle_backup_bytes

    if settings.conv_history_enabled:
        log_inbound(ctx.msg_id, ctx.sender, "document", content=ctx.extra_desc,
                    context_id=ctx.context_id, raw_payload=ctx.raw_payload)

    if not is_backup_pending(ctx.session):
        # Import akışı yok — Bridge'e metin açıklamasını ilet
        await _forward_to_bridge(ctx.sender, ctx.extra_desc, ctx.session)
        return

    # Telegram belge indirme (BACKUP-7)
    doc = (ctx.raw_payload or {}).get("message", {}).get("document", {})
    file_id  = doc.get("file_id", "")
    filename = doc.get("file_name", "backup.99rb")

    if not file_id:
        await get_messenger().send_text(
            ctx.sender, t("backup.import_bad_file", ctx.lang)
        )
        ctx.session.clear_backup_import()
        return

    raw_bytes = await _download_telegram_file(file_id)
    if raw_bytes is None:
        await get_messenger().send_text(
            ctx.sender,
            t("backup.import_download_error", ctx.lang, error="Telegram dosyası indirilemedi"),
        )
        ctx.session.clear_backup_import()
        return

    await handle_backup_bytes(ctx.sender, filename, raw_bytes, ctx.session)


async def _download_telegram_file(file_id: str) -> bytes | None:
    """Telegram Bot API'si üzerinden file_id'ye karşılık gelen dosyayı indirir.

    Returns:
        İndirilen dosyanın ham byte'ları veya hata durumunda None.
    """
    import httpx
    from ..config import settings as _cfg

    token = _cfg.telegram_bot_token
    if not token:
        logger.warning("Telegram dosyası indirilemedi: TELEGRAM_BOT_TOKEN ayarlanmamış")
        return None

    token_val = token.get_secret_value() if hasattr(token, "get_secret_value") else str(token)
    base = f"https://api.telegram.org/bot{token_val}"

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.get(f"{base}/getFile", params={"file_id": file_id})
            r.raise_for_status()
            file_path = r.json().get("result", {}).get("file_path", "")
            if not file_path:
                logger.warning("Telegram getFile: file_path boş döndü (file_id=%s)", file_id)
                return None
            dl = await client.get(f"https://api.telegram.org/file/bot{token_val}/{file_path}")
            dl.raise_for_status()
            return dl.content
    except Exception as exc:
        logger.exception("Telegram dosya indirme hatası: file_id=%s hata=%s", file_id, exc)
        return None


# OCP-MSG: Yeni mesaj tipi = yeni _handle_<type>() + buraya kayıt
_MSG_TYPE_HANDLERS: dict[str, _HandlerFn] = {
    "text":        _handle_text,
    "interactive": _handle_interactive,
    "location":    _handle_location,
    "sticker":     _handle_sticker,
    "reaction":    _handle_reaction,
    "image":       _handle_media,
    "audio":       _handle_media,
    "video":       _handle_media,
    "document":    _handle_media,
}


# ── NL Zamanlama buton handler ────────────────────────────────────

async def _handle_nl_schedule_reply(sender: str, reply_id: str, session: dict) -> None:
    """Doğal dil zamanlama onay veya iptal butonunu işler."""
    from ..i18n import t
    from ..adapters.messenger.messenger_factory import get_messenger

    lang = session.get("lang", "tr")
    messenger = get_messenger()

    pending = session.pop("pending_nl_schedule", None)

    if reply_id == "nlsched_cancel" or not pending:
        await messenger.send_text(sender, t("nl_schedule.cancelled", lang))
        return

    params = pending.get("params", {})
    project_id  = params.get("project_id", "")
    action_type = params.get("action_type", "")
    cron_expr   = params.get("cron_expr", "")
    description = params.get("description", f"{action_type} — {project_id}")

    if not project_id or not action_type or not cron_expr:
        await messenger.send_text(sender, t("nl_schedule.create_error", lang))
        return

    try:
        from ..store import sqlite_store as db
        from ..features.scheduler import add_cron_job

        # action_payload oluştur
        if action_type == "run_scanner":
            payload = {
                "scan_type":   params.get("scan_type", "security"),
                "project_id":  project_id,
                "auto_review": params.get("auto_review", True),
                "dry_run":     params.get("dry_run", False),
            }
        else:  # run_backlog_executor
            payload = {
                "project_id": project_id,
                "prefix":     params.get("prefix", ""),
                "max_items":  params.get("max_items", 3),
                "parallel":   2,
                "dry_run":    params.get("dry_run", False),
            }

        task = await db.task_create(
            description=description,
            action_type=action_type,
            action_payload=payload,
            cron_expr=cron_expr,
        )
        await add_cron_job(task["id"], cron_expr, description, action_type, payload)
        await messenger.send_text(
            sender,
            t("nl_schedule.created", lang,
              id=task["id"][:6], cron=cron_expr, desc=description),
        )
    except Exception as exc:
        logger.error("nl_schedule oluşturma hatası: %s", exc)
        await messenger.send_text(sender, t("nl_schedule.create_error", lang))


# ── Interactive yönlendirme ───────────────────────────────────────

async def _route_interactive(sender: str, reply_id: str, session: dict) -> None:
    # REFAC-10: perm_a/perm_d butonları handle_common_message'da önceden işlenir ve return
    # edilir; bu fonksiyona asla ulaşmaz — duplike kontrol kaldırıldı.
    from ..guards.commands import registry as cmd_registry
    from ..features.menu import handle_menu_reply, is_handled_locally
    from ..features.install_wizard import handle_install_wizard_callback, is_wizard_callback

    # TG-WIZ-1: Install wizard callback'leri menüden önce yakalanır (iw: prefix).
    if is_wizard_callback(reply_id):
        lang = session.get("lang", "tr")
        await handle_install_wizard_callback(sender, reply_id, lang)
        return

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

    # ── Komut-özel buton handler'ları ────────────────────────────────────
    # /lang dil seçim butonları
    if reply_id.startswith("lang_select_"):
        code = reply_id[len("lang_select_"):]
        command = cmd_registry.get("/lang")
        if command:
            await command.execute(sender, code, session)
        return

    # /tokens zaman aralığı butonları
    if reply_id.startswith("tokens_"):
        period = reply_id[len("tokens_"):]  # "24h", "7d", "30d"
        command = cmd_registry.get("/tokens")
        if command:
            await command.execute(sender, period, session)
        return

    # /history mesaj sayısı butonları
    if reply_id.startswith("history_"):
        sub = reply_id[len("history_"):]  # "5", "10", "20", "summary"
        command = cmd_registry.get("/history")
        if command:
            await command.execute(sender, sub, session)
        return

    # /export kapsam butonları
    if reply_id.startswith("export_"):
        scope = reply_id[len("export_"):]  # "essential", "full", "media", "env"
        command = cmd_registry.get("/export")
        if command:
            # "essential" → empty arg (ExportCommand._resolve_scope treats "" as essential)
            await command.execute(sender, "" if scope == "essential" else scope, session)
        return

    # /backlog run butonları
    if reply_id.startswith("backlog_"):
        sub = reply_id[len("backlog_"):]
        command = cmd_registry.get("/backlog")
        if command:
            if sub == "status":
                await command.execute(sender, "durum", session)
            elif sub.startswith("run_"):
                project_id = sub[len("run_"):]
                await command.execute(sender, f"çalıştır {project_id}", session)
        return

    # /scan tip seçim butonları
    if reply_id.startswith("scan_"):
        sub = reply_id[len("scan_"):]  # "security", "bugfix", "status"
        command = cmd_registry.get("/scan")
        if command:
            await command.execute(sender, sub, session)
        return

    # /timezone saat dilimi butonları
    if reply_id.startswith("tz_"):
        _TZ_MAP: dict[str, str] = {
            "tz_Istanbul": "Europe/Istanbul",
            "tz_London":   "Europe/London",
            "tz_Berlin":   "Europe/Berlin",
            "tz_NewYork":  "America/New_York",
            "tz_Dubai":    "Asia/Dubai",
        }
        tz = _TZ_MAP.get(reply_id)
        if tz:
            command = cmd_registry.get("/timezone")
            if command:
                await command.execute(sender, tz, session)
        return

    # Doğal dil zamanlama onay/iptal butonları
    if reply_id in ("nlsched_confirm", "nlsched_cancel"):
        await _handle_nl_schedule_reply(sender, reply_id, session)
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
        messenger_type = settings.messenger_type.lower()
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"http://localhost:{api_port}/{messenger_type}/internal/message",
                json={"sender": sender, "text": "", "reply_id": reply_id},
            )
            r.raise_for_status()
    except Exception as exc:
        logger.exception(
            "_forward_interactive_to_project hatası: sender=%s project_id=%s error=%s",
            sender, project_id, exc,
        )
        await get_messenger().send_text(sender, t("dispatcher.project_connect_error", lang))
