"""/wizard — Stage-2 install wizard'ı başlatır (Telegram inline butonlu).

install.sh sadece Bot Token + Chat ID + ngrok bilgilerini terminalde toplar.
LLM seçimi, capabilities, timezone ve TOTP QR'ları bu komutla Telegram üzerinden
tamamlanır.
"""
from __future__ import annotations

import logging

from .registry import registry
from ..permission import Perm

logger = logging.getLogger(__name__)


class WizardCommand:
    cmd_id      = "/wizard"
    perm        = Perm.OWNER
    hidden      = True   # beta — /help ve slash menüde gösterilmez
    label       = "Kurulum Sihirbazı"
    description = "Kurulum tamamlanma sihirbazını başlatır (LLM, yetenekler, TOTP)."
    usage       = "/wizard"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...features.install_wizard import start_or_resume_wizard

        lang = session.get("lang", "tr")
        await start_or_resume_wizard(sender, lang)


registry.register(WizardCommand())
