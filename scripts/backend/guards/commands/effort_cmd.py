"""/effort komutu — Claude Code CLI reasoning effort seviyesini değiştir.

Desteklenen seviyeler (Claude Code CLI 2.1.101+):
    low | medium | high | max

Effort seviyesi **bağımsız bir ayar**: Extended Thinking on/off durumu
`/thinking` ile ayrı kontrol edilir. Thinking kapalıyken effort seçili olsa
bile gönderilmez (CLI/SDK varsayılan davranışı). Thinking açıkken seçili
effort budget_tokens'a (Anthropic SDK) veya `--effort` CLI flag'ine (Bridge)
çevrilir.

`/effort` (argümansız)  → butonlu seçim (Telegram/WhatsApp)
`/effort <level>`       → doğrudan ayarla

Effort seçimi global ve servis yeniden başlatılana kadar kalıcıdır
(user_settings tablosunda saklanır).
"""
from .registry import registry
from ..permission import Perm


_VALID_EFFORTS: tuple[str, ...] = ("low", "medium", "high", "max")


class EffortCommand:
    cmd_id      = "/effort"
    button_id   = "cmd_effort"
    perm        = Perm.OWNER
    label       = "Effort Seviyesi"
    description = "Claude Code CLI reasoning effort seviyesini değiştirir (low/medium/high/max). Global etki, restart'a kadar kalıcı."
    usage       = "/effort [low|medium|high|max]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...guards.runtime_state import get_active_effort, set_active_effort
        from ...i18n import t

        lang = session.get("lang", "tr")
        messenger = get_messenger()
        arg = arg.strip().lower()

        current = get_active_effort() or "default"

        # 4 seviye butonu — WhatsApp send_buttons max 3, bu yüzden send_list.
        # Aktif seviye "✓" ile işaretlenir.
        if not arg:
            rows = [
                {"id": "effort_select_low",    "title": t("effort.btn_low",    lang)},
                {"id": "effort_select_medium", "title": t("effort.btn_medium", lang)},
                {"id": "effort_select_high",   "title": t("effort.btn_high",   lang)},
                {"id": "effort_select_max",    "title": t("effort.btn_max",    lang)},
            ]
            current_key = current if current in _VALID_EFFORTS else None
            if current_key:
                for r in rows:
                    if r["id"].endswith(current_key):
                        r["title"] = r["title"] + " ✓"
            await messenger.send_list(
                sender,
                t("effort.select_prompt", lang, level=current),
                [{"title": t("effort.section_title", lang), "rows": rows}],
            )
            return

        if arg not in _VALID_EFFORTS:
            await messenger.send_text(sender, t("effort.invalid", lang, level=arg))
            return

        if arg == current:
            await messenger.send_text(sender, t("effort.already_active", lang, level=arg))
            return

        set_active_effort(arg)

        from ...store.repositories.settings_repo import user_setting_set
        await user_setting_set(sender, "effort", arg)

        await messenger.send_text(sender, t("effort.changed", lang, level=arg))


async def handle_effort_select(sender: str, level: str, session: dict) -> None:
    """Buton callback'i: effort_select_{level} → seviyeyi değiştir."""
    cmd = EffortCommand()
    await cmd.execute(sender, level, session)


registry.register(EffortCommand())
