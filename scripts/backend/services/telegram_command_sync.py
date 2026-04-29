"""Telegram bot komut menüsü senkronizasyonu — setMyCommands API entegrasyonu.

Sorumluluk (SRP):
  - Registry'deki tüm !komutları Telegram komut formatına dönüştür
  - setMyCommands API çağrısıyla bot menüsünü güncelle
  - tg_name → cmd_id haritası üret (router'ın ters çevirim için kullanır)

Her servis restart'ında çalışır → yeni komutlar otomatik menüye yansır.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import httpx

from ..config import settings
from ..guards.commands import registry

logger = logging.getLogger(__name__)

_MAX_CMD_LEN = 32
_MAX_DESC_LEN = 256
_MIN_DESC_LEN = 3


def _to_tg_name(cmd_id: str) -> str:
    """'/root-reset' → 'root_reset'"""
    return cmd_id.lstrip("/").replace("-", "_").lower()[:_MAX_CMD_LEN]


@lru_cache(maxsize=None)
def build_tg_command_map() -> dict[str, str]:
    """tg_name → cmd_id haritası döndürür. Router'ın ters çevirim için kullanır.

    Örnek: {'root_reset': '/root-reset', 'help': '/help', 'start': '/help'}
    İlk çağrıda hesaplanır, sonraki çağrılarda önbellekten döner (lru_cache).
    """
    result: dict[str, str] = {}
    for cmd_id in registry.all_ids():
        if not cmd_id.startswith("/"):
            continue
        tg_name = _to_tg_name(cmd_id)
        result[tg_name] = cmd_id
    result.setdefault("start", "/help")
    return result


class TelegramCommandSyncer:
    """Telegram setMyCommands API'sini çağırarak bot komut menüsünü günceller."""

    async def sync(self) -> None:
        token = settings.telegram_bot_token.get_secret_value()
        if not token:
            logger.warning("TELEGRAM_BOT_TOKEN tanımlı değil — komut menüsü senkronizasyonu atlandı")
            return

        commands = self._build_commands()
        if not commands:
            logger.warning("Registry'de Telegram için uygun komut bulunamadı")
            return

        await self._call_set_my_commands(token, commands)

    def _build_commands(self) -> list[dict]:
        commands = []
        for cmd_id in sorted(registry.all_ids()):
            if not cmd_id.startswith("/"):
                continue
            tg_name = _to_tg_name(cmd_id)
            desc = self._get_description(cmd_id)
            if not desc:
                continue
            commands.append({"command": tg_name, "description": desc})
        return commands

    def _get_description(self, cmd_id: str) -> str:
        info = registry.describe(cmd_id)
        if not info:
            return ""
        desc = (info.get("description") or info.get("label") or cmd_id).strip()
        desc = desc[:_MAX_DESC_LEN]
        if len(desc) < _MIN_DESC_LEN:
            desc = desc.ljust(_MIN_DESC_LEN)
        return desc

    async def _call_set_my_commands(self, token: str, commands: list[dict]) -> None:
        url = f"https://api.telegram.org/bot{token}/setMyCommands"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(url, json={"commands": commands})
            data = resp.json()
            if data.get("ok"):
                logger.info("Telegram komut menüsü güncellendi: %d komut", len(commands))
            else:
                logger.error("setMyCommands başarısız: %s", data)
        except Exception as exc:
            logger.error("setMyCommands çağrısı başarısız: %s", exc)
