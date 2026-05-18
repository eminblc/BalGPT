"""Ana menü ve interactive reply handler (SRP).

WhatsApp buton/liste menü içerikleri ve reply yönlendirmesi burada.
Proje prefix handler'ları: menu_project.py
"""
from __future__ import annotations

import datetime
from typing import Callable

from ..adapters.messenger import get_messenger as _get_messenger
from ..i18n import t
from .menu_project import PREFIX_HANDLERS as _PROJECT_PREFIX_HANDLERS


# ── Exact-match handlers — signature: (sender, session) ──────────────────

async def _h_menu_chat(sender: str, session: dict) -> None:
    await _get_messenger().send_text(sender, t("menu.chat_mode", session.get("lang", "tr")))


async def _h_menu_plans(sender: str, session: dict) -> None:
    from .plans import list_plans, format_plan_list
    plans = await list_plans()
    await _get_messenger().send_text(sender, format_plan_list(plans))


async def _h_menu_projects(sender: str, session: dict) -> None:
    from .projects import list_projects, format_project_list
    lang     = session.get("lang", "tr")
    projects = await list_projects()
    if not projects:
        await _get_messenger().send_buttons(
            sender,
            t("menu.no_projects", lang),
            [
                {"id": "project_new",  "title": t("menu.new_project_btn", lang)},
                {"id": "menu_chat",    "title": t("menu.chat_btn", lang)},
            ],
        )
    else:
        page = session.get("menu_page", 0)
        menu = format_project_list(projects, page, lang=lang)
        await _get_messenger().send_list(sender, t("menu.projects_title", lang), menu["sections"])


async def _h_project_new(sender: str, session: dict) -> None:
    await _get_messenger().send_text(sender, t("menu.new_project_prompt", session.get("lang", "tr")))
    session.start_project_name()


async def _h_wiz_auto_arch_yes(sender: str, session: dict) -> None:
    from .project_wizard import handle_auto_arch_reply
    await handle_auto_arch_reply(sender, "wiz_auto_arch_yes", session)


async def _h_wiz_auto_arch_no(sender: str, session: dict) -> None:
    from .project_wizard import handle_auto_arch_reply
    await handle_auto_arch_reply(sender, "wiz_auto_arch_no", session)


async def _h_wiz_arch_accept(sender: str, session: dict) -> None:
    # WIZ-LLM-4: Önizleme kabul edildi → AI önerileri session'da kalır,
    # seçenekler menüsüne geç. Gerçek scaffold tüketimi WIZ-LLM-5'te.
    from .project_wizard import ask_options
    await ask_options(sender, session)


async def _h_wiz_arch_edit(sender: str, session: dict) -> None:
    from .project_wizard import ask_arch_edit_input
    await ask_arch_edit_input(sender, session)


async def _h_wiz_arch_skip(sender: str, session: dict) -> None:
    # Önizleme atlandı → AI alanlarını temizle, seçenekler menüsüne geç.
    for key in ("wiz_ai_desc", "wiz_ai_arch", "wiz_ai_stack",
                "wiz_ai_dirs", "wiz_ai_prev_json"):
        session.pop(key, None)
    from .project_wizard import ask_options
    await ask_options(sender, session)


async def _h_wiz_options_confirm(sender: str, session: dict) -> None:
    from .project_wizard import handle_options_reply
    await handle_options_reply(sender, "wiz_options_confirm", session)


async def _h_wiz_path_keep(sender: str, session: dict) -> None:
    from .project_wizard import handle_path_keep
    await handle_path_keep(sender, session)


async def _h_wiz_path_change(sender: str, session: dict) -> None:
    from .project_wizard import ask_path_input
    await ask_path_input(sender, session)


async def _h_wiz_service_more(sender: str, session: dict) -> None:
    from .project_wizard import ask_service_name
    await ask_service_name(sender, session)


async def _h_wiz_show_summary(sender: str, session: dict) -> None:
    from .project_wizard import show_summary
    await show_summary(sender, session)


async def _h_wiz_confirm(sender: str, session: dict) -> None:
    from .project_wizard import confirm_create
    await confirm_create(sender, session)


async def _h_wiz_confirm_overwrite(sender: str, session: dict) -> None:
    # Mevcut dizin uyarısı onaylandı → bayrağı set et ve oluşturmaya devam et (O-2)
    from .project_wizard import confirm_create
    session.set_wizard_overwrite_confirmed()
    await confirm_create(sender, session)


async def _h_wiz_edit_options(sender: str, session: dict) -> None:
    from .project_wizard import handle_edit_summary
    await handle_edit_summary(sender, session)


async def _h_wiz_cancel(sender: str, session: dict) -> None:
    from .project_wizard import cancel_wizard
    await cancel_wizard(sender, session)


async def _h_menu_calendar(sender: str, session: dict) -> None:
    from .calendar import list_upcoming, format_event_list
    events = await list_upcoming()
    await _get_messenger().send_text(sender, format_event_list(events))


async def _h_menu_history(sender: str, session: dict) -> None:
    from .history import get_recent_messages, format_history
    msgs = await get_recent_messages(sender, limit=15)
    await _get_messenger().send_text(sender, format_history(msgs, lang=session.get("lang", "tr")))


async def _h_menu_tasks(sender: str, session: dict) -> None:
    from .scheduler import list_active_tasks
    lang  = session.get("lang", "tr")
    tasks = await list_active_tasks()
    if not tasks:
        await _get_messenger().send_text(sender, t("menu.no_tasks", lang))
    else:
        lines = [t("menu.tasks_header", lang)]
        for task in tasks[:10]:
            nxt = datetime.datetime.fromtimestamp(task["next_run"]).strftime("%d.%m %H:%M") if task.get("next_run") else "?"
            lines.append(f"• {task['description']} — {nxt}")
        await _get_messenger().send_text(sender, "\n".join(lines))


async def _h_cmd_lang(sender: str, session: dict) -> None:
    lang = session.get("lang", "tr")
    await _get_messenger().send_buttons(
        sender,
        t("menu.lang_choose", lang),
        [
            {"id": "lang_tr", "title": t("lang.label_tr", lang)},
            {"id": "lang_en", "title": t("lang.label_en", lang)},
        ],
    )


async def _h_lang_tr(sender: str, session: dict) -> None:
    session["lang"] = "tr"
    from ..store.repositories.settings_repo import user_setting_set
    await user_setting_set(sender, "lang", "tr")
    await _get_messenger().send_text(sender, t("lang.changed", "tr", code="TR"))


async def _h_lang_en(sender: str, session: dict) -> None:
    session["lang"] = "en"
    from ..store.repositories.settings_repo import user_setting_set
    await user_setting_set(sender, "lang", "en")
    await _get_messenger().send_text(sender, t("lang.changed", "en", code="EN"))


async def _h_menu_status(sender: str, session: dict) -> None:
    import httpx
    from ..config import settings
    lang = session.get("lang", "tr")
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(
                f"{settings.claude_bridge_url}/status",
                headers={"X-Api-Key": settings.api_key.get_secret_value()},
            )
            data = r.json()
            sessions = data.get("active_sessions", [])
            msg = t("menu.bridge_ok", lang, sessions=len(sessions))
    except Exception:
        msg = t("menu.bridge_error", lang)
    await _get_messenger().send_text(sender, msg)


async def _h_noop(_sender: str, _session: dict) -> None:
    """Section başlığı butonları — tıklanırsa sessizce yoksay."""


async def _h_noroot_y(sender: str, session: dict) -> None:
    """noroot_y — 99-root projesi ile devam et.

    Pending işlemin project_id'sini 99-root ile doldurur,
    sonraki adıma geçer (scan → üçüncü taraf sorusu; backlog → paralel sorusu).
    """
    from ..i18n import t as _t

    lang    = session.get("lang", "tr")
    pending = session.get("_pending_parallel")
    if pending is None:
        await _get_messenger().send_text(sender, _t("parallel.no_pending", lang))
        return

    from ..guards.commands._root_project_helpers import ensure_99root_in_db

    try:
        project = await ensure_99root_in_db()
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning("noroot_y: 99-root DB hatası — %s", _exc)
        await _get_messenger().send_text(sender, _t("noroot.db_error", lang))
        session.pop("_pending_parallel", None)
        return

    pending["params"]["project_id"] = project["id"]
    pending.pop("_needs_root_confirm", None)
    pending["_display_project"] = project.get("name") or project["id"]

    cmd_type: str = pending["cmd"]

    if cmd_type == "backlog":
        # Paralel seçim sorusu
        project_id   = project["id"]
        prefix       = pending["params"].get("prefix", "")
        prefix_label = f" · prefix: {prefix}" if prefix else ""
        dry_label    = _t("parallel.dry_label", lang) if pending["params"].get("dry_run") else ""
        await _get_messenger().send_buttons(
            sender,
            _t("parallel.backlog_ask", lang, project=f"{project_id}{dry_label}", prefix=prefix_label),
            [
                {"id": "parallel_1", "title": _t("parallel.btn_rec", lang, n=1)},
                {"id": "parallel_2", "title": _t("parallel.btn",     lang, n=2)},
                {"id": "parallel_3", "title": _t("parallel.btn",     lang, n=3)},
            ],
        )
    else:
        # scan / all_scans → üçüncü taraf sorusu
        await _get_messenger().send_buttons(
            sender,
            _t("scan.third_party_ask", lang),
            [
                {"id": "scan3p_n", "title": _t("scan.third_party_skip",    lang)},
                {"id": "scan3p_y", "title": _t("scan.third_party_include", lang)},
            ],
        )


async def _h_noroot_n(sender: str, session: dict) -> None:
    """noroot_n — 99-root onayı reddedildi; işlemi iptal et."""
    session.pop("_pending_parallel", None)
    lang = session.get("lang", "tr")
    await _get_messenger().send_text(sender, t("noroot.cancelled", lang))


# ── Exact-match dispatch table ────────────────────────────────────────────

_EXACT: dict[str, Callable] = {
    "noop":                  _h_noop,
    "menu_chat":             _h_menu_chat,
    "menu_plans":            _h_menu_plans,
    "menu_projects":         _h_menu_projects,
    "project_new":           _h_project_new,
    "wiz_auto_arch_yes":     _h_wiz_auto_arch_yes,
    "wiz_auto_arch_no":      _h_wiz_auto_arch_no,
    "wiz_arch_accept":       _h_wiz_arch_accept,
    "wiz_arch_edit":         _h_wiz_arch_edit,
    "wiz_arch_skip":         _h_wiz_arch_skip,
    "wiz_options_confirm":   _h_wiz_options_confirm,
    "wiz_path_keep":         _h_wiz_path_keep,
    "wiz_path_change":       _h_wiz_path_change,
    "wiz_service_more":      _h_wiz_service_more,
    "wiz_show_summary":      _h_wiz_show_summary,
    "wiz_confirm":           _h_wiz_confirm,
    "wiz_confirm_overwrite": _h_wiz_confirm_overwrite,
    "wiz_edit_options":      _h_wiz_edit_options,
    "wiz_cancel":            _h_wiz_cancel,
    "menu_calendar":         _h_menu_calendar,
    "menu_history":          _h_menu_history,
    "menu_tasks":            _h_menu_tasks,
    "menu_status":           _h_menu_status,
    "cmd_lang":              _h_cmd_lang,
    "lang_tr":               _h_lang_tr,
    "lang_en":               _h_lang_en,
    "noroot_y":              _h_noroot_y,
    "noroot_n":              _h_noroot_n,
}


# ── Prefix handlers — signature: (sender, suffix, session) ───────────────

async def _hp_model_select(sender: str, alias: str, session: dict) -> None:
    from ..guards.commands.model_cmd import handle_model_select
    await handle_model_select(sender, alias, session)


async def _hp_wiz_opt(sender: str, suffix: str, session: dict) -> None:
    from .project_wizard import handle_options_reply
    await handle_options_reply(sender, "wiz_opt_" + suffix, session)


async def _hp_pdf_scaffold(sender: str, level: str, session: dict) -> None:
    _VALID = {"full", "minimal", "none"}
    lang    = session.get("lang", "tr")
    if level not in _VALID:
        await _get_messenger().send_text(sender, t("menu.pdf_unknown_option", lang, option=level))
        return
    media_id = session.pop("pending_pdf", "")
    if not media_id:
        await _get_messenger().send_text(sender, t("menu.pdf_not_found", lang))
        return
    from .pdf_importer import import_from_whatsapp_media
    await import_from_whatsapp_media(media_id, sender, level=level, lang=lang)


async def _hp_cmd_button(sender: str, suffix: str, session: dict) -> None:
    """cmd_<suffix> button'larını registry'deki button_id ile eşleştirip çalıştırır.

    Yeni bir komuta button_id eklemek menü değişikliği gerektirmez (OCP).
    """
    from ..guards.commands.registry import registry
    button_id = "cmd_" + suffix
    cmd = registry.get_by_button_id(button_id)
    if cmd is None:
        lang = session.get("lang", "tr")
        await _get_messenger().send_text(sender, t("menu.unknown_reply", lang, id=button_id))
        return
    await cmd.execute(sender, "", session)


async def _hp_scan_button(sender: str, suffix: str, session: dict) -> None:
    """scan_<suffix> butonlarını ScanCommand.execute'a yönlendirir.

    Örnekler: scan_security → arg="security", scan_status → arg="status"
    """
    from ..guards.commands.scan_cmd import ScanCommand
    await ScanCommand().execute(sender, suffix, session)


async def _hp_backlog_button(sender: str, suffix: str, session: dict) -> None:
    """backlog_<suffix> butonlarını BacklogCommand.execute'a yönlendirir.

    Örnekler: backlog_run_myproject → arg="run myproject", backlog_status → arg="status"
    """
    from ..guards.commands.backlog_cmd import BacklogCommand
    # "run_myproject" → "run myproject" (ilk alt çizgiyi boşluğa çevir)
    arg = suffix.replace("_", " ", 1)
    await BacklogCommand().execute(sender, arg, session)


async def _hp_scan3p(sender: str, choice: str, session: dict) -> None:
    """scan3p_y / scan3p_n — üçüncü taraf dahil etme tercihini kaydeder, paralel seçim gösterir."""
    from ..i18n import t as _t

    lang    = session.get("lang", "tr")
    pending = session.get("_pending_parallel")
    if pending is None:
        await _get_messenger().send_text(sender, _t("parallel.no_pending", lang))
        return

    pending["params"]["include_third_party"] = (choice == "y")

    display_name    = pending.get("_display_name", "")
    display_project = pending.get("_display_project", "")
    dry_label       = _t("parallel.dry_label", lang) if pending["params"].get("dry_run") else ""

    await _get_messenger().send_buttons(
        sender,
        _t("parallel.scan_ask", lang, name=display_name, project=display_project, dry=dry_label),
        [
            {"id": "parallel_2", "title": _t("parallel.btn",     lang, n=2)},
            {"id": "parallel_3", "title": _t("parallel.btn",     lang, n=3)},
            {"id": "parallel_4", "title": _t("parallel.btn_rec", lang, n=4)},
        ],
    )


async def _hp_parallel_select(sender: str, n_str: str, session: dict) -> None:
    """parallel_<N> butonunu işler.

    Backlog: hemen başlatır.
    Scan / all_scans: paralel sayısını pending'e kaydeder, model seçimi sorusuna geçer.
    """
    from ..i18n import t as _t

    lang    = session.get("lang", "tr")
    pending = session.get("_pending_parallel")
    if pending is None:
        await _get_messenger().send_text(sender, _t("parallel.no_pending", lang))
        return

    try:
        n = int(n_str)
    except ValueError:
        await _get_messenger().send_text(sender, _t("parallel.no_pending", lang))
        return

    cmd_type: str = pending["cmd"]

    if cmd_type == "backlog":
        # Backlog: model seçimi yok — hemen başlat
        import httpx as _httpx
        params: dict = session.pop("_pending_parallel")["params"]
        try:
            async with _httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    "http://localhost:8010/internal/backlog/execute",
                    json={**params, "parallel": n},
                )
            await _get_messenger().send_text(
                sender, _t("parallel.backlog_launched", lang, parallel=n)
            )
        except Exception as _exc:
            import logging as _logging
            _logging.getLogger(__name__).warning("parallel_select(backlog): trigger başarısız — %s", _exc)
        return

    # scan / all_scans → paraleli kaydet, model sorusuna geç
    pending["params"]["parallel"] = n
    await _get_messenger().send_buttons(
        sender,
        _t("scan_model.ask", lang),
        [
            {"id": "scanmodel_haiku",  "title": _t("scan_model.btn_haiku",  lang)},
            {"id": "scanmodel_sonnet", "title": _t("scan_model.btn_sonnet", lang)},
            {"id": "scanmodel_opus",   "title": _t("scan_model.btn_opus",   lang)},
        ],
    )


async def _hp_scan_model_select(sender: str, alias: str, session: dict) -> None:
    """scanmodel_<alias> butonunu işler: scan modelini kaydeder, reviewer model sorusunu gösterir."""
    from ..i18n import t as _t

    lang    = session.get("lang", "tr")
    pending = session.get("_pending_parallel")
    if pending is None:
        await _get_messenger().send_text(sender, _t("parallel.no_pending", lang))
        return

    pending["params"]["scan_model"] = alias  # "haiku" | "sonnet" | "opus"

    await _get_messenger().send_buttons(
        sender,
        _t("scan_model.ask_review", lang),
        [
            {"id": "reviewmodel_haiku",  "title": _t("scan_model.btn_haiku",  lang)},
            {"id": "reviewmodel_sonnet", "title": _t("scan_model.btn_sonnet", lang)},
            {"id": "reviewmodel_opus",   "title": _t("scan_model.btn_opus",   lang)},
        ],
    )


async def _hp_review_model_select(sender: str, alias: str, session: dict) -> None:
    """reviewmodel_<alias> butonunu işler: reviewer modelini kaydeder ve scan/all_scans başlatır."""
    import httpx as _httpx
    from ..i18n import t as _t

    lang    = session.get("lang", "tr")
    pending = session.pop("_pending_parallel", None)
    if pending is None:
        await _get_messenger().send_text(sender, _t("parallel.no_pending", lang))
        return

    cmd_type: str = pending["cmd"]
    params: dict  = pending["params"]
    params["review_model"] = alias  # "haiku" | "sonnet" | "opus"
    parallel: int = params.get("parallel", 3)

    try:
        async with _httpx.AsyncClient(timeout=5.0) as client:
            if cmd_type == "scan":
                resp = await client.post(
                    "http://localhost:8010/internal/scanner/trigger",
                    json=params,
                )
            elif cmd_type == "all_scans":
                resp = await client.post(
                    "http://localhost:8010/internal/scanner/trigger-all",
                    json=params,
                )
            else:
                resp = None

        if resp is not None and resp.status_code == 409:
            await _get_messenger().send_text(sender, _t("scan.already_running", lang))
            return

        await _get_messenger().send_text(
            sender, _t("parallel.scan_launched", lang, parallel=parallel)
        )
    except Exception as _exc:
        import logging as _logging
        _logging.getLogger(__name__).warning("review_model_select: trigger başarısız — %s", _exc)


# ── Prefix dispatch table: (prefix, handler) — matched in order ──────────

_PREFIX: list[tuple[str, Callable]] = [
    ("model_select_", _hp_model_select),
    ("wiz_opt_",      _hp_wiz_opt),
    ("pdf_scaffold_", _hp_pdf_scaffold),
    ("scan3p_",       _hp_scan3p),
    ("parallel_",     _hp_parallel_select),
    ("scanmodel_",    _hp_scan_model_select),
    ("reviewmodel_",  _hp_review_model_select),
    ("scan_",         _hp_scan_button),
    ("backlog_",      _hp_backlog_button),
    ("cmd_",          _hp_cmd_button),
    *_PROJECT_PREFIX_HANDLERS,
]


# ── Public entry point ────────────────────────────────────────────────────

def is_handled_locally(reply_id: str) -> bool:
    """True if reply_id matches a known local (99-root) menu handler.

    Used by _dispatcher to decide whether to forward to beta project or handle locally.
    """
    if reply_id in _EXACT:
        return True
    for prefix, _ in _PREFIX:
        if reply_id.startswith(prefix):
            return True
    return False


async def handle_menu_reply(sender: str, reply_id: str, session: dict) -> None:
    """Buton/liste cevabını işle."""
    if reply_id in _EXACT:
        await _EXACT[reply_id](sender, session)
        return
    for prefix, handler in _PREFIX:
        if reply_id.startswith(prefix):
            await handler(sender, reply_id[len(prefix):], session)
            return
    await _get_messenger().send_text(sender, t("menu.unknown_reply", session.get("lang", "tr"), id=reply_id))
