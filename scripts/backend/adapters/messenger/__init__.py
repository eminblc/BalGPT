"""Messenger adapter paketi — OCP uyumlu mesajlaşma soyutlaması.

Yeni platform = yeni dosya + factory kaydı. Mevcut koda dokunulmaz.

Kullanım:
    from backend.adapters.messenger import AbstractMessenger, get_messenger

    messenger = get_messenger()          # MESSENGER_TYPE env'e göre seçilir
    await messenger.send_text(to, text)

Protokol hiyerarşisi (ISP):
    AbstractMessenger  — yalnızca send_text; metin tabanlı minimal platformlar için
    InteractiveMessenger(AbstractMessenger) — send_buttons + send_list ekler
    MediaMessenger(AbstractMessenger) — send_image + send_video + send_document ekler

Kapasite kontrolü (LSP-2 / REFAC-12):
    @runtime_checkable Protocol sayesinde isinstance() ile güvenli kontrol yapılabilir;
    ad-hoc getattr kullanımından kaçın:

        if isinstance(messenger, InteractiveMessenger):
            await messenger.send_buttons(to, text, buttons)
        else:
            await messenger.send_text(to, text)

        if isinstance(messenger, MediaMessenger):
            await messenger.send_image(to, "/path/to/image.jpg")
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class AbstractMessenger(Protocol):
    """Temel mesajlaşma sözleşmesi — yalnızca metin gönderimi.

    Metin tabanlı minimal platformlar (SMS, e-posta vb.) bu protokolü uygular;
    send_buttons / send_list tanımlamak zorunda değildir.
    """

    async def send_text(self, to: str, text: str) -> None:
        """Kullanıcıya düz metin mesajı gönder."""
        ...


@runtime_checkable
class InteractiveMessenger(AbstractMessenger, Protocol):
    """Etkileşimli mesajlaşma sözleşmesi — buton ve liste desteği ekler.

    Tüm mevcut adaptörler (WhatsApp, Telegram, CLI) bu protokolü uygular.
    supports_interactive_buttons = True olan messengerlar bu protokolü karşılar.
    """

    supports_interactive_buttons: bool

    async def send_buttons(self, to: str, text: str, buttons: list[dict]) -> None:
        """Tıklanabilir butonlu mesaj gönder.

        buttons: [{"id": "btn_id", "title": "Başlık"}, ...]
        """
        ...

    async def send_list(self, to: str, text: str, sections: list[dict]) -> None:
        """Bölümlere ayrılmış liste/menü gönder.

        sections: [{"title": "Bölüm", "rows": [{"id": "...", "title": "...", "description": "..."}]}]
        Native liste desteği olmayan platformlar düz metin olarak gönderir.
        """
        ...


@runtime_checkable
class TypingMessenger(AbstractMessenger, Protocol):
    """Yazıyor… göstergesi desteği — platforma özgü typing action.

    Telegram: sendChatAction("typing")
    WhatsApp/CLI: no-op (native destek yok)
    """

    async def send_typing(self, to: str) -> None:
        """Kullanıcıya 'yazıyor…' göstergesi gönder (yaklaşık 5 sn aktif kalır)."""
        ...


@runtime_checkable
class MediaMessenger(AbstractMessenger, Protocol):
    """Medya gönderim sözleşmesi — görsel, video ve belge desteği ekler.

    source parametresi yerel dosya yolu (/data/media/...) veya https:// URL olabilir.
    supports_media = True olan messengerlar bu protokolü karşılar.
    """

    supports_media: bool

    async def send_image(self, to: str, source: str, caption: str = "") -> None:
        """Görsel gönder. source: yerel yol veya URL."""
        ...

    async def send_video(self, to: str, source: str, caption: str = "") -> None:
        """Video gönder. source: yerel yol (WhatsApp URL desteklemez)."""
        ...

    async def send_document(self, to: str, source: str, filename: str, caption: str = "") -> None:
        """Belge gönder. source: yerel yol veya URL."""
        ...


# Kolaylık re-export'ları — döngüsel import olmaması için concrete sınıflar
# Protocol tanımından sonra yüklenir (noqa: E402)
from .whatsapp_messenger import WhatsAppMessenger  # noqa: E402
from .telegram_messenger import TelegramMessenger  # noqa: E402
from .cli_messenger import CLIMessenger            # noqa: E402
from .messenger_factory import get_messenger, set_messenger, reset_messenger  # noqa: E402

__all__ = [
    "AbstractMessenger",
    "InteractiveMessenger",
    "TypingMessenger",
    "MediaMessenger",
    "WhatsAppMessenger",
    "TelegramMessenger",
    "CLIMessenger",
    "get_messenger",
    "set_messenger",
    "reset_messenger",
]
