"""/unlock komutu — kilitli uygulamayı TOTP doğrulamasıyla açar."""
from .registry import registry
from ..permission import Perm


class UnlockCommand:
    cmd_id      = "/unlock"
    perm        = Perm.OWNER_TOTP
    label       = "Kilidi Aç"
    description = "Kilitli uygulamayı açar."
    usage       = "/unlock"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...guards.runtime_state import set_locked
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        set_locked(False)
        lang = session.get("lang", "tr")
        await get_messenger().send_text(sender, t("lock.unlocked", lang))


registry.register(UnlockCommand())
