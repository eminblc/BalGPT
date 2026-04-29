"""/shutdown komutu — servisleri ortama göre durdur (systemd | docker | pm2)."""
import asyncio
import logging
import os
import signal

from .registry import registry
from ._runtime import detect_runtime
from ..permission import Perm

logger = logging.getLogger(__name__)

_PM2_APPS = ["99-bridge", "99-api"]


class ShutdownCommand:
    cmd_id      = "/shutdown"
    perm        = Perm.OWNER_TOTP
    button_id   = "cmd_shutdown"
    label       = "Sunucuyu Kapat"
    description = "Servisleri ortama göre durdurur (systemd | docker | pm2)."
    usage       = "/shutdown"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        lang = session.get("lang", "tr")
        runtime = detect_runtime()
        logger.warning("/shutdown komutu alındı — ortam: %s (sender: %s)", runtime, sender)

        if runtime == "docker":
            await get_messenger().send_text(sender, t("shutdown.docker_warning", lang))
            await asyncio.sleep(1)
            os.kill(os.getpid(), signal.SIGTERM)
        elif runtime == "pm2":
            await get_messenger().send_text(sender, t("shutdown.ok", lang))
            await asyncio.sleep(1)
            await self._stop_pm2()
        else:
            await get_messenger().send_text(sender, t("shutdown.ok", lang))
            await asyncio.sleep(1)
            os.kill(os.getpid(), signal.SIGTERM)

    async def _stop_pm2(self) -> None:
        for app in _PM2_APPS:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "pm2", "stop", app,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc.communicate(), timeout=10)
                logger.info("PM2 app durduruldu: %s", app)
            except Exception as exc:
                logger.error("PM2 stop hata: %s — %s", app, exc)


registry.register(ShutdownCommand())
