"""Mesaj guard implementasyonları — WhatsApp ve Telegram router'larının ortak kullandığı.

Her sınıf bağımsız bir güvenlik katmanıdır; GuardChain tarafından zincirlenir.
Yeni guard tipi = bu dosyaya yeni sınıf + GuardChain kaydı. Router'a dokunulmaz.

DIP-V1: Messenger bağımlılığı constructor'da inject edilir — fonksiyon-içi geç import yok.
"""
from __future__ import annotations

import logging
from typing import Callable

from .guard_chain import GuardContext, GuardResult
from ..store.message_logger import log_outbound, _mask_phone
from ..i18n import t

logger = logging.getLogger(__name__)


class DedupMessageGuard:
    """Yinelenen mesajları (Meta yeniden gönderimi vb.) sessizce atar."""

    def __init__(self, dedup) -> None:
        self._dedup = dedup

    async def check(self, ctx: GuardContext) -> GuardResult:
        if self._dedup.is_duplicate(ctx.msg_id):
            logger.debug("Duplicate mesaj atlandı: %s", ctx.msg_id)
            return GuardResult(passed=False, reason="duplicate")
        return GuardResult(passed=True)


class BlacklistMessageGuard:
    """Engellenen gönderenlerden gelen mesajları reddeder."""

    def __init__(self, blacklist_mgr) -> None:
        self._mgr = blacklist_mgr

    async def check(self, ctx: GuardContext) -> GuardResult:
        if self._mgr.is_blocked(ctx.sender):
            logger.info("Engelli sender: %s", _mask_phone(ctx.sender))
            return GuardResult(passed=False, reason="blacklisted")
        return GuardResult(passed=True)


_UNSET = object()  # notification_target sentinel: "not provided, use default"


class OwnerPermissionGuard:
    """Yalnızca owner'a izin verir; yetkisiz erişim teşebbüsünü owner'a bildirir.

    Bildirim kasıtlıdır: tek kullanıcılı sistemde yetkisiz numara mesaj atarsa
    owner'a haber verilmesi güvenlik izleme gereksinimi olarak tasarlanmıştır.

    messenger_factory: Messenger singleton'ını döndüren callable (DIP-V1: constructor'da inject).
    notification_target: Yetkisiz erişim bildirimi gönderilecek hedef.
        - Verilmezse (default): settings.whatsapp_owner kullanılır (WhatsApp router için).
        - Açıkça verilirse (ör. settings.telegram_chat_id): o değer kullanılır;
          None ise bildirim gönderilmez (Telegram'da chat_id tanımlı değilse).
    """

    def __init__(self, perm_mgr, settings, messenger_factory: Callable, notification_target=_UNSET) -> None:
        self._perm                = perm_mgr
        self._settings            = settings
        self._get_messenger       = messenger_factory
        self._notification_target = notification_target

    async def check(self, ctx: GuardContext) -> GuardResult:
        if self._perm.is_owner(ctx.sender):
            return GuardResult(passed=True)

        logger.warning("Yetkisiz sender: %s", _mask_phone(ctx.sender))
        target = (
            self._settings.owner_id
            if self._notification_target is _UNSET
            else self._notification_target
        )
        if target:
            try:
                preview = ""
                if ctx.msg.get("text"):
                    preview = ctx.msg["text"].get("body", "")[:100]
                elif ctx.msg.get("type"):
                    preview = f"[{ctx.msg['type']}]"
                await self._get_messenger().send_text(
                    target,
                    t("guard.unauthorized", "tr", sender=ctx.sender, preview=preview),
                )
            except Exception:
                pass
        return GuardResult(passed=False, reason="unauthorized")


class RateLimitMessageGuard:
    """Gönderen başına istek hızını sınırlar; aşılırsa kullanıcıya bildirir."""

    def __init__(self, rate_limiter, messenger_factory: Callable) -> None:
        self._limiter       = rate_limiter
        self._get_messenger = messenger_factory

    async def check(self, ctx: GuardContext) -> GuardResult:
        if self._limiter.check(ctx.sender):
            return GuardResult(passed=True)
        try:
            await self._get_messenger().send_text(ctx.sender, t("guard.rate_limit", ctx.lang))
            log_outbound(ctx.sender, "text", "rate_limit", context_id="system")
        except Exception:
            pass
        return GuardResult(passed=False, reason="rate_limited")
