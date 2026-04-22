"""Wizard sabitleri, yardımcı fonksiyonlar ve temizleme (SRP).

Adım fonksiyonları wizard_steps.py'de; bu modül yalnızca paylaşılan
sabitler, hesaplama yardımcıları ve session temizleme içerir.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..store.sqlite_store import slugify_project_name
from ..i18n import t

logger = logging.getLogger(__name__)

# ── Sabitler ──────────────────────────────────────────────────────

_LEVEL_LABEL_KEYS = {
    "full":    "wizard.level_full",
    "minimal": "wizard.level_minimal",
    "none":    "wizard.level_none",
}


def get_level_label(level: str, lang: str) -> str:
    """Proje türü etiketini lokalize edilmiş olarak döndür."""
    key = _LEVEL_LABEL_KEYS.get(level)
    if key:
        return t(key, lang)
    return level

_MDS_MAP: dict[str, list[str]] = {
    "none":          [],
    "all":           ["CLAUDE.md", "AGENT.md", "BACKLOG.md", "README.md"],
    "claude_readme": ["CLAUDE.md", "README.md"],
    "readme":        ["README.md"],
}

_REVERSE_MDS_MAP: dict[str, str] = {
    str(sorted(v)): k for k, v in _MDS_MAP.items()
}

_DEFAULT_LEVEL = "full"
_DEFAULT_MDS   = "none"
_DEFAULT_SVC   = "no"


# ── Yardımcı fonksiyonlar ─────────────────────────────────────────

def _default_project_path(name: str) -> str:
    """slugify_project_name ile varsayılan proje yolunu döndür."""
    from ..config import settings
    project_id = slugify_project_name(name)
    return str(settings.resolved_projects_dir / project_id)


def _options_sections(session: dict) -> list:
    """Mevcut pending seçimleri yansıtan liste bölümlerini oluştur."""
    lang  = session.get("lang", "tr")
    level = session.get("wiz_pending_level", _DEFAULT_LEVEL)
    mds   = session.get("wiz_pending_mds",   _DEFAULT_MDS)
    svc   = session.get("wiz_pending_svc",   _DEFAULT_SVC)

    def sel(val: str, cur: str) -> str:
        return "✅ " if val == cur else ""

    return [
        {
            "title": t("wizard.opt_sec_level", lang),
            "rows": [
                {"id": "wiz_opt_level_full",    "title": sel("full", level)    + t("wizard.opt_level_full", lang),    "description": t("wizard.opt_level_full_desc", lang)},
                {"id": "wiz_opt_level_minimal", "title": sel("minimal", level) + t("wizard.opt_level_minimal", lang), "description": t("wizard.opt_level_minimal_desc", lang)},
                {"id": "wiz_opt_level_none",    "title": sel("none", level)    + t("wizard.opt_level_none", lang),    "description": t("wizard.opt_level_none_desc", lang)},
            ],
        },
        {
            "title": t("wizard.opt_sec_mds", lang),
            "rows": [
                {"id": "wiz_opt_mds_none",          "title": sel("none", mds)          + t("wizard.opt_mds_none", lang),          "description": t("wizard.opt_mds_none_desc", lang)},
                {"id": "wiz_opt_mds_all",           "title": sel("all", mds)           + t("wizard.opt_mds_all", lang),           "description": t("wizard.opt_mds_all_desc", lang)},
                {"id": "wiz_opt_mds_claude_readme", "title": sel("claude_readme", mds) + t("wizard.opt_mds_claude_readme", lang), "description": t("wizard.opt_mds_claude_readme_desc", lang)},
                {"id": "wiz_opt_mds_readme",        "title": sel("readme", mds)        + t("wizard.opt_mds_readme", lang),        "description": t("wizard.opt_mds_readme_desc", lang)},
            ],
        },
        {
            "title": t("wizard.opt_sec_svc", lang),
            "rows": [
                {"id": "wiz_opt_svc_no",  "title": sel("no", svc)  + t("wizard.opt_svc_no", lang),  "description": t("wizard.opt_svc_no_desc", lang)},
                {"id": "wiz_opt_svc_yes", "title": sel("yes", svc) + t("wizard.opt_svc_yes", lang), "description": t("wizard.opt_svc_yes_desc", lang)},
            ],
        },
        {
            "title": t("wizard.opt_sec_continue", lang),
            "rows": [
                {"id": "wiz_options_confirm", "title": t("wizard.opt_confirm", lang), "description": t("wizard.opt_confirm_desc", lang)},
            ],
        },
    ]


# ── Session yönetimi ──────────────────────────────────────────────

async def cancel_wizard(sender: str, session: dict) -> None:
    """Wizard iptal edildi."""
    lang = session.get("lang", "tr")
    clear_wizard(session)
    from ..adapters.messenger import get_messenger
    await get_messenger().send_text(sender, t("wizard.cancelled", lang))


def clear_wizard(session: dict) -> None:
    """Wizard'a ait tüm session anahtarlarını temizle.

    SessionState.clear_wizard() metodu anahtar listesinin tek kaynağıdır (SOLID-v2-5).
    Bu fonksiyon geriye dönük uyumluluk için korunur — SessionState dışı dict'ler
    için fallback sağlar.
    """
    if hasattr(session, "clear_wizard"):
        session.clear_wizard()
    else:
        # Fallback: raw dict (test vb.)
        for key in (
            "wiz_name", "wiz_desc", "wiz_level", "wiz_mds", "wiz_path",
            "wiz_svc_decision", "wiz_services",
            "wiz_svc_name", "wiz_svc_cmd", "wiz_svc_port",
            "wiz_pending_level", "wiz_pending_mds", "wiz_pending_svc",
            "wiz_overwrite_confirmed",
            "awaiting_project_description",
            "awaiting_project_path",
            "awaiting_service_name", "awaiting_service_cmd",
            "awaiting_service_port", "awaiting_service_cwd",
            "pending_project_name", "pending_project_description",
            "pending_scaffold_source",
            # WIZ-LLM-3 — AI mimari önizlemesi
            "awaiting_arch_edit",
            "wiz_auto_arch",
            "wiz_ai_desc", "wiz_ai_arch", "wiz_ai_stack", "wiz_ai_dirs",
            "wiz_ai_prev_json",
        ):
            session.pop(key, None)
