"""/lang komutu — arayüz dilini değiştir (tr / en)."""
from .registry import registry
from ..permission import Perm


class LangCommand:
    cmd_id      = "/lang"
    perm        = Perm.OWNER
    label       = "Dil Değiştir"
    description = "Arayüz dilini değiştirir. Desteklenen: tr, en."
    usage       = "/lang <tr|en>"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        lang = arg.strip().lower()
        current = session.get("lang", "tr")

        if lang not in ("tr", "en"):
            await get_messenger().send_text(sender, t("lang.invalid", current))
            return

        session["lang"] = lang

        from ...store.repositories.settings_repo import user_setting_set
        await user_setting_set(sender, "lang", lang)

        await get_messenger().send_text(sender, t("lang.changed", lang, code=lang.upper()))


registry.register(LangCommand())
