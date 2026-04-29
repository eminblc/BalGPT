"""/beta komutu — beta moduna gir veya beta modundan ana ajana dön.

/beta               → beta modundan çık (ya da zaten ana modda bilgilendir)
/beta <proje_adı>   → belirtilen projenin beta modunu başlat (id veya isimle eşleşir)
"""
from .registry import registry
from ..permission import Perm


class BetaExitCommand:
    cmd_id      = "/beta"
    perm        = Perm.OWNER
    label       = "Beta Modu"
    description = "Beta modunu başlat (/beta <proje>) veya beta modundan çık (/beta)."
    usage       = "/beta [proje_adı]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from .. import session_mgr
        from ...i18n import t

        lang = session.get("lang", "tr")
        messenger = get_messenger()

        # Argüman varsa → projeye göre beta modunu başlat
        if arg:
            await self._start_beta(sender, arg, session, lang, messenger, session_mgr)
            return

        # Argüman yok → beta modundan çık
        if session.get("active_context", "main") == "main":
            await messenger.send_text(sender, t("beta_exit.already_main", lang))
            return

        project_id = session.get("beta_project_id", "")
        session_mgr.exit_beta(sender)
        await messenger.send_text(sender, t("beta_exit.ok", lang, id=project_id))

    async def _start_beta(self, sender: str, arg: str, session: dict,
                          lang: str, messenger, session_mgr) -> None:
        """İsim veya id ile projeyi bul ve beta modunu başlat."""
        from ...features.project_crud import list_projects, start_beta_mode
        from ...i18n import t

        projects = await list_projects()
        project = next(
            (p for p in projects
             if p["id"] == arg or p["name"].lower() == arg.lower()),
            None,
        )
        if not project:
            await messenger.send_text(sender, t("beta_exit.not_found", lang, arg=arg))
            return

        # Mevcut beta oturumu varsa önce çık
        if session.get("active_context", "main") != "main":
            session_mgr.exit_beta(sender)

        await start_beta_mode(project["id"], sender, lang=lang)


registry.register(BetaExitCommand())
