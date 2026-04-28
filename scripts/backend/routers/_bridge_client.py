"""Claude Code Bridge istemcisi — iletim mantığını whatsapp_router'dan ayırır (REF-1/REF-3).

Sorumluluk (SRP / REFAC-9):
  - Mesajı Bridge'e veya beta modunda projenin FastAPI'sine iletmek
  - ConnectError için retry (BR-3)
  - Başarı / hata durumlarını loglamak
  - Hata mesajını kullanıcıya göndermek

Bölünmüş sorumluluklar:
  _bridge_helpers.py — dosya adı sanitizasyonu (PI-FIX-3) + CLAUDE.md önbelleği (K8)

Dışa açık API:
  forward(sender, text, session)        — lock dışarıda alınmış olmalı
  forward_locked(sender, text, session) — session kilidini kendisi alır
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import time

import httpx

from ..config import settings
from ..store.message_logger import log_bridge_call, log_outbound, _mask_phone
from ..adapters.messenger.messenger_factory import get_messenger
from ..i18n import t
from ..store.sqlite_wrapper import store as _store  # DIP-V3: StoreProtocol uyumlu wrapper
from ._bridge_helpers import sanitize_filename as _sanitize_filename, CLAUDE_MD_CACHE as _CLAUDE_MD_CACHE
from ..adapters.messenger import TypingMessenger

logger = logging.getLogger(__name__)

_TYPING_INTERVAL = 4.0  # Telegram typing action ~5 sn aktif; 4 sn'de yenile

# D4: Persistent connection pool — her forward() çağrısında yeni TCP bağlantısı açmaz.
# bridge_client_timeout uzun (1800 s) olduğundan pool'un read_timeout'u da buna uygun.
_http_pool = httpx.AsyncClient(
    timeout=httpx.Timeout(
        connect=10.0,
        read=float(settings.bridge_client_timeout),
        write=30.0,
        pool=5.0,
    ),
    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
)


async def _typing_loop(to: str) -> None:
    """Messenger TypingMessenger ise her _TYPING_INTERVAL saniyede typing action gönder."""
    messenger = get_messenger()
    if not isinstance(messenger, TypingMessenger):
        return
    while True:
        await messenger.send_typing(to)
        await asyncio.sleep(_TYPING_INTERVAL)


# ── SOLID-v2-3: Port keşfi helper ────────────────────────────────────
async def _discover_project_api_port(project_id: str) -> int | None:
    """Proje metadata'sından API servis portunu keşfeder. Bulunamazsa None döner."""
    project = await _store.project_get(project_id)
    if not project:
        return None
    try:
        meta = _json.loads(project.get("metadata") or "{}")
        api_svc = next((s for s in meta.get("services", []) if s.get("name") == "api"), None)
        return api_svc.get("port") if api_svc else None
    except Exception:
        return None


# BR-3: ConnectError retry parametreleri
_BRIDGE_CONNECT_RETRIES = 3
_BRIDGE_RETRY_WAITS = [2, 4]  # deneme arası bekleme (saniye)


async def send_permission_response(request_id: str, session_id: str, allowed: bool) -> None:
    """Bridge'e araç onay/red kararını ilet (FEAT-4)."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{settings.claude_bridge_url}/permission_response",
                headers={"X-Api-Key": settings.api_key.get_secret_value()},
                json={"session_id": session_id, "tool_use_id": request_id, "allowed": allowed},
            )
    except Exception as exc:
        logger.error("send_permission_response hatası: req=%s err=%s", request_id, exc)


async def forward_locked(sender: str, text: str, session: dict) -> None:
    """Session kilidini alarak bridge'e ilet (dışarıdan lock alınmamışsa kullan)."""
    from ..guards import session_mgr
    async with session_mgr.lock(sender):
        await forward(sender, text, session)


async def forward_document_locked(
    sender: str, media_id: str, filename: str, mime: str, session: dict
) -> None:
    """Yapısal belge verisini session kilidiyle ilet (injection scanner tetiklememek için)."""
    from ..guards import session_mgr
    async with session_mgr.lock(sender):
        await forward_document(sender, media_id, filename, mime, session)


async def forward_document(
    sender: str, media_id: str, filename: str, mime: str, session: dict
) -> None:
    """Belge meta verisini proje API'sine veya ana bridge'e ilet.

    Proje bağlamında: /whatsapp/internal/message'a yapısal `document` alanıyla gönderir
    (text formatında göndermek injection scanner'ı tetikler — bkz. BR-DOC-1).
    Ana bridge'de: text açıklaması olarak iletir (Bridge metin tabanlı çalışır).
    """
    project_id = session.get("beta_project_id")

    if not project_id:
        # Ana mod — bridge metin tabanlı; açıklama metni kabul edilebilir
        # PI-FIX-3: filename üçüncü taraf içerik içerebilir — güvenli karakterler dışını temizle
        safe_filename = _sanitize_filename(filename)
        desc = f"[Kullanıcı dosya gönderdi: {safe_filename} ({mime}) media_id={media_id}]"
        await forward(sender, desc, session)
        return

    api_port = await _discover_project_api_port(project_id)
    if not api_port:
        lang = session.get("lang", "tr")
        await get_messenger().send_text(sender, t("bridge.doc_port_error", lang, id=project_id))
        return

    try:
        r = await _http_pool.post(
            f"http://localhost:{api_port}/whatsapp/internal/message",
            json={
                "sender":   sender,
                "text":     "",
                "document": {"media_id": media_id, "filename": filename, "mime_type": mime},
            },
        )
        r.raise_for_status()
    except Exception as exc:
        logger.error(
            "Belge iletim hatası: sender=%s error=%s", _mask_phone(sender), exc
        )
        lang = session.get("lang", "tr")
        await get_messenger().send_text(sender, t("bridge.doc_send_error", lang))


async def forward(sender: str, text: str, session: dict) -> None:
    """Bridge iletim iç mantığı — lock dışarıda alınmış olmalı."""
    context    = session.get("active_context", "main")
    session_id = "main" if context == "main" else context.replace(":", "_")
    project_id = session.get("beta_project_id")

    t0 = time.monotonic()
    answer = ""
    typing_task = asyncio.create_task(_typing_loop(sender))
    try:
        if project_id:
            r = await _forward_to_project(_http_pool, project_id, sender, text)
        else:
            r = await _forward_to_main_bridge(_http_pool, session_id, text)

        r.raise_for_status()
        data   = r.json()
        answer = data.get("answer", "")

        latency_ms = int((time.monotonic() - t0) * 1000)
        if settings.conv_history_enabled:
            log_bridge_call(
                sender=sender,
                session_id=session_id,
                prompt=text,
                response=answer,
                latency_ms=latency_ms,
                success=True,
            )

    except Exception as exc:
        latency_ms = int((time.monotonic() - t0) * 1000)
        logger.error(
            "Bridge hatası: sender=%s error_type=%s error=%s",
            _mask_phone(sender), type(exc).__name__, exc or repr(exc),
        )
        _resp = getattr(exc, "response", None)
        if _resp is not None:
            logger.error("Bridge yanıt gövdesi: %s", _resp.text[:500])
        if settings.conv_history_enabled:
            # PERF-OPT-6: str(exc) bazı httpx exception'larında boş dönebilir →
            # type adını öne koy; repr(exc) son çare olarak tam detay sağlar.
            _exc_str = str(exc)
            _err_detail = f"{type(exc).__name__}: {_exc_str}" if _exc_str else repr(exc)
            log_bridge_call(
                sender=sender,
                session_id=session_id,
                prompt=text,
                latency_ms=latency_ms,
                success=False,
                error_msg=_err_detail[:200],
            )
        lang = session.get("lang", "tr")
        msg  = _error_message(exc, project_id, lang)
        await get_messenger().send_text(sender, msg)
        if settings.conv_history_enabled:
            log_outbound(sender, "text", "bridge_error_reply", context_id=context)
        return
    finally:
        typing_task.cancel()

    # Bridge yanıtını gönder — send_text hataları bridge hatasıyla karışmasın
    if answer:
        try:
            await get_messenger().send_text(sender, answer)
            if settings.conv_history_enabled:
                log_outbound(sender, "text", answer, context_id=context)
        except Exception as send_exc:
            logger.error("Yanıt gönderilemedi: sender=%s error=%s", _mask_phone(sender), send_exc)


async def _forward_to_project(
    client: httpx.AsyncClient, project_id: str, sender: str, text: str
) -> httpx.Response:
    """Beta: mesajı projenin kendi FastAPI'sine yönlendir."""
    api_port = await _discover_project_api_port(project_id)
    if not api_port:
        raise RuntimeError(f"Proje API portu bulunamadı: {project_id}")
    return await client.post(
        f"http://localhost:{api_port}/whatsapp/internal/message",
        json={"sender": sender, "text": text},
    )


async def _forward_to_main_bridge(
    client: httpx.AsyncClient, session_id: str, text: str
) -> httpx.Response:
    """Ana mod: 99-root bridge — ConnectError'da retry."""
    from ..guards.runtime_state import get_active_model
    active_model = get_active_model() or settings.default_model
    body: dict = {"session_id": session_id, "message": text, "init_prompt": _CLAUDE_MD_CACHE}
    if active_model:
        body["model"] = active_model
    r: httpx.Response | None = None
    for _attempt in range(_BRIDGE_CONNECT_RETRIES):
        try:
            r = await client.post(
                f"{settings.claude_bridge_url}/query",
                headers={"X-Api-Key": settings.api_key.get_secret_value()},
                json=body,
            )
            return r
        except httpx.ConnectError:
            if _attempt < _BRIDGE_CONNECT_RETRIES - 1:
                wait = _BRIDGE_RETRY_WAITS[min(_attempt, len(_BRIDGE_RETRY_WAITS) - 1)]
                logger.warning(
                    "Bridge ConnectError — %ds sonra tekrar deneniyor (deneme %d/%d)",
                    wait, _attempt + 1, _BRIDGE_CONNECT_RETRIES,
                )
                await asyncio.sleep(wait)
            else:
                raise  # tüm denemeler başarısız


def _error_message(exc: Exception, project_id: str | None, lang: str = "tr") -> str:
    """İstisna türüne göre kullanıcıya gösterilecek hata metnini üretir."""
    err_str = str(exc).lower()
    if "timeout" in err_str:
        return t("bridge.timeout", lang)
    if project_id and ("connection refused" in err_str or "connect" in err_str):
        project_name = project_id
        try:
            from ..store.repositories.project_repo import _sync_project_get
            _p = _sync_project_get(project_id)
            if _p:
                project_name = _p["name"]
        except (OSError, ValueError, KeyError):
            pass
        return t("bridge.project_offline", lang, name=project_name)
    if "connection" in err_str or "connect" in err_str:
        return t("bridge.connection_error", lang)
    return t("bridge.unavailable", lang)
