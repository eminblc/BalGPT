"""/thinking komutu — Extended Thinking on/off toggle.

VS Code Claude Code eklentisindeki "Thinking" toggle'ının Telegram karşılığı.
Effort seviyesi (`/effort`) bağımsız bir ayar; thinking kapalıyken effort
seviyesi seçili olsa bile gönderilmez. Açıkken seçili effort budget_tokens'a
(Anthropic SDK) veya `--effort` CLI flag'ine (Bridge) çevrilir.

`/thinking`         → mevcut durumu gösterir + on/off butonları
`/thinking on`      → açar
`/thinking off`     → kapatır
`/thinking toggle`  → tersine çevirir
"""
from .registry import registry
from ..permission import Perm


_ON_ALIASES: frozenset[str] = frozenset({"on", "true", "1", "yes", "aç", "ac", "open"})
_OFF_ALIASES: frozenset[str] = frozenset({"off", "false", "0", "no", "kapat", "kapalı", "kapali", "close"})


class ThinkingCommand:
    cmd_id      = "/thinking"
    button_id   = "cmd_thinking"
    perm        = Perm.OWNER
    label       = "Extended Thinking"
    description = "Extended Thinking on/off toggle (effort seviyesinden bağımsız). Restart sonrası korunur."
    usage       = "/thinking [on|off|toggle]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...guards.runtime_state import get_active_thinking, set_active_thinking
        from ...i18n import t

        lang = session.get("lang", "tr")
        messenger = get_messenger()
        arg = arg.strip().lower()

        current = get_active_thinking()

        if not arg:
            # Mevcut durum + iki buton (on/off)
            on_mark  = " ✓" if current else ""
            off_mark = " ✓" if not current else ""
            await messenger.send_buttons(
                sender,
                t("thinking.select_prompt", lang, state=t("thinking.on" if current else "thinking.off", lang)),
                [
                    {"id": "thinking_on",  "title": t("thinking.btn_on",  lang) + on_mark},
                    {"id": "thinking_off", "title": t("thinking.btn_off", lang) + off_mark},
                ],
            )
            return

        if arg in {"toggle", "swap", "tersine", "çevir", "cevir"}:
            new_value = not current
        elif arg in _ON_ALIASES:
            new_value = True
        elif arg in _OFF_ALIASES:
            new_value = False
        else:
            await messenger.send_text(sender, t("thinking.invalid", lang, value=arg))
            return

        if new_value == current:
            key = "thinking.already_on" if current else "thinking.already_off"
            await messenger.send_text(sender, t(key, lang))
            return

        set_active_thinking(new_value)

        from ...store.repositories.settings_repo import user_setting_set
        await user_setting_set(sender, "thinking", "1" if new_value else "0")

        key = "thinking.turned_on" if new_value else "thinking.turned_off"
        await messenger.send_text(sender, t(key, lang))


async def handle_thinking_button(sender: str, suffix: str, session: dict) -> None:
    """Buton callback'i: thinking_on / thinking_off → komuta yönlendir."""
    cmd = ThinkingCommand()
    await cmd.execute(sender, suffix, session)


registry.register(ThinkingCommand())
