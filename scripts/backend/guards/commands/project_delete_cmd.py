"""/project-delete <id> — projeyi DB'den siler (yalnızca kayıt; dosya sistemi dokunulmaz).

Yetki: OWNER_TOTP — matematik challenge + owner TOTP gerektirir.
"""
import logging

from .registry import registry
from ..permission import Perm

logger = logging.getLogger(__name__)


class ProjectDeleteCommand:
    cmd_id      = "/project-delete"
    perm        = Perm.OWNER_TOTP
    label       = "Proje Sil"
    description = (
        "Projeyi veritabanından siler. "
        "Dosya sistemi etkilenmez — dizini manuel silmen gerekir."
    )
    usage       = "/project-delete <id>"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...store import sqlite_store as db
        from ...adapters.messenger import get_messenger

        from ...i18n import t
        lang       = session.get("lang", "tr")
        project_id = arg.strip()

        if not project_id:
            projects = await db.project_list()
            if not projects:
                await get_messenger().send_text(sender, t("project_delete.empty", lang))
            else:
                lines = [t("project_delete.list_header", lang)]
                for p in projects:
                    lines.append(f"  • {p['id']}  →  {p['name']}")
                lines.append(t("project_delete.list_footer", lang))
                await get_messenger().send_text(sender, "\n".join(lines))
            return

        project = await db.project_get(project_id)
        if not project:
            await get_messenger().send_text(sender, t("project_delete.not_found", lang, id=project_id))
            return

        deleted = await db.project_delete(project_id)
        if not deleted:
            await get_messenger().send_text(sender, t("project_delete.delete_failed", lang, id=project_id))
            return

        logger.warning(
            "Proje silindi: id=%s name=%s path=%s sender=%s",
            project_id, project.get("name"), project.get("path"), sender,
        )
        await get_messenger().send_text(
            sender,
            t("project_delete.ok", lang,
              name=project["name"], id=project_id, path=project.get("path", "—")),
        )


registry.register(ProjectDeleteCommand())
