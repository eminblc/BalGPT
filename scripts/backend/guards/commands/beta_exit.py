"""!beta-exit komutu — beta modundan ana ajana dön."""
from .registry import registry
from ..permission import Perm


class BetaExitCommand:
    cmd_id      = "!beta-exit"
    perm        = Perm.OWNER
    label       = "Beta'dan Çık"
    description = "Proje beta modundan ana ajana döner."
    usage       = "!beta-exit"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from .. import session_mgr

        from ...i18n import t
        lang = session.get("lang", "tr")
        if session.get("active_context", "main") == "main":
            await get_messenger().send_text(sender, t("beta_exit.already_main", lang))
            return

        project_id = session.get("beta_project_id", "")
        # exit_beta() özet kaydeder ve started_at'ı sıfırlar
        session_mgr.exit_beta(sender)
        await get_messenger().send_text(sender, t("beta_exit.ok", lang, id=project_id))


registry.register(BetaExitCommand())
