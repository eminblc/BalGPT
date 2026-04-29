"""Desktop endpoint için TOTP kapısı (oturum bazlı unlock).

İlk çağrıda owner TOTP doğrulaması gerekir; başarılı doğrulamadan sonra
`desktop_totp_ttl_seconds` (varsayılan 900 sn) boyunca sonraki çağrılar
TOTP istemeden geçer.

Brute-force koruması: 3 başarısız deneme → 15 dk kilit.
Kilit "internal_desktop" sender key'i ile `totp_lockouts` tablosuna yazılır;
WhatsApp TOTP kilidinden bağımsızdır.

OOP-DIP: Tüm mutable state (unlock zamanı, TOTP istek bayrağı) DesktopTotpGate
sınıfında kapsüllenmiştir. Modül düzeyinde global değişken mutasyonu yoktur.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from ..config import settings
from ..guards import get_perm_mgr

logger = logging.getLogger(__name__)

_SENDER = "internal_desktop"  # TOTP lockout scope — diğer TOTP kanallarından bağımsız


class DesktopTotpGate:
    """Desktop endpoint erişimi için admin TOTP gate (oturum bazlı unlock).

    SRP: yalnızca unlock durumunu ve TOTP doğrulama akışını yönetir.
    OOP: Tüm mutable state (unlock zamanı, TOTP istek bayrağı) instance
         değişkenlerindedir; modül düzeyinde global mutasyon yoktur.
    DIP: TTL constructor üzerinden enjekte edilir; `settings` doğrudan okunmaz.
    """

    def __init__(self, ttl_seconds: float) -> None:
        self._ttl: float = float(ttl_seconds)
        self._unlock_until: float = 0.0
        # Duplicate WA mesajı göndermeyi önler: True iken kilitliyse yeni çağrı
        # ikinci mesaj göndermez. Başarılı unlock / iptal sonrası sıfırlanır.
        self._totp_request_sent: bool = False

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    def is_unlocked(self, *, now: Optional[float] = None) -> bool:
        if now is None:
            now = time.time()
        return now < self._unlock_until

    def remaining_seconds(self, *, now: Optional[float] = None) -> int:
        if now is None:
            now = time.time()
        return max(0, int(self._unlock_until - now))

    def reset(self) -> None:
        """Test veya elle kilitleme için unlock durumunu sıfırlar."""
        self._unlock_until = 0.0

    def clear_totp_request_sent(self) -> None:
        """TOTP başarılı / iptal / lockout sonrası istek bayrağını sıfırla."""
        self._totp_request_sent = False

    async def try_unlock(self, code: str) -> tuple[bool, Optional[int]]:
        """
        Admin TOTP kodunu doğrular ve başarılıysa unlock penceresini açar.

        Dönüş:
            (True, None)                       → doğrulama başarılı, TTL boyunca unlock
            (False, lockout_remaining_seconds) → brute-force kilidi aktif veya tetiklendi
            (False, None)                      → geçersiz kod, henüz kilit yok
        """
        from ..store.sqlite_store import (
            totp_get_lockout,
            totp_record_failure,
            totp_reset_lockout,
        )

        now = time.time()
        _, lockout_until = await totp_get_lockout(_SENDER, "owner")
        if lockout_until and now < lockout_until:
            remaining = int(lockout_until - now)
            logger.warning(
                "desktop_totp_gate: kilit aktif, %d sn kaldı", remaining,
            )
            return False, remaining

        if not code:
            return False, None

        valid = get_perm_mgr().verify_totp(code)
        if valid:
            await totp_reset_lockout(_SENDER, "owner")
            self._unlock_until = now + self._ttl
            self._totp_request_sent = False  # başarılı unlock → bayrağı sıfırla
            logger.info(
                "desktop_totp_gate: unlock başarılı TTL=%d sn", int(self._ttl),
            )
            return True, None

        fail_count, new_lockout = await totp_record_failure(_SENDER, "owner")
        if new_lockout:
            remaining = int(new_lockout - now)
            logger.warning(
                "desktop_totp_gate: brute-force kilidi uygulandı "
                "fail_count=%d remaining=%d",
                fail_count, remaining,
            )
            return False, remaining

        logger.warning(
            "desktop_totp_gate: başarısız TOTP denemesi fail_count=%d",
            fail_count,
        )
        return False, None

    async def request_totp(self, owner_id: str) -> None:
        """Gate kilitliyse owner'a TOTP isteği gönderir ve session state'i ayarlar.

        DESK-TOTP-2: Bu metod LLM'den değil, sunucu tarafından çağrılır.
        Duplicate mesaj göndermez (_totp_request_sent bayrağı ile korunur).
        """
        if self.is_unlocked() or self._totp_request_sent:
            if self.is_unlocked():
                return
            logger.debug("desktop_totp_gate: TOTP isteği zaten gönderildi, atlanıyor")
            return

        from ..guards import get_session_mgr
        from ..adapters.messenger.messenger_factory import get_messenger

        session = get_session_mgr().get(owner_id)
        session.start_desktop_totp()

        ttl_min = int(self._ttl) // 60
        await get_messenger().send_text(
            owner_id,
            (
                "🔒 Desktop işlemi için TOTP gerekli.\n"
                f"Başarılı girişten sonra {ttl_min} dk geçerli olacak.\n"
                "(/cancel ile iptal)"
            ),
        )
        self._totp_request_sent = True
        logger.info(
            "desktop_totp_gate: TOTP isteği gönderildi owner=%s ttl_min=%d",
            owner_id[-4:],
            ttl_min,
        )

    async def enforce(self, code: Optional[str]) -> Optional[dict]:
        """Endpoint başında çağrılır. Gate açıksa None döner (serbest geçiş).

        Kapalıysa `code` ile unlock dener; başarısızsa hata dict'i döner.

        Dönüş:
            None → işleme devam et
            dict → hata yanıtı (endpoint bu dict'i döndürmeli)
        """
        if self.is_unlocked():
            return None

        if not code:
            return {
                "ok": False,
                "requires_totp": True,
                "message": (
                    "🔒 Admin TOTP gerekli. İsteğin gövdesine "
                    "\"code\": \"<6 haneli kod>\" alanını ekleyerek tekrar gönder. "
                    f"Başarılı doğrulama sonrası {int(self._ttl)} sn boyunca "
                    "yeniden sorulmaz."
                ),
            }

        valid, lockout_remaining = await self.try_unlock(code)
        if valid:
            return None

        if lockout_remaining is not None:
            mins = max(1, lockout_remaining // 60)
            return {
                "ok": False,
                "requires_totp": True,
                "message": (
                    f"❌ TOTP kilidi aktif — yaklaşık {mins} dk sonra tekrar dene."
                ),
            }

        return {
            "ok": False,
            "requires_totp": True,
            "message": "❌ Geçersiz TOTP kodu. Tekrar dene.",
        }


# ── Modül singleton — settings import zamanında hazır; lazy init / global mutasyon yok ──
_gate = DesktopTotpGate(ttl_seconds=settings.desktop_totp_ttl_seconds)


def get_desktop_totp_gate() -> DesktopTotpGate:
    """Process-wide DesktopTotpGate singleton'u döner."""
    return _gate


# ── Backward-compat shim'ler — çağrı noktaları (_auth_flows, cancel_cmd) değişmez ──

def clear_totp_request_sent() -> None:
    """TOTP başarılı / iptal / lockout sonrası istek bayrağını sıfırla."""
    _gate.clear_totp_request_sent()


async def request_desktop_totp(owner_id: str) -> None:
    """Gate kilitliyse owner'a TOTP isteği gönderir (backward-compat shim)."""
    await _gate.request_totp(owner_id)


async def enforce_totp(code: Optional[str]) -> Optional[dict]:
    """Endpoint başında çağrılır; gate kontrolü yapar (backward-compat shim)."""
    return await _gate.enforce(code)
