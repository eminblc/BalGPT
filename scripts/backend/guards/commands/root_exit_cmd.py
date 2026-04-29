"""/root-exit komutu — root proje bağlamından çık, 99-root dizinine dön."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .registry import registry
from ..permission import Perm
from ...app_types import ACTIVE_CONTEXT_PATH as _ACTIVE_CONTEXT_PATH  # REFAC-18

logger = logging.getLogger(__name__)


class RootExitCommand:
    cmd_id      = "/root-exit"
    perm        = Perm.OWNER
    label       = "Root'tan Çık"
    description = "Root proje bağlamından çıkar; ana ajan 99-root diziniyle devam eder."
    usage       = "/root-exit"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...features.chat import reset_bridge_session

        from ...i18n import t
        lang = session.get("lang", "tr")
        try:
            ctx = json.loads(_ACTIVE_CONTEXT_PATH.read_text(encoding="utf-8")) if _ACTIVE_CONTEXT_PATH.exists() else {}
            rp = ctx.get("active_root_project")
            if not rp:
                await get_messenger().send_text(sender, t("root_exit.not_set", lang))
                return
            project_name = rp.get("name", "?")
            ctx.pop("active_root_project", None)
            ctx["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            _ACTIVE_CONTEXT_PATH.write_text(json.dumps(ctx, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.error("active_context.json güncellenemedi: %s", exc)
            await get_messenger().send_text(sender, t("root_exit.error", lang, error=exc))
            return

        await reset_bridge_session("main")
        await get_messenger().send_text(sender, t("root_exit.ok", lang, name=project_name))


registry.register(RootExitCommand())
