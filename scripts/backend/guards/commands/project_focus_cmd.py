"""/project komutu — aktif projeyi değiştir (ana mod bağlamı için)."""
from .registry import registry
from ..permission import Perm


class ProjectFocusCommand:
    cmd_id      = "/project"
    perm        = Perm.OWNER
    label       = "Proje Odağı"
    description = "Aktif projeyi değiştirir. ID vermezsen mevcut projeyi ve seçenekleri gösterir. 'none' yazarsan aktif projeyi temizler."
    usage       = "/project [id|none]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...store import sqlite_store as db
        from ...adapters.messenger import get_messenger
        from ...features.projects import update_active_context_project
        from ...guards import get_session_mgr

        from ...i18n import t
        lang       = session.get("lang", "tr")
        project_id = arg.strip()

        if project_id.lower() == "none":
            get_session_mgr().set_active_project(sender, None)
            update_active_context_project(None)
            await get_messenger().send_text(sender, t("project.cleared", lang))
            return

        if not project_id:
            # Mevcut aktif projeyi göster
            current = session.get("active_project_id")
            if current:
                p = await db.project_get(current)
                name = p["name"] if p else current
                await get_messenger().send_text(sender, t("project.active", lang, name=name))
            else:
                projects = await db.project_list()
                lines = [t("project.none_active", lang)]
                for p in projects[:8]:
                    lines.append(f"  /project {p['id']}  → {p['name']}")
                await get_messenger().send_text(sender, "\n".join(lines))
            return

        project = await db.project_get(project_id)
        if not project:
            await get_messenger().send_text(sender, t("project.not_found", lang, id=project_id))
            return

        get_session_mgr().set_active_project(sender, project_id)
        update_active_context_project(project)
        await get_messenger().send_text(sender, t("project.set_ok", lang, name=project["name"]))


registry.register(ProjectFocusCommand())
