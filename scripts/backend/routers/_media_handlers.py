"""WhatsApp medya mesajı işleyicileri — whatsapp_router'dan ayrıştırıldı (REF-3).

Sorumluluk (SRP):
  - Gelen image / audio / video / document mesajlarını işlemek
  - İlgili features/media_handler fonksiyonlarını çağırmak
  - Mesajı loglamak ve bridge'e iletmek

Bağımlılık yönü: Media handlers → Bridge client (forward_locked)
Not: Bu modül WhatsApp'a özgü medya indirme mantığı içerir. Gönderim get_messenger()
     üzerinden yapılır; platform değiştirildiğinde (ör. Telegram) bu modüle dokunulmaz.
"""
from __future__ import annotations

import logging

from ..config import settings
from ..store.message_logger import log_inbound, log_outbound
from ..adapters.messenger.messenger_factory import get_messenger
from ..i18n import t

logger = logging.getLogger(__name__)


async def _handle_media(
    sender: str,
    msg_id: str,
    msg: dict,
    session: dict,
    raw_payload: dict | None,
    *,
    media_type: str,
    handler_fn,
) -> None:
    """image / audio / video için ortak: işle → logla → bridge'e ilet."""
    from . import _bridge_client
    context_id = session.get("active_context", "main")
    desc, media_id, media_path = await handler_fn(sender, msg, session)
    if settings.conv_history_enabled:
        log_inbound(msg_id, sender, media_type, content=desc, media_id=media_id,
                    media_path=media_path,
                    mime_type=msg.get(media_type, {}).get("mime_type"),
                    context_id=context_id, raw_payload=raw_payload)
    await _bridge_client.forward_locked(sender, desc, session)


async def handle_image(
    sender: str, msg_id: str, msg: dict, session: dict, raw_payload: dict | None
) -> None:
    from ..features.media_handler import handle_image as _process
    await _handle_media(sender, msg_id, msg, session, raw_payload,
                        media_type="image", handler_fn=_process)


async def handle_audio(
    sender: str, msg_id: str, msg: dict, session: dict, raw_payload: dict | None
) -> None:
    from ..features.media_handler import handle_audio as _process
    await _handle_media(sender, msg_id, msg, session, raw_payload,
                        media_type="audio", handler_fn=_process)


async def handle_video(
    sender: str, msg_id: str, msg: dict, session: dict, raw_payload: dict | None
) -> None:
    from ..features.media_handler import handle_video as _process
    await _handle_media(sender, msg_id, msg, session, raw_payload,
                        media_type="video", handler_fn=_process)


async def handle_document(
    sender: str, msg_id: str, msg: dict, session: dict, raw_payload: dict | None
) -> None:
    from . import _bridge_client
    context_id = session.get("active_context", "main")
    doc      = msg.get("document", {})
    media_id = doc.get("id", "")
    mime     = doc.get("mime_type", "")
    filename = doc.get("filename", "")

    if settings.conv_history_enabled:
        log_inbound(msg_id, sender, "document", content=filename, media_id=media_id,
                    mime_type=mime, context_id=context_id, raw_payload=raw_payload)

    if mime == "application/pdf":
        if not settings.pdf_import_enabled:
            lang = session.get("lang", "tr")
            cap_name = t("capability.pdf_import", lang)
            await get_messenger().send_text(
                sender, t("guard.capability_restricted", lang, capability=cap_name)
            )
            return
        lang = session.get("lang", "tr")
        # Proje sihirbazı aktifken PDF import'u reddet; kullanıcı önce sihirbazı bitirmeli.
        _WIZ_KEYS = ("awaiting_project_name", "awaiting_project_description",
                     "wiz_name", "wiz_level", "awaiting_project_path", "wiz_svc_decision")
        if any(session.get(k) for k in _WIZ_KEYS):
            await get_messenger().send_text(sender, t("media.pdf_wizard_active", lang))
            return
        session.set_pending_pdf(media_id)
        await get_messenger().send_buttons(
            sender,
            t("media.pdf_received", lang, filename=filename or "dosya.pdf"),
            [
                {"id": "pdf_scaffold_full",    "title": t("media.pdf_btn_full", lang)},
                {"id": "pdf_scaffold_minimal", "title": t("media.pdf_btn_minimal", lang)},
                {"id": "pdf_scaffold_none",    "title": t("media.pdf_btn_none", lang)},
            ],
        )
        if settings.conv_history_enabled:
            log_outbound(sender, "text", "pdf_confirm_prompt", context_id=context_id)
    else:
        await _bridge_client.forward_document_locked(sender, media_id, filename, mime, session)
