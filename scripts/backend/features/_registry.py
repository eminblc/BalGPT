"""Feature manifest registry — OCP-uyumlu plugin sistemi (MOD-10).

Yeni bir feature eklemek için yalnızca bu dosyaya FEATURE_REGISTRY listesine
bir FeatureManifest girdisi eklemek yeterlidir; main.py'ye dokunulmaz.

Her FeatureManifest şu alanları destekler:
  name            — İnsan-okunur isim (loglama için zorunlu)
  enabled         — Callable[[], bool]; feature aktif mi? (varsayılan: lambda: True)
  router_module   — Absolute dotted module yolu, ör. "backend.routers.desktop_router"
  router_attr     — Router nesnesi attribute adı (varsayılan: "router")
  router_prefix   — URL prefix ör. "/whatsapp"; boş string = prefix yok
  startup         — async () → None; uygulama başlarken çağrılır
  shutdown        — async () → None; uygulama kapanırken çağrılır (LIFO sırası)
  capability_rule — dict; ileride capability_guard otomasyonu için ayrılmış
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


# TypedDict yerine basit dict kullanıyoruz — Python 3.9 compat + total=False
# Tip dokümantasyonu yukarıdaki docstring'de.
FeatureManifest = dict[str, Any]


# ── Feature Registry ──────────────────────────────────────────────────────────
# Sıra önemlidir: startup önce → shutdown LIFO (son başlayan ilk durur).

def _build_registry() -> list[FeatureManifest]:
    """Registry'yi settings'e bağlı olmadan tanımla; enabled lambda'ları geç-değerlendirilir."""
    from ..config import settings
    from ..features import webhook_proxy, scheduler, browser

    return [
        # ── Her zaman aktif router'lar ─────────────────────────────────────
        {
            "name": "agent",
            "enabled": lambda: True,
            "router_module": "backend.routers.personal_agent_router",
            "router_prefix": "/agent",
        },
        {
            "name": "internal",
            "enabled": lambda: True,
            "router_module": "backend.routers.internal_router",
            "router_prefix": "",
        },
        {
            "name": "schedule",
            "enabled": lambda: True,
            "router_module": "backend.routers._schedule_router",
            "router_prefix": "",
        },
        # ── Webhook proxy (her zaman aktif, startup/shutdown var) ──────────
        {
            "name": "webhook_proxy",
            "enabled": lambda: True,
            "startup": webhook_proxy.lifecycle_startup,
            "shutdown": webhook_proxy.lifecycle_shutdown,
        },
        # ── Messenger router'ları ──────────────────────────────────────────
        {
            "name": "whatsapp",
            "enabled": lambda: settings.messenger_type.lower() == "whatsapp",
            "router_module": "backend.routers.whatsapp_router",
            "router_prefix": "/whatsapp",
        },
        {
            "name": "telegram",
            "enabled": lambda: settings.messenger_type.lower() == "telegram",
            "router_module": "backend.routers.telegram_router",
            "router_prefix": "/telegram",
        },
        # ── İsteğe bağlı özellikler ───────────────────────────────────────
        {
            "name": "desktop",
            "enabled": lambda: settings.desktop_enabled,
            "router_module": "backend.routers.desktop_router",
            "router_prefix": "",
        },
        {
            "name": "terminal",
            "enabled": lambda: not settings.restrict_shell,
            "router_module": "backend.routers.terminal_router",
            "router_prefix": "",
        },
        {
            "name": "browser",
            "enabled": lambda: settings.browser_enabled,
            "router_module": "backend.routers.browser_router",
            "router_prefix": "",
            "shutdown": browser.lifecycle_shutdown,
        },
        {
            "name": "scheduler",
            "enabled": lambda: settings.scheduler_enabled,
            "startup": scheduler.lifecycle_startup,
            "shutdown": scheduler.lifecycle_shutdown,
        },
    ]


# Modül yüklendiğinde registry oluşturulur (settings singleton hazır olmalı).
# main.py bu modülü app nesnesi oluşturulduktan sonra import eder → sorun yok.
FEATURE_REGISTRY: list[FeatureManifest] = []


def _ensure_registry() -> list[FeatureManifest]:
    """Registry henüz oluşturulmamışsa oluştur ve döndür."""
    global FEATURE_REGISTRY
    if not FEATURE_REGISTRY:
        FEATURE_REGISTRY = _build_registry()
    return FEATURE_REGISTRY


# ── Yardımcı fonksiyonlar — main.py tarafından çağrılır ──────────────────────

def register_routers(app: Any) -> None:
    """Tüm aktif feature router'larını FastAPI app'e kaydet."""
    registry = _ensure_registry()
    for manifest in registry:
        if "router_module" not in manifest:
            continue
        enabled_fn: Callable[[], bool] = manifest.get("enabled", lambda: True)
        if not enabled_fn():
            continue
        module_path: str = manifest["router_module"]
        attr: str = manifest.get("router_attr", "router")
        prefix: str = manifest.get("router_prefix", "")
        name: str = manifest.get("name", module_path)
        try:
            mod = importlib.import_module(module_path)
            router_obj = getattr(mod, attr)
            if prefix:
                app.include_router(router_obj, prefix=prefix)
            else:
                app.include_router(router_obj)
            logger.info("Feature router kaydedildi: %s → %s", name, prefix or "/")
        except Exception as exc:
            logger.error("Feature router kayıt hatası [%s]: %s", name, exc, exc_info=True)
            raise


async def run_startup_hooks() -> None:
    """Tüm aktif feature'ların startup hook'larını sırayla çalıştır."""
    registry = _ensure_registry()
    for manifest in registry:
        enabled_fn: Callable[[], bool] = manifest.get("enabled", lambda: True)
        if not enabled_fn():
            continue
        startup_fn = manifest.get("startup")
        if startup_fn is None:
            continue
        name: str = manifest.get("name", "?")
        try:
            logger.info("Feature startup: %s", name)
            await startup_fn()
        except Exception as exc:
            logger.error("Feature startup hatası [%s]: %s", name, exc, exc_info=True)
            raise


async def run_shutdown_hooks() -> None:
    """Tüm aktif feature'ların shutdown hook'larını LIFO sırasıyla çalıştır."""
    registry = _ensure_registry()
    for manifest in reversed(registry):
        enabled_fn: Callable[[], bool] = manifest.get("enabled", lambda: True)
        if not enabled_fn():
            continue
        shutdown_fn = manifest.get("shutdown")
        if shutdown_fn is None:
            continue
        name: str = manifest.get("name", "?")
        try:
            logger.info("Feature shutdown: %s", name)
            await shutdown_fn()
        except Exception as exc:
            logger.warning("Feature shutdown hatası [%s]: %s", name, exc)
            # Shutdown'da hata diğer shutdown'ları bloklamaz — devam et
