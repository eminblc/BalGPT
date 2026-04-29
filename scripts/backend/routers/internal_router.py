"""Internal router — yalnızca localhost (127.0.0.1 / ::1) erişimine açık endpoint'ler.

Dış ağdan erişilemez; API key gerektirmez.
Kullanım: Claude Code Bridge veya Claude Code CLI'nın admin TOTP doğrulaması için.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from ..guards import get_perm_mgr, get_session_mgr
from ..config import settings
from ..adapters.messenger.messenger_factory import get_messenger
from ..i18n import t
from ._localhost_guard import is_localhost

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal")


def _require_localhost(request: Request) -> None:
    if not is_localhost(request):
        host = request.client.host if request.client else "?"
        logger.warning("internal_router: localhost dışı erişim engellendi host=%s", host)
        raise HTTPException(status_code=403, detail="Localhost only")


class _VerifyRequest(BaseModel):
    code: str


class _PermissionPromptRequest(BaseModel):
    session_id: str
    request_id: str   # = tool_use_id (Bridge'den gelen ham ID)
    tool_name:  str
    tool_detail: str  # Bridge'de summarizeToolInput() ile hazırlanmış özet


@router.post("/send_permission_prompt")
async def send_permission_prompt(request: Request, body: _PermissionPromptRequest):
    """Bridge'den gelen araç onayı isteğini kullanıcıya buton olarak ilet."""
    _require_localhost(request)
    messenger = get_messenger()
    owner     = settings.owner_id
    lang      = get_session_mgr().get(owner).get("lang", "tr")

    await messenger.send_buttons(
        owner,
        t("permission.prompt_body", lang, tool_name=body.tool_name, detail=body.tool_detail),
        [
            {"id": f"perm_a:{body.request_id}", "title": t("permission.allow_btn", lang)},
            {"id": f"perm_d:{body.request_id}", "title": t("permission.deny_btn", lang)},
        ],
    )
    logger.info(
        "permission_prompt gönderildi: session=%s req=%s tool=%s",
        body.session_id, body.request_id, body.tool_name,
    )
    return {"ok": True}


class _SendMessageRequest(BaseModel):
    to: str
    text: str


class _SendMediaRequest(BaseModel):
    """Yerel medya dosyasını owner'a gönderme isteği.

    path  — tek dosya (screenshot, video vb.)
    paths — çoklu dosya listesi (çok monitörlü screenshot/video)
    to    — hedef; belirtilmezse settings.owner_id kullanılır
    caption — isteğe bağlı açıklama
    """
    path: Optional[str] = None
    paths: Optional[list[str]] = None
    caption: str = ""
    to: Optional[str] = None


@router.post("/send_media")
async def internal_send_media(request: Request, body: _SendMediaRequest):
    """Yerel medya dosyasını (görsel/video/belge) owner'a gönder.

    Yalnızca localhost erişimine açıktır; API key gerekmez.
    Bridge veya Claude Code CLI, screenshot/video sonrası bu endpoint'i çağırır.

    MIME tipine göre otomatik dispatch:
      image/* → send_image
      video/* → send_video
      diğer   → send_document
    """
    import mimetypes
    from pathlib import Path

    _require_localhost(request)

    # Gönderilecek yolları topla (path XOR paths)
    all_paths: list[str] = []
    if body.paths:
        all_paths = body.paths
    elif body.path:
        all_paths = [body.path]

    if not all_paths:
        raise HTTPException(status_code=400, detail="path veya paths alanı gerekli")

    messenger = get_messenger()
    owner = body.to or settings.owner_id

    from ..adapters.messenger import MediaMessenger

    results: list[dict] = []
    for file_path in all_paths:
        p = Path(file_path)
        if not p.exists():
            logger.warning("send_media: dosya bulunamadı: %s", file_path)
            results.append({"path": file_path, "ok": False, "error": "dosya bulunamadı"})
            continue

        mime_type, _ = mimetypes.guess_type(file_path)
        mt = mime_type or ""

        if not isinstance(messenger, MediaMessenger):
            # Medya desteklemeyen messenger → yol bilgisini metin olarak ilet
            await messenger.send_text(owner, f"📁 {p.name}: {file_path}")
            results.append({"path": file_path, "ok": True, "fallback": "text"})
            logger.info(
                "send_media: medya desteği yok, metin fallback. path=%s messenger=%s",
                file_path, type(messenger).__name__,
            )
            continue

        try:
            if mt.startswith("image/"):
                await messenger.send_image(owner, file_path, caption=body.caption)
            elif mt.startswith("video/"):
                await messenger.send_video(owner, file_path, caption=body.caption)
            else:
                await messenger.send_document(
                    owner, file_path, filename=p.name, caption=body.caption
                )
            results.append({"path": file_path, "ok": True})
            logger.info(
                "send_media: gönderildi path=%s mime=%s to=%s",
                file_path, mt, owner[:6] + "…",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("send_media: gönderim hatası path=%s: %s", file_path, exc)
            results.append({"path": file_path, "ok": False, "error": str(exc)})

    all_ok = all(r["ok"] for r in results)
    return {"ok": all_ok, "results": results}


@router.post("/send_message")
async def internal_send_message(request: Request, body: _SendMessageRequest):
    """Localhost'taki proje servislerinin kullanıcıya mesaj göndermesi için.

    Yalnızca localhost erişimine açıktır; API key gerekmez.
    Proje FastAPI'leri (bengisu vb.) bu endpoint'i çağırarak WhatsApp/Telegram'a
    mesaj gönderir — 99-root API key'i bilmeden mesaj iletimi sağlar.
    """
    _require_localhost(request)
    messenger = get_messenger()
    await messenger.send_text(body.to, body.text)
    logger.info("internal send_message: to=%s len=%d", body.to[:6] + "…", len(body.text))
    return {"ok": True}


@router.post("/verify-admin-totp")
async def verify_totp_internal(request: Request, body: _VerifyRequest):
    """Owner TOTP doğrulaması — Claude Code CLI guardrail override için.

    Endpoint adı geriye dönük uyumluluk için korundu (bridge bu URL'yi kullanır).
    Dönüş: {"valid": true/false}
    SEC-H1: Brute-force koruması — 3 başarısız deneme → 15 dk kilit.
    Kilit "internal_cli" sender key'i ile totp_lockouts tablosuna yazılır;
    WhatsApp TOTP lockout'undan bağımsızdır.
    """
    import time as _time
    from ..store.sqlite_store import totp_get_lockout, totp_record_failure, totp_reset_lockout

    _require_localhost(request)

    _SENDER = "internal_cli"
    _, lockout_until = await totp_get_lockout(_SENDER, "owner")
    if lockout_until and _time.time() < lockout_until:
        remaining = int(lockout_until - _time.time())
        logger.warning("internal verify-admin-totp: kilit aktif, %d sn kaldı", remaining)
        return {"valid": False}

    valid = get_perm_mgr().verify_totp(body.code)

    if valid:
        await totp_reset_lockout(_SENDER, "owner")
        logger.info("internal verify-admin-totp: başarılı doğrulama")
    else:
        fail_count, locked_until = await totp_record_failure(_SENDER, "owner")
        if locked_until:
            logger.warning(
                "internal verify-admin-totp: brute-force kilidi uygulandı fail_count=%d",
                fail_count,
            )
        else:
            logger.warning(
                "internal verify-admin-totp: başarısız deneme fail_count=%d", fail_count
            )

    return {"valid": valid}


# Zamanlama endpoint'leri _schedule_router.py'e taşındı (SOLID-SRP-1).
