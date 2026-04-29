"""/lock komutu — uygulamayı TOTP doğrulamasıyla kilitler."""
from .registry import registry
from ..permission import Perm


class LockCommand:
    cmd_id      = "/lock"
    perm        = Perm.OWNER_TOTP
    label       = "Kilitle"
    description = "Uygulamayı kilitler. Kilitliyken yalnızca /unlock çalışır."
    usage       = "/lock"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...guards.runtime_state import set_locked
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        set_locked(True)
        lang = session.get("lang", "tr")
        await get_messenger().send_text(sender, t("lock.locked", lang))


registry.register(LockCommand())
