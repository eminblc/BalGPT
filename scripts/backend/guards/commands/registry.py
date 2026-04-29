"""Command Protocol ve registry — OCP garantisi.

Yeni komut = yeni dosya + register(). Bu dosyaya dokunulmaz.

Her Command class'ı isteğe bağlı olarak şu class attribute'ları tanımlayabilir:
  label:       str  — İnsan okunabilir kısa ad  (ör. "Yeniden Başlat")
  description: str  — /help menüsünde görünen açıklama satırı
  usage:       str  — Kullanım örneği  (ör. "/restart")
"""
from __future__ import annotations

import logging
from typing import Protocol, runtime_checkable

from ..permission import Perm

logger = logging.getLogger(__name__)


@runtime_checkable
class Command(Protocol):
    cmd_id: str
    perm:   Perm   # ISP-2: protocol'de tanımlı — tip kontrol araçları eksik perm'i yakalar

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        """Komutu çalıştır. Yanıtı doğrudan WhatsApp'a gönderir."""
        ...


class CommandRegistry:
    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def register(self, cmd: Command) -> None:
        # REFAC-13: isinstance(cmd, Command) — @runtime_checkable Protocol cmd_id, perm, execute'ü kontrol eder.
        # hasattr(cmd, "perm") ile aynı işlevi görür; Command Protocol'ünün tamamını doğrular (LSP-1).
        if not isinstance(cmd, Command):
            cmd_id = getattr(cmd, "cmd_id", repr(cmd))
            raise TypeError(
                f"Komut {cmd_id!r} Command Protocol'ünü karşılamıyor. "
                "cmd_id (str), perm (Perm) ve async execute(sender, arg, session) zorunlu. "
                "Eksik 'perm' → yetki kontrolü bypass edilir (güvenlik riski)."
            )
        self._commands[cmd.cmd_id] = cmd
        logger.debug("Komut kaydedildi: %s", cmd.cmd_id)

    def get(self, cmd_id: str) -> Command | None:
        return self._commands.get(cmd_id)

    def all_ids(self) -> list[str]:
        return list(self._commands.keys())

    def visible_ids(self) -> list[str]:
        """hidden=True olan komutlar hariç tüm komut ID'lerini döndürür."""
        return [cid for cid, cmd in self._commands.items() if not getattr(cmd, "hidden", False)]

    def describe(self, cmd_id: str) -> dict[str, str] | None:
        """Komut için label/description/usage döndürür; kayıtlı değilse None."""
        cmd = self._commands.get(cmd_id)
        if cmd is None:
            return None
        return {
            "label":       getattr(cmd, "label",       cmd_id),
            "description": getattr(cmd, "description", ""),
            "usage":       getattr(cmd, "usage",       cmd_id),
            "hidden":      getattr(cmd, "hidden",      False),
        }


# Singleton instance — import this in command modules to register
registry = CommandRegistry()
