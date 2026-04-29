"""/help komutu — ana menü + bireysel komut açıklamaları.

/help            → butonlar + tam komut listesi
/help /shutdown  → yalnızca o komutun açıklaması
"""
from __future__ import annotations

from .registry import registry
from ..permission import Perm


class HelpCommand:
    cmd_id      = "/help"
    perm        = Perm.OWNER
    label       = "Yardım Menüsü"
    description = "Tüm komutları listeler. Komut adı verince o komutun açıklamasını gösterir."
    usage       = "/help [/komut]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        lang      = session.get("lang", "tr")
        target    = arg.strip()
        messenger = get_messenger()

        # ── Bireysel komut yardımı: /help /shutdown ──────────────────
        if target.startswith("/"):
            await self._send_single_help(sender, target, lang, messenger.send_text)
            return

        # ── Tam menü ─────────────────────────────────────────────────
        await self._send_quick_buttons(sender, lang, messenger.send_buttons)
        model_hint = _build_model_hint(lang)
        await self._send_full_list(sender, lang, messenger.send_list, messenger.send_text, model_hint)

    # ── Yardımcı metodlar ─────────────────────────────────────────

    @staticmethod
    async def _send_single_help(sender: str, cmd_id: str, lang: str, send_text) -> None:
        """Tek bir komutun detaylı açıklamasını gönderir."""
        from ...i18n import t
        info = registry.describe(cmd_id)
        if info is None:
            await send_text(sender, t("help.unknown_cmd", lang, cmd=cmd_id))
            return

        lines = [
            f"*{info['label']}*",
            f"`{info['usage']}`",
            "",
            info["description"],
        ]
        await send_text(sender, "\n".join(lines))

    @staticmethod
    async def _send_quick_buttons(sender: str, lang: str, send_buttons) -> None:
        from ...i18n import t
        try:
            await send_buttons(
                sender,
                t("help.menu_title", lang),
                [
                    {"id": "menu_chat",     "title": t("help.btn_chat",     lang)},
                    {"id": "menu_plans",    "title": t("help.btn_plans",    lang)},
                    {"id": "menu_projects", "title": t("help.btn_projects", lang)},
                ],
            )
        except Exception:
            pass

    @staticmethod
    async def _send_full_list(sender: str, lang: str, send_list, send_text, model_hint: str = "") -> None:
        from ...i18n import t
        try:
            await send_list(
                sender,
                t("help.list_header", lang),
                [
                    {
                        "title": t("help.section_planning", lang),
                        "rows": [
                            {"id": "menu_plans",    "title": t("help.row_plans",       lang)},
                            {"id": "menu_calendar", "title": t("help.row_calendar",    lang)},
                            {"id": "menu_projects", "title": t("help.row_projects",    lang)},
                            {"id": "project_new",   "title": t("help.row_new_project", lang)},
                        ],
                    },
                    {
                        "title": t("help.section_system", lang),
                        "rows": [
                            {"id": "menu_history",      "title": t("help.row_history",       lang)},
                            {"id": "cmd_schedule_list", "title": t("help.row_schedule",      lang)},
                            {"id": "cmd_root_reset",    "title": t("help.row_session_reset", lang)},
                            {"id": "cmd_shutdown",      "title": t("help.row_shutdown",      lang)},
                            {"id": "cmd_lang",          "title": t("help.row_lang",          lang)},
                            {"id": "cmd_model",         "title": t("help.row_model",         lang)},
                            {"id": "cmd_tokens",        "title": t("help.row_tokens",        lang)},
                        ],
                    },
                ],
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error("send_list hatası: %s", e)
            await _send_fallback(sender, lang, send_text, model_hint)


def _build_model_hint(lang: str = "tr") -> str:
    """Backend'e özgü /model kullanım ipucu döndürür."""
    from ...config import settings
    from ...guards.runtime_state import get_active_model
    from ...i18n import t
    backend = settings.llm_backend.lower()
    current = get_active_model() or settings.default_model
    if backend == "anthropic":
        return t("help.model_hint_anthropic", lang, current=current)
    if backend == "ollama":
        return t("help.model_hint_ollama", lang, current=current)
    if backend == "gemini":
        return t("help.model_hint_gemini", lang, current=current)
    return t("help.model_hint_default", lang, current=current)


async def _send_fallback(sender: str, lang: str, send_text, model_hint: str = "") -> None:
    """Buton desteklemeyen istemci için düz metin."""
    from ...i18n import t
    await send_text(sender, t("help.fallback", lang, model_hint=model_hint))


registry.register(HelpCommand())
