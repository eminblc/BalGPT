"""/timezone komutu — çalışma zamanında saat dilimini değiştir (FEAT-10).

Kullanım:
  /timezone                → mevcut saat dilimini göster
  /timezone Europe/London  → saat dilimini değiştir, APScheduler'ı yeniden yapılandır
"""
from .registry import registry
from ..permission import Perm


class TimezoneCommand:
    cmd_id      = "/timezone"
    perm        = Perm.OWNER
    label       = "Saat Dilimi"
    description = "Çalışma zamanında saat dilimini değiştirir (APScheduler dahil)."
    usage       = "/timezone [IANA/TZ]  — argümansız: mevcut ayarı göster"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t
        from ...config import settings

        lang = session.get("lang", "tr")
        tz_arg = arg.strip()

        if not tz_arg:
            # Mevcut timezone'u göster
            current = _get_current_tz()
            await get_messenger().send_text(sender, t("timezone.current", lang, tz=current))
            return

        # Geçerli IANA timezone mi?
        try:
            from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
            ZoneInfo(tz_arg)
        except Exception:
            await get_messenger().send_text(sender, t("timezone.invalid", lang, tz=tz_arg))
            return

        # Kaydet
        from ...store.repositories.settings_repo import user_setting_set
        await user_setting_set(sender, "timezone", tz_arg)

        # APScheduler'ı yeniden yapılandır
        from ...features.scheduler import apply_timezone
        await apply_timezone(tz_arg)

        await get_messenger().send_text(sender, t("timezone.changed", lang, tz=tz_arg))


def _get_current_tz() -> str:
    """Çalışma zamanındaki aktif timezone'u döndür."""
    from ...features.scheduler import get_current_timezone
    return get_current_timezone()


registry.register(TimezoneCommand())
