"""Proje CRUD ve beta modu — veri erişim ve context yönetimi (SRP).

Sorumluluk: Proje kayıtlarını yönetmek ve active_context.json'ı güncel tutmak.
Servis başlatma/durdurma: project_service.py
Dosya iskeleti: project_scaffold.py
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..store.sqlite_wrapper import store as db  # REFAC-16: StoreProtocol uyumlu wrapper
from .project_scaffold import _scaffold_project
from ..app_types import ACTIVE_CONTEXT_PATH as _ACTIVE_CONTEXT_PATH  # REFAC-18

logger = logging.getLogger(__name__)


def update_active_context_project(project: dict | None) -> None:
    """active_context.json dosyasının active_project alanını güncelle."""
    try:
        ctx = json.loads(_ACTIVE_CONTEXT_PATH.read_text(encoding="utf-8")) if _ACTIVE_CONTEXT_PATH.exists() else {}
    except Exception:
        ctx = {}
    ctx["schema_version"] = 1
    ctx["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if project:
        ctx["active_project"] = {
            "id": project["id"],
            "name": project["name"],
            "path": project["path"],
        }
        if not ctx.get("last_actions"):
            ctx["last_actions"] = []
        if not ctx.get("last_files"):
            ctx["last_files"] = []
        if not ctx.get("session_note"):
            ctx["session_note"] = ""
    else:
        ctx["active_project"] = None
    _ACTIVE_CONTEXT_PATH.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.debug("active_context.json güncellendi: %s", project["id"] if project else "null")


async def create_project(
    name: str,
    description: str = "",
    source_pdf: str | None = None,
    level: str = "full",
    mds: list[str] | None = None,
    metadata: str = "{}",
    path: str | None = None,
    ai_overrides: dict | None = None,
) -> dict:
    """Proje kaydı oluştur + klasör yapısını init et.

    level: "full" | "minimal" | "none"
    mds: None → varsayılan, [] → hiç yok, [..] → belirtilenler
    path: None → varsayılan (40-claude-code-agents/{id})
    ai_overrides: AI wizard önizlemesi kabul edildiyse stack/directories/architecture
                  alanlarını içeren dict; sadece CLAUDE.md'ye ek bloklar yazılır.
    """
    project = await db.project_create(name, description, source_pdf, metadata, path)
    project_dir = Path(project["path"])
    _scaffold_project(project_dir, name, description, level, mds, ai_overrides)
    logger.info("Proje oluşturuldu: %s → %s (level=%s)", name, project_dir, level)
    return project


async def list_projects() -> list[dict]:
    """Tüm projeleri döndür."""
    return await db.project_list()


async def get_project(project_id: str) -> dict | None:
    """Proje detaylarını döndür."""
    return await db.project_get(project_id)


async def start_beta_mode(project_id: str, sender: str, lang: str = "tr") -> None:
    """Beta modunu başlat — session context'ini projeye çevir."""
    from ..guards import get_session_mgr
    from ..adapters.messenger import get_messenger
    from ..i18n import t
    messenger = get_messenger()

    project = await db.project_get(project_id)
    if not project:
        await messenger.send_text(sender, t("project.not_found", lang, id=project_id))
        return

    get_session_mgr().set_beta(sender, project_id)
    await db.project_update_status(project_id, "beta")
    update_active_context_project(project)
    await messenger.send_text(
        sender,
        t("project.beta_started", lang, name=project["name"]),
    )


def format_project_list(projects: list[dict], page: int = 0, page_size: int = 8,
                        lang: str = "tr") -> dict:
    """Proje listesini WhatsApp liste mesajı formatına çevir (pagination ile)."""
    from ..app_types import PROJECT_STATUS_EMOJI as _STATUS_EMOJI
    from ..i18n import t

    total = len(projects)
    start = page * page_size
    end = min(start + page_size, total)
    page_projects = projects[start:end]

    rows = []
    for p in page_projects:
        emoji = _STATUS_EMOJI.get(p["status"], "⚪")
        rows.append({
            "id": f"project_select_{p['id']}",
            "title": f"{emoji} {p['name'][:20]}",
            "description": p.get("description", "")[:50],
        })

    sections = [{"title": t("project_list.section_title", lang, start=start+1, end=end), "rows": rows}]

    nav_rows = []
    if end < total:
        nav_rows.append({"id": f"projects_next_{page+1}", "title": t("project_list.next_page", lang)})
    if page > 0:
        nav_rows.append({"id": f"projects_prev_{page-1}", "title": t("project_list.prev_page", lang)})
    nav_rows.append({"id": "project_new", "title": t("project_list.new_project", lang)})

    if nav_rows:
        sections.append({"title": t("project_list.nav_section", lang), "rows": nav_rows})

    return {"sections": sections, "button_text": t("project_list.select_btn", lang)}
