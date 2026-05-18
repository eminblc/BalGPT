"""/history komutu — son mesajları ve session özetlerini göster."""
from __future__ import annotations

from .registry import Command, registry
from ..permission import Perm


class HistoryCommand:
    cmd_id      = "/history"
    perm        = Perm.OWNER
    label       = "Mesaj Geçmişi"
    description = "Son mesajları gösterir. Sayı verilebilir. 'özet' yazılırsa session özetleri çıkar."
    usage       = "/history [N|özet]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...features.history import (
            get_recent_messages,
            get_session_summaries,
            format_history,
            format_summaries,
        )
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        sub = arg.strip().lower()

        lang = session.get("lang", "tr")

        if not sub:
            messenger = get_messenger()
            buttons = [
                {"id": "history_5",       "title": t("history.btn_5",       lang)},
                {"id": "history_10",      "title": t("history.btn_10",      lang)},
                {"id": "history_20",      "title": t("history.btn_20",      lang)},
                {"id": "history_summary", "title": t("history.btn_summary", lang)},
            ]
            await messenger.send_buttons(sender, t("history.choose_prompt", lang), buttons)
            return

        if sub in ("ozet", "özet", "summary"):
            summaries = await get_session_summaries(sender, limit=5)
            await get_messenger().send_text(sender, format_summaries(summaries, lang=lang))
        else:
            limit = 15
            try:
                limit = int(sub) if sub else 15
            except ValueError:
                pass
            msgs = await get_recent_messages(sender, limit=limit)
            await get_messenger().send_text(sender, format_history(msgs, lang=lang))


registry.register(HistoryCommand())
