"""CLI (stdout) messenger adaptörü — yerel geliştirme ve test için (DIST-4).

MESSENGER_TYPE=cli olarak ayarlandığında tüm mesajlar terminale yazdırılır;
WhatsApp veya Telegram bağlantısı gerektirmez.
"""
from __future__ import annotations


class CLIMessenger:
    """Mesajları stdout'a yazdıran debug/test messenger."""

    supports_interactive_buttons: bool = True  # Stdout'a simüle edilmiş buton çıktısı
    supports_media: bool = True

    async def send_text(self, to: str, text: str) -> None:
        print(f"[TO:{to}] {text}")

    async def send_buttons(self, to: str, text: str, buttons: list[dict]) -> None:
        btn_labels = " | ".join(f"[{b.get('title', b.get('id', '?'))}]" for b in buttons)
        print(f"[TO:{to}] {text}\n  Butonlar: {btn_labels}")

    async def send_list(self, to: str, text: str, sections: list[dict]) -> None:
        print(f"[TO:{to}] {text}")
        for section in sections:
            print(f"  [{section.get('title', '')}]")
            for row in section.get("rows", []):
                desc = f" — {row['description']}" if row.get("description") else ""
                print(f"    • {row.get('title', row.get('id', '?'))}{desc}")

    async def send_typing(self, to: str) -> None:
        print(f"[CLIMessenger] typing → to={to}")

    async def send_image(self, to: str, source: str, caption: str = "") -> None:
        print(f"[CLIMessenger] send_image → to={to} source={source} caption={caption!r}")

    async def send_video(self, to: str, source: str, caption: str = "") -> None:
        print(f"[CLIMessenger] send_video → to={to} source={source} caption={caption!r}")

    async def send_document(self, to: str, source: str, filename: str, caption: str = "") -> None:
        print(f"[CLIMessenger] send_document → to={to} source={source} filename={filename!r} caption={caption!r}")
