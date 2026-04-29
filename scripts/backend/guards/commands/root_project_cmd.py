"""/root-project komutu — root ajana aktif proje bağlamı ata.

Kullanım:
  /root-project <proje-id>  → Root proje olarak ayarla, bridge session sıfırla
  /root-project             → Mevcut root proje bilgisini göster
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from .registry import registry
from ..permission import Perm
from ...app_types import ACTIVE_CONTEXT_PATH as _ACTIVE_CONTEXT_PATH  # REFAC-18

logger = logging.getLogger(__name__)
_PROJECT_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


def _set_active_root_project(project: dict) -> None:
    """active_context.json dosyasının active_root_project alanını güncelle."""
    try:
        ctx = json.loads(_ACTIVE_CONTEXT_PATH.read_text(encoding="utf-8")) if _ACTIVE_CONTEXT_PATH.exists() else {}
    except Exception:
        ctx = {}
    ctx["schema_version"] = 1
    ctx["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ctx["active_root_project"] = {
        "id":   project["id"],
        "name": project["name"],
        "path": project["path"],
    }
    _ACTIVE_CONTEXT_PATH.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.debug("active_root_project ayarlandı: %s", project["id"])


class RootProjectCommand:
    cmd_id      = "/root-project"
    perm        = Perm.OWNER
    label       = "Root Proje Seç"
    description = "Root ajana proje bağlamı atar; cwd ve CLAUDE.md o projeye göre değişir."
    usage       = "/root-project <proje-id>"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...store import sqlite_store as db
        from ...features.chat import reset_bridge_session

        from ...i18n import t
        lang       = session.get("lang", "tr")
        project_id = arg.strip()

        # Argümansız çağrıda mevcut durumu göster
        if not project_id:
            try:
                ctx = json.loads(_ACTIVE_CONTEXT_PATH.read_text(encoding="utf-8")) if _ACTIVE_CONTEXT_PATH.exists() else {}
                rp = ctx.get("active_root_project")
                if rp:
                    await get_messenger().send_text(sender, t("root_project.status", lang, name=rp["name"], id=rp["id"], path=rp["path"]))
                else:
                    await get_messenger().send_text(sender, t("root_project.none", lang))
            except Exception as exc:
                logger.error("active_context.json okunamadı: %s", exc)
                await get_messenger().send_text(sender, t("root_project.read_error", lang))
            return

        if not _PROJECT_ID_RE.match(project_id):
            await get_messenger().send_text(sender, t("root_project.invalid_id", lang))
            return

        project = await db.project_get(project_id)
        if not project:
            await get_messenger().send_text(sender, t("root_project.not_found", lang, id=project_id))
            return

        _set_active_root_project(project)
        await reset_bridge_session("main")
        await get_messenger().send_text(sender, t("root_project.set_ok", lang, name=project["name"], path=project["path"]))


registry.register(RootProjectCommand())
