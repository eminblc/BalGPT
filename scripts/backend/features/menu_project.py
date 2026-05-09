"""Proje menü handler'ları — prefix tabanlı yönlendirme (SRP).

Sorumluluk: project_select_*, project_info_*, project_start_*, project_stop_*,
            project_restart_*, beta_start_*, root_set_*, project_delete_confirm_*,
            projects_next_*, projects_prev_* prefix'li buton/liste cevapları.
Genel menü (exact-match handlers, handle_menu_reply): menu.py
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Callable

from ..adapters.messenger import get_messenger as _get_messenger
from ..i18n import t

# BUG-M2: project_id güvenli karakter kalıbı — yalnızca alphanum, tire, alt çizgi (max 64)
_PROJECT_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


async def _hp_project_select(sender: str, project_id: str, session: dict) -> None:
    lang = session.get("lang", "tr")
    if not _PROJECT_ID_RE.match(project_id):
        await _get_messenger().send_text(sender, t("menu.invalid_project_id", lang))
        return
    from .projects import get_project
    from ..app_types import PROJECT_STATUS_EMOJI as _S
    project = await get_project(project_id)
    status = project.get("status", "idle") if project else "?"
    emoji = _S.get(status, "⚪")
    name = project["name"] if project else project_id
    body = f"{emoji} *{name}*\n{t('project_menu.info_status', lang)}: {status}"
    await _get_messenger().send_list(
        sender,
        body,
        [
            {
                "title": t("project_menu.sec_run", lang),
                "rows": [
                    {"id": f"project_start_{project_id}",   "title": t("project_menu.start_title", lang),   "description": t("project_menu.start_desc", lang)},
                    {"id": f"project_stop_{project_id}",    "title": t("project_menu.stop_title", lang),    "description": t("project_menu.stop_desc", lang)},
                    {"id": f"project_restart_{project_id}", "title": t("project_menu.restart_title", lang), "description": t("project_menu.restart_desc", lang)},
                ],
            },
            {
                "title": t("project_menu.sec_mode", lang),
                "rows": [
                    {"id": f"beta_start_{project_id}",            "title": t("project_menu.beta_title", lang),      "description": t("project_menu.beta_desc", lang)},
                    {"id": f"root_set_{project_id}",              "title": t("project_menu.root_set_title", lang),  "description": t("project_menu.root_set_desc", lang)},
                    {"id": f"project_info_{project_id}",          "title": t("project_menu.info_title", lang),      "description": t("project_menu.info_desc", lang)},
                    {"id": f"project_delete_confirm_{project_id}","title": t("project_menu.delete_title", lang),    "description": t("project_menu.delete_desc", lang)},
                    {"id": "menu_projects",                       "title": t("project_menu.back_title", lang),      "description": t("project_menu.back_desc", lang)},
                ],
            },
        ],
    )


async def _hp_project_info(sender: str, project_id: str, session: dict) -> None:
    lang = session.get("lang", "tr")
    if not _PROJECT_ID_RE.match(project_id):
        await _get_messenger().send_text(sender, t("menu.invalid_project_id", lang))
        return
    from .projects import get_project
    from ..app_types import PROJECT_STATUS_EMOJI as _S
    p = await get_project(project_id)
    if not p:
        await _get_messenger().send_text(sender, t("menu.project_not_found", lang, id=project_id))
        return
    emoji = _S.get(p.get("status", "idle"), "⚪")
    try:
        meta = json.loads(p.get("metadata") or "{}")
        services = meta.get("services", [])
        # BUG-H2: services tipi doğrulaması
        if not isinstance(services, list):
            services = []
        svc_lines = "\n".join(
            f"  • {s.get('name','?')} → port {s.get('port','?')}" for s in services
            if isinstance(s, dict)
        ) if services else f"  {t('project_menu.info_svc_undefined', lang)}"
    except Exception:
        svc_lines = f"  {t('project_menu.info_svc_unreadable', lang)}"
    msg = (
        f"{emoji} *{p['name']}*\n"
        f"{t('project_menu.info_status', lang)}: {p.get('status','?')}\n"
        f"{t('project_menu.info_path', lang)}: `{p.get('path','?')}`\n"
        f"{t('project_menu.info_desc_label', lang)}: {p.get('description','') or '—'}\n"
        f"{t('project_menu.info_svc', lang)}:\n{svc_lines}"
    )
    await _get_messenger().send_text(sender, msg)


async def _hp_project_start(sender: str, project_id: str, session: dict) -> None:
    if not _PROJECT_ID_RE.match(project_id):
        await _get_messenger().send_text(sender, t("menu.invalid_project_id", session.get("lang", "tr")))
        return
    from .projects import start_project_services
    await start_project_services(project_id, sender, lang=session.get("lang", "tr"))


async def _hp_project_stop(sender: str, project_id: str, session: dict) -> None:
    if not _PROJECT_ID_RE.match(project_id):
        await _get_messenger().send_text(sender, t("menu.invalid_project_id", session.get("lang", "tr")))
        return
    from .projects import stop_project_services
    await stop_project_services(project_id, sender, lang=session.get("lang", "tr"))


async def _hp_project_restart(sender: str, project_id: str, session: dict) -> None:
    if not _PROJECT_ID_RE.match(project_id):
        await _get_messenger().send_text(sender, t("menu.invalid_project_id", session.get("lang", "tr")))
        return
    from .projects import start_project_services, stop_project_services
    lang = session.get("lang", "tr")
    await stop_project_services(project_id, sender, lang=lang)
    await asyncio.sleep(1)
    await start_project_services(project_id, sender, lang=lang)


async def _hp_beta_start(sender: str, project_id: str, session: dict) -> None:
    lang = session.get("lang", "tr")
    if not _PROJECT_ID_RE.match(project_id):
        await _get_messenger().send_text(sender, t("menu.invalid_project_id", lang))
        return
    from .projects import start_beta_mode
    await start_beta_mode(project_id, sender, lang=lang)


async def _hp_root_set(sender: str, project_id: str, session: dict) -> None:
    if not _PROJECT_ID_RE.match(project_id):
        await _get_messenger().send_text(sender, t("menu.invalid_project_id", session.get("lang", "tr")))
        return
    from .projects import get_project
    from ..guards.commands.root_project_cmd import _set_active_root_project
    from .chat import reset_bridge_session
    project = await get_project(project_id)
    if not project:
        await _get_messenger().send_text(sender, t("menu.project_not_found", session.get("lang", "tr"), id=project_id))
        return
    _set_active_root_project(project)
    await reset_bridge_session("main")
    await _get_messenger().send_text(sender, t("root_project.set_ok", session.get("lang", "tr"), name=project["name"], path=project["path"]))


async def _hp_project_delete_confirm(sender: str, project_id: str, session: dict) -> None:
    if not _PROJECT_ID_RE.match(project_id):
        await _get_messenger().send_text(sender, t("menu.invalid_project_id", session.get("lang", "tr")))
        return
    from .projects import get_project
    project = await get_project(project_id)
    if not project:
        await _get_messenger().send_text(sender, t("menu.project_not_found", session.get("lang", "tr"), id=project_id))
        return
    session.start_totp(cmd=f"/project-delete {project_id}")
    await _get_messenger().send_text(
        sender,
        t("menu.project_delete_totp", session.get("lang", "tr"), name=project["name"]),
    )


async def _hp_projects_page(sender: str, page_str: str, session: dict) -> None:
    try:
        page = int(page_str)
    except ValueError:
        page = 0
    session["menu_page"] = page
    # Döngüsel import önlemek için lazy import
    from .menu import handle_menu_reply
    await handle_menu_reply(sender, "menu_projects", session)


# ── Prefix dispatch tablosu (menu.py tarafından tüketilir) ───────────────────

PREFIX_HANDLERS: list[tuple[str, Callable]] = [
    ("project_select_",         _hp_project_select),
    ("project_info_",           _hp_project_info),
    ("project_start_",          _hp_project_start),
    ("project_stop_",           _hp_project_stop),
    ("project_restart_",        _hp_project_restart),
    ("beta_start_",             _hp_beta_start),
    ("root_set_",               _hp_root_set),
    ("project_delete_confirm_", _hp_project_delete_confirm),
    ("projects_next_",          _hp_projects_page),
    ("projects_prev_",          _hp_projects_page),
]
