"""!restart komutu — servisleri systemctl restart ile yeniden başlat."""
import asyncio
import logging

from .registry import registry
from ..permission import Perm

logger = logging.getLogger(__name__)

SERVICES = [
    "personal-agent-bridge.service",
    "personal-agent.service",  # Bu servis en son yeniden başlatılır (mevcut süreç)
]


def _on_restart_done(task: asyncio.Task) -> None:
    """RR-3: Task exception'ı sessizce kaybolmasın."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("_do_restart beklenmedik exception: %s", exc, exc_info=exc)


async def _do_restart() -> None:
    """Mesaj gönderildikten sonra arka planda servisleri yeniden başlatır."""
    from ...config import settings
    from ...adapters.messenger import get_messenger

    await asyncio.sleep(1)
    for svc in SERVICES:
        try:
            # RR-1: asyncio.create_subprocess_exec — event loop bloklamaz
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
                # RR-5: bridge başarısız → kullanıcıya bildir
                if svc == "personal-agent-bridge.service" and settings.owner_id:
                    from ...i18n import t
                    await get_messenger().send_text(
                        settings.owner_id,
                        t("restart.bridge_timeout", "tr", svc=svc),
                    )
                continue
            if proc.returncode != 0:
                stderr_str = stderr_bytes.decode(errors="replace").strip()
                logger.error("Servis yeniden başlatılamadı: %s — %s", svc, stderr_str)
                # RR-5: bridge başarısız → kullanıcıya bildir
                if svc == "personal-agent-bridge.service" and settings.owner_id:
                    from ...i18n import t
                    await get_messenger().send_text(
                        settings.owner_id,
                        t("restart.bridge_failed", "tr", svc=svc, error=stderr_str[:200] or "Hata detayı yok"),
                    )
            else:
                logger.info("Servis yeniden başlatıldı: %s", svc)
        except Exception as exc:
            logger.error("_do_restart beklenmedik hata: %s — %s", svc, exc)


class RestartCommand:
    cmd_id      = "!restart"
    perm        = Perm.OWNER_ADMIN_TOTP
    button_id   = "cmd_restart"
    label       = "Servisleri Yeniden Başlat"
    description = "personal-agent ve bridge servislerini systemctl restart ile yeniden başlatır."
    usage       = "!restart"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger

        # RR-2: restart önce başlatılır — send_text hatasına bağımlı değil
        task = asyncio.create_task(_do_restart())
        task.add_done_callback(_on_restart_done)  # RR-3: exception yakalanır

        try:
            from ...i18n import t
            await get_messenger().send_text(sender, t("restart.starting", session.get("lang", "tr")))
        except Exception as exc:
            logger.warning("!restart bildirim gönderilemedi (restart devam ediyor): %s", exc)


registry.register(RestartCommand())
