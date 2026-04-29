"""Blacklist yönetimi — yasaklı numaraları saklar ve kontrol eder (SRP)."""
from __future__ import annotations

import json
import logging
from pathlib import Path


logger = logging.getLogger(__name__)

_BLACKLIST_FILE = Path(__file__).parent.parent.parent.parent / "data" / "blacklist.json"


class BlacklistManager:
    """Yasaklı numara listesi. JSON dosyasına kalıcı olarak yazar."""

    def __init__(self) -> None:
        self._blocked: set[str] = set()
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(_BLACKLIST_FILE.read_text(encoding="utf-8"))
            self._blocked = {e["number"] for e in data if isinstance(e, dict)}
        except FileNotFoundError:
            self._blocked = set()
        except json.JSONDecodeError as exc:
            logger.warning("Blacklist JSON bozuk, liste sıfırlandı: %s", exc)
            self._blocked = set()
        except Exception as exc:
            logger.warning("Blacklist yüklenemedi: %s", exc)
            self._blocked = set()

    def _save(self) -> None:
        entries = [{"number": n} for n in sorted(self._blocked)]
        _BLACKLIST_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")

    async def _save_async(self) -> None:
        """R7: async bağlamda event loop'u bloklamadan kaydet."""
        import asyncio
        await asyncio.to_thread(self._save)

    def is_blocked(self, number: str) -> bool:
        return number in self._blocked

    async def add(self, number: str, reason: str = "") -> None:
        self._blocked.add(number)
        await self._save_async()
        logger.warning("Blacklist'e eklendi: %s — %s", number, reason)

    def remove(self, number: str) -> None:
        self._blocked.discard(number)
        self._save()
