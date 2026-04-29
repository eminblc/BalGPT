"""/restart komutu — servisleri ortama göre yeniden başlat (systemd | docker | pm2)."""
import asyncio
import logging
import os
import signal

from .registry import registry
from ._runtime import detect_runtime
from ..permission import Perm

logger = logging.getLogger(__name__)

_SYSTEMD_SERVICES = [
    "personal-agent-bridge.service",
    "personal-agent.service",
]
_PM2_APPS = ["99-bridge", "99-api"]


def _on_restart_done(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("_do_restart beklenmedik exception: %s", exc, exc_info=exc)


async def _restart_systemd() -> None:
    from ...config import settings
    from ...adapters.messenger import get_messenger
    from ...i18n import t

    for svc in _SYSTEMD_SERVICES:
        try:
            proc = await asyncio.create_subprocess_exec(
                "sudo", "-n", "systemctl", "restart", svc,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=15)
            except asyncio.TimeoutError:
                proc.kill()
                logger.error("Servis zaman aşımı: %s", svc)
                if svc == "personal-agent-bridge.service" and settings.owner_id:
                    await get_messenger().send_text(
                        settings.owner_id,
                        t("restart.bridge_timeout", "tr", svc=svc),
                    )
                continue
            if proc.returncode != 0:
                stderr_str = stderr_bytes.decode(errors="replace").strip()
                logger.error("Servis yeniden başlatılamadı: %s — %s", svc, stderr_str)
                if svc == "personal-agent-bridge.service" and settings.owner_id:
                    await get_messenger().send_text(
                        settings.owner_id,
                        t("restart.bridge_failed", "tr", svc=svc, error=stderr_str[:200] or "Hata detayı yok"),
                    )
            else:
                logger.info("Servis yeniden başlatıldı: %s", svc)
        except Exception as exc:
            logger.error("_restart_systemd hata: %s — %s", svc, exc)


async def _restart_docker() -> None:
    import httpx
    from ...config import settings

    # Bridge: /restart endpoint'i çağır → process.exit(0) → Docker yeniden başlatır
    try:
        headers = {"X-Api-Key": settings.api_key.get_secret_value()}
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{settings.claude_bridge_url}/restart",
                headers=headers,
                timeout=5,
            )
        logger.info("Bridge Docker restart isteği gönderildi")
    except Exception as exc:
        logger.error("Bridge Docker restart isteği başarısız: %s", exc)

    # API: SIGTERM → Docker container'ı yeniden başlatır (restart: unless-stopped)
    await asyncio.sleep(1)
    logger.info("API SIGTERM ile yeniden başlatılıyor (Docker)")
    os.kill(os.getpid(), signal.SIGTERM)


async def _restart_pm2() -> None:
    from ...config import settings
    from ...adapters.messenger import get_messenger
    from ...i18n import t

    for app in _PM2_APPS:
        try:
            proc = await asyncio.create_subprocess_exec(
                "pm2", "restart", app,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=15)
            except asyncio.TimeoutError:
                proc.kill()
                logger.error("PM2 restart zaman aşımı: %s", app)
                continue
            if proc.returncode != 0:
                stderr_str = stderr_bytes.decode(errors="replace").strip()
                logger.error("PM2 restart başarısız: %s — %s", app, stderr_str)
                if settings.owner_id:
                    await get_messenger().send_text(
                        settings.owner_id,
                        t("restart.pm2_failed", "tr", app=app, error=stderr_str[:200] or "Hata detayı yok"),
                    )
            else:
                logger.info("PM2 app yeniden başlatıldı: %s", app)
        except Exception as exc:
            logger.error("_restart_pm2 hata: %s — %s", app, exc)


async def _do_restart() -> None:
    await asyncio.sleep(1)
    runtime = detect_runtime()
    logger.info("/restart çalışma ortamı: %s", runtime)
    if runtime == "docker":
        await _restart_docker()
    elif runtime == "pm2":
        await _restart_pm2()
    else:
        await _restart_systemd()


class RestartCommand:
    cmd_id      = "/restart"
    perm        = Perm.OWNER_TOTP
    button_id   = "cmd_restart"
    label       = "Servisleri Yeniden Başlat"
    description = "Servisleri ortama göre yeniden başlatır (systemd | docker | pm2)."
    usage       = "/restart"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        task = asyncio.create_task(_do_restart())
        task.add_done_callback(_on_restart_done)

        try:
            await get_messenger().send_text(sender, t("restart.starting", session.get("lang", "tr")))
        except Exception as exc:
            logger.warning("/restart bildirim gönderilemedi (restart devam ediyor): %s", exc)


registry.register(RestartCommand())
