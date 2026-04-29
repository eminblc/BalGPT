"""FastAPI uygulama giriş noktası.

Sorumluluk: app oluşturma, middleware, router kayıt, startup/shutdown.
İş mantığı bu dosyada olmaz — router ve feature modüllerine ait.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from .config import settings
from .logging_config import configure_logging

logger = logging.getLogger(__name__)


async def _startup_message() -> str:
    """Proxy URL'sini okuyup açılış mesajı oluştur."""
    from .features import webhook_proxy
    from .i18n import t
    public_url = webhook_proxy.get_public_url()
    if public_url:
        return t("main.started_with_url", "tr", url=f"{public_url}/whatsapp/webhook")
    return t("main.started", "tr")


async def _notify(text: str) -> None:
    """Owner'a bildirim gönder. Hata olursa sessizce geç — lifecycle'ı bloklamaz."""
    if not settings.owner_id:
        return
    try:
        from .adapters.messenger import get_messenger
        await get_messenger().send_text(settings.owner_id, text)
    except Exception as e:
        logger.warning("Lifecycle bildirimi gönderilemedi: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup ve shutdown hook'ları."""
    configure_logging(level=settings.log_level)
    logger.info("BalGPT başlatılıyor (port %d)", settings.port)

    # Güvenlik doğrulaması — SRP: tüm mantık Settings.validate_for_environment()'ta
    settings.validate_for_environment()

    # FEAT-3: Aktif yetenek kısıtlamalarını logla
    from .guards import get_capability_guard
    get_capability_guard().log_active_restrictions()

    # DB şemasını oluştur / güncelle
    from .store.sqlite_store import init_db, init_db_migrations
    init_db()
    init_db_migrations()
    logger.info("SQLite DB hazır")

    # FEAT-6: Kalıcı model tercihini yükle — restart sonrası korunur
    try:
        from .store.repositories.settings_repo import _sync_user_setting_get
        from .guards.runtime_state import set_active_model
        saved_model = _sync_user_setting_get(settings.owner_id, "model")
        if saved_model:
            set_active_model(saved_model)
            logger.info("Kullanıcı model tercihi yüklendi: %s", saved_model)
    except Exception as exc:
        logger.warning("Model tercihi yüklenemedi: %s", exc)

    # MOD-10: Feature registry startup hook'ları (scheduler, webhook_proxy, ...)
    from .features._registry import run_startup_hooks
    await run_startup_hooks()

    # Telegram komut menüsünü senkronize et — her restart'ta otomatik güncellenir
    if settings.messenger_type == "telegram":
        from .services.telegram_command_sync import TelegramCommandSyncer
        try:
            await TelegramCommandSyncer().sync()
        except Exception as exc:
            logger.warning("Telegram komut menüsü senkronizasyonu başarısız: %s", exc)

    # Açılış bildirimi — proxy URL'sini de içerir (webhook_proxy start sonrası)
    await _notify(await _startup_message())

    # Periyodik session temizliği başlat (her saat)
    async def _session_cleanup_loop():
        from .guards import get_session_mgr
        from .whatsapp.cloud_api import evict_outbound_cache
        while True:
            await asyncio.sleep(3600)
            try:
                cleaned = await get_session_mgr().cleanup_expired()
                if cleaned:
                    logger.info("Session temizlendi: %d adet", cleaned)
                evict_outbound_cache()  # R6: uzun inaktifte outbound lock sızıntısını önle
            except Exception as exc:
                # BUG-A4: loop ölmeden devam et — bir sonraki saatte tekrar dener
                logger.error("Session cleanup döngüsünde beklenmedik hata: %s", exc, exc_info=True)

    cleanup_task = asyncio.create_task(_session_cleanup_loop())

    # SRP-1: Bridge izleme BridgeMonitor sınıfına taşındı
    from .services.bridge_monitor import BridgeMonitor
    bridge_monitor = BridgeMonitor(settings.claude_bridge_url, _notify)
    await bridge_monitor.start()

    yield

    # Kapatma bildirimi — her şeyden ÖNCE gönderilmeli
    from .i18n import t as _t
    await _notify(_t("main.stopping", "tr"))

    # Arka plan görevlerini durdur
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass
    await bridge_monitor.stop()

    # MOD-10: Feature registry shutdown hook'ları — LIFO sırası
    from .features._registry import run_shutdown_hooks
    await run_shutdown_hooks()
    logger.info("Ajan kapatılıyor")


app = FastAPI(
    title="BalGPT API",
    docs_url=None,       # Swagger kapalı (güvenlik)
    redoc_url=None,
    lifespan=lifespan,
)

_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()] or ["http://localhost:5678"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Api-Key"],
)
# SEC-H2: X-Forwarded-For yalnızca 127.0.0.1 (local proxy) kaynağında güvenilir;
# dış kaynaklı sahte header'lar yok sayılır → rate limiter IP spoofing bypass engellenir
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=["127.0.0.1"])

# ── Router kayıtları — MOD-10: Feature registry üzerinden ───────────────────
from .features._registry import register_routers  # noqa: E402

register_routers(app)


def _get_public_url() -> str:
    try:
        from .features import webhook_proxy
        return webhook_proxy.get_public_url() or ""
    except Exception:
        return ""


@app.get("/health")
async def health():
    import httpx
    bridge_ok = False
    bridge_detail: str | None = None
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{settings.claude_bridge_url}/health")
        bridge_ok = r.status_code == 200
        bridge_detail = r.json().get("status") if bridge_ok else f"http_{r.status_code}"
    except Exception as exc:
        bridge_detail = str(exc)[:80]

    from .store.sqlite_store import db_ping
    db_ok = await db_ping()

    if not settings.scheduler_enabled:
        scheduler_ok = True  # devre dışı = sorun yok
    else:
        from .features.scheduler import _scheduler
        scheduler_ok = _scheduler.running

    # R5: alt servis hatalarında "degraded" döndür
    overall = "ok" if (bridge_ok and db_ok and scheduler_ok) else "degraded"
    return {
        "status": overall,
        "service": "personal-agent",
        "bridge": "ok" if bridge_ok else "down",
        "bridge_detail": bridge_detail,
        "db": "ok" if db_ok else "down",
        "scheduler": "disabled" if not settings.scheduler_enabled else ("ok" if scheduler_ok else "down"),
        "public_url": _get_public_url(),
    }
