"""/root-log komutu — root_actions.log son 5 satırını insan okunur formatta göster."""
import json
from datetime import datetime, timezone
from pathlib import Path
from .registry import registry
from ..permission import Perm

_LOG_PATH = Path(__file__).parent.parent.parent.parent.parent / "outputs" / "logs" / "root_actions.log"


def _fmt_log_entry(line: str) -> str | None:
    """JSON log satırını insan okunur formata dönüştür."""
    try:
        obj = json.loads(line.strip())
        ts_str = obj.get("ts", "")
        tool = obj.get("tool", "Unknown")
        input_text = obj.get("input", "")
        output_text = obj.get("output", "")

        # UTC timestamp'i yerel saate dönüştür (UTC+3)
        try:
            dt_utc = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            dt_local = dt_utc.astimezone()
            time_str = dt_local.strftime("%H:%M:%S")
        except (ValueError, AttributeError):
            time_str = "??"

        # Input metnini kısalt (80 karaktere)
        input_preview = input_text[:80].replace("\n", " ")
        if len(input_text) > 80:
            input_preview += "…"

        # Output metnini kısalt (50 karaktere)
        output_preview = output_text[:50].replace("\n", " ")
        if len(output_text) > 50:
            output_preview += "…"

        return f"⏰ {time_str} | 🔧 {tool}\n  → {input_preview}\n  ← {output_preview}"
    except (json.JSONDecodeError, KeyError):
        return line.strip() or None


class RootLogCommand:
    cmd_id      = "/root-log"
    perm        = Perm.OWNER
    label       = "Root İşlem Geçmişi"
    description = "root_actions.log dosyasının son 5 işlemini insan okunur formatta gösterir."
    usage       = "/root-log"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        lang = session.get("lang", "tr")
        if not _LOG_PATH.exists():
            await get_messenger().send_text(sender, t("root_check.not_found", lang))
            return

        try:
            lines = _LOG_PATH.read_text(encoding="utf-8", errors="replace").splitlines()
            last = [l for l in lines if l.strip()][-5:]

            formatted = []
            for line in last:
                entry = _fmt_log_entry(line)
                if entry:
                    formatted.append(entry)

            if not formatted:
                await get_messenger().send_text(sender, t("root_check.error", lang, error="Log verisi parse edilemedi"))
                return

            msg = t("root_log.header", lang) + "\n\n".join(formatted)
            await get_messenger().send_text(sender, msg)
        except Exception as e:
            await get_messenger().send_text(sender, t("root_check.error", lang, error=e))


registry.register(RootLogCommand())
