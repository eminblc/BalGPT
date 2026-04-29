"""/root-reset komutu — ana Claude Code session'ını sıfırla."""
from .registry import registry
from ..permission import Perm


class RootResetCommand:
    cmd_id      = "/root-reset"
    perm        = Perm.OWNER
    button_id   = "cmd_root_reset"
    label       = "Session Sıfırla"
    description = "Ana Claude Code session'ını sıfırlar. Sohbet geçmişi silinir, servis ayakta kalır."
    usage       = "/root-reset"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...features.chat import reset_bridge_session
        from ...features.project_wizard import clear_wizard
        from ...adapters.messenger import get_messenger

        from ...i18n import t
        lang = session.get("lang", "tr")
        clear_wizard(session)
        await get_messenger().send_text(sender, t("root_reset.starting", lang))
        ok = await reset_bridge_session("main")
        if ok:
            await get_messenger().send_text(sender, t("root_reset.ok", lang))
        else:
            await get_messenger().send_text(sender, t("root_reset.failed", lang))


registry.register(RootResetCommand())
