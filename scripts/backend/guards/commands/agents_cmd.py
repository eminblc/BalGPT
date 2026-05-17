"""/agents komutu — aktif ve son agent run'larını WhatsApp'ta göster.

Alt komutlar:
  /agents           — aktif run'lar + son 5 tamamlanan
  /agents active    — sadece aktif (pending + running) run'lar
  /agents history   — son 20 run
  /agents cancel <run_id> — run'ı iptal et
"""
from __future__ import annotations

import logging
import time

from .registry import registry
from ..permission import Perm

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = frozenset({"pending", "running"})
_STATUS_ICON = {
    "pending":   "⏳",
    "running":   "▶️",
    "completed": "✅",
    "failed":    "❌",
    "cancelled": "🛑",
}


def _short_id(run_id: str) -> str:
    """UUID'nin ilk 6 karakterini döndür."""
    return run_id[:6]


def _elapsed(ts: float | None) -> str:
    """Unix timestamp'ten 'X dk Y sn' formatında geçen süre döndür."""
    if ts is None:
        return "?"
    secs = int(time.time() - ts)
    if secs < 60:
        return f"{secs}sn"
    mins, secs = divmod(secs, 60)
    return f"{mins}dk {secs}sn"


def _duration(ms: int | None) -> str:
    """Milisaniyeden 'X dk Y sn' formatında süre string'i üret."""
    if ms is None:
        return "?"
    secs = ms // 1000
    if secs < 60:
        return f"{secs}sn"
    mins, secs = divmod(secs, 60)
    return f"{mins}dk {secs}sn"


def _format_active_run(run: dict, lang: str) -> str:
    """Tek bir aktif run için çoklu-satır metin oluştur."""
    icon = _STATUS_ICON.get(run.get("status", ""), "▶️")
    rid = _short_id(run.get("id", "??????"))
    agent_type = run.get("agent_type", "unknown")

    project_id = run.get("project_id")
    session_id = run.get("session_id", "?")

    detail_parts: list[str] = []
    if project_id:
        detail_parts.append(f"Proje: {project_id}" if lang == "tr" else f"Project: {project_id}")
    else:
        detail_parts.append(f"Session: {session_id}")

    started_at = run.get("started_at") or run.get("created_at")
    if started_at:
        detail_parts.append(
            f"Başladı: {_elapsed(started_at)}" if lang == "tr"
            else f"Started: {_elapsed(started_at)} ago"
        )

    detail_line = " | ".join(detail_parts)
    return f"{icon} #{rid} — {agent_type}\n   {detail_line}"


def _format_completed_run(run: dict, lang: str) -> str:
    """Tamamlanmış/başarısız/iptal run için tek satır özet."""
    status = run.get("status", "completed")
    icon = _STATUS_ICON.get(status, "✅")
    rid = _short_id(run.get("id", "??????"))
    agent_type = run.get("agent_type", "unknown")
    dur = _duration(run.get("duration_ms"))

    if status == "failed":
        err = run.get("error_msg") or "?"
        max_err = 50
        if len(err) > max_err:
            err = err[:max_err] + "…"
        suffix = f"BAŞARISIZ: {err}" if lang == "tr" else f"FAILED: {err}"
        return f"{icon} #{rid} — {suffix}"

    return f"{icon} #{rid} — {dur} ({agent_type})"


def _build_active_section(runs: list[dict], lang: str) -> list[str]:
    """Aktif run'lar bölümünü satır listesi olarak döndür."""
    lines: list[str] = []
    if not runs:
        lines.append("  " + ("Aktif agent yok." if lang == "tr" else "No active agents."))
        return lines
    for run in runs:
        lines.append(_format_active_run(run, lang))
    return lines


class AgentsCommand:
    """Agent run'larını listele ve yönet (/agents komutu)."""

    cmd_id      = "/agents"
    perm        = Perm.OWNER
    label       = "Agent Run'lar"
    description = "Aktif ve son agent run'larını gösterir. Alt komutlar: active, history, cancel <id>."
    usage       = "/agents [active|history|cancel <run_id>]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t
        from ...store.repositories import agent_run_repo

        lang      = session.get("lang", "tr")
        messenger = get_messenger()
        sub       = arg.strip().lower()

        # ── /agents cancel <run_id> ───────────────────────────────────
        if sub.startswith("cancel "):
            run_id_prefix = sub.removeprefix("cancel ").strip()
            await self._handle_cancel(sender, run_id_prefix, agent_run_repo, messenger, lang)
            return

        # ── /agents active ────────────────────────────────────────────
        if sub == "active":
            active_runs = await agent_run_repo.agent_run_list_active()
            header = t("agents.active_header", lang, count=len(active_runs))
            lines = [header, ""]
            lines.extend(_build_active_section(active_runs, lang))
            await messenger.send_text(sender, "\n".join(lines))
            return

        # ── /agents history ───────────────────────────────────────────
        if sub == "history":
            runs = await agent_run_repo.agent_run_list(limit=20)
            if not runs:
                await messenger.send_text(sender, t("agents.empty", lang))
                return
            header = t("agents.history_header", lang, count=len(runs))
            lines = [header, ""]
            for run in runs:
                lines.append(_format_completed_run(run, lang))
            await messenger.send_text(sender, "\n".join(lines))
            return

        # ── /agents (default: aktif + son 5) ─────────────────────────
        active_runs   = await agent_run_repo.agent_run_list_active()
        recent_runs   = await agent_run_repo.agent_run_list(limit=5)

        # Son 5'ten aktif olanları çıkar (aktif bölümde gösterileceği için)
        active_ids    = {r["id"] for r in active_runs}
        completed_runs = [r for r in recent_runs if r["id"] not in active_ids]

        lines: list[str] = [
            t("agents.active_header", lang, count=len(active_runs)),
            "",
        ]
        lines.extend(_build_active_section(active_runs, lang))

        if completed_runs:
            lines.append("")
            lines.append(t("agents.recent_header", lang))
            for run in completed_runs:
                lines.append(_format_completed_run(run, lang))

        await messenger.send_text(sender, "\n".join(lines))

    # ── private helpers ───────────────────────────────────────────────

    async def _handle_cancel(
        self,
        sender: str,
        run_id_prefix: str,
        agent_run_repo,  # type: ignore[annotation-unchecked]
        messenger,       # type: ignore[annotation-unchecked]
        lang: str,
    ) -> None:
        """Prefix ile eşleşen run'ı iptal et."""
        from ...i18n import t

        if not run_id_prefix:
            await messenger.send_text(sender, t("agents.cancel_usage", lang))
            return

        # Önce tam ID ile dene; bulamazsa aktif run'lar içinde prefix eşleşmesi ara
        run = await agent_run_repo.agent_run_get(run_id_prefix)
        if run is None:
            # Prefix ile aktif run ara
            active_runs = await agent_run_repo.agent_run_list_active()
            matches = [r for r in active_runs if r["id"].startswith(run_id_prefix)]
            if len(matches) == 1:
                run = matches[0]
            elif len(matches) > 1:
                await messenger.send_text(sender, t("agents.cancel_ambiguous", lang, prefix=run_id_prefix))
                return
            else:
                await messenger.send_text(sender, t("agents.cancel_not_found", lang, run_id=run_id_prefix))
                return

        run_id = run["id"]
        status = run.get("status", "")
        if status not in _ACTIVE_STATUSES:
            await messenger.send_text(
                sender,
                t("agents.cancel_not_active", lang, run_id=_short_id(run_id), status=status),
            )
            return

        await agent_run_repo.agent_run_cancel(run_id)
        logger.info("AgentsCommand: run %s iptal edildi.", run_id)
        await messenger.send_text(sender, t("agents.cancel_ok", lang, run_id=_short_id(run_id)))


registry.register(AgentsCommand())
