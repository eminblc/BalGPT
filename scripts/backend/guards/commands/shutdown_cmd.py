"""!shutdown komutu — FastAPI servisini güvenli şekilde kapat."""
import logging
import os
import signal

from .registry import registry
from ..permission import Perm

logger = logging.getLogger(__name__)


class ShutdownCommand:
    cmd_id      = "!shutdown"
    perm        = Perm.OWNER_ADMIN_TOTP
    button_id   = "cmd_shutdown"
    label       = "Sunucuyu Kapat"
    description = "FastAPI servisini güvenli şekilde kapatır. Yeniden başlatmak için sunucuya elle erişim gerekir."
    usage       = "!shutdown"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t
        await get_messenger().send_text(sender, t("shutdown.ok", session.get("lang", "tr")))
        logger.warning("!shutdown komutu alındı — SIGTERM gönderiliyor (sender: %s)", sender)
        os.kill(os.getpid(), signal.SIGTERM)


registry.register(ShutdownCommand())
