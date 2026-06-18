"""/dashboard komutu — aktif iş kaynaklarını tek ekranda gösterir.

Birleştirilen kaynaklar:
  • Scanner pipeline durumu  (GET /internal/scanner/status)
  • Backlog executor durumu  (GET /internal/backlog/status)
  • Aktif agent run'lar       (agent_run_repo.agent_run_list_active)
  • Zamanlanmış görevler      (features.scheduler.list_cron_jobs)
  • Aktif root project        (data/active_context.json)
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import httpx

from .registry import registry
from ..permission import Perm

log = logging.getLogger(__name__)

_CTX_FILE = Path(__file__).parent.parent.parent.parent.parent / "data" / "active_context.json"

_TIP_ICONS = {
    "run_bridge":            "💬",
    "send_message":          "📢",
    "run_scan":              "🔍",
    "run_scanner":           "🔍",
    "run_backlog_executor":  "🛠",
}


def _short_id(run_id: str, n: int = 6) -> str:
    return run_id[:n] if run_id else "??????"


def _elapsed(ts: float | None) -> str:
    if not ts:
        return "?"
    secs = int(time.time() - ts)
    if secs < 60:
        return f"{secs}sn"
    mins, secs = divmod(secs, 60)
    if mins < 60:
        return f"{mins}dk {secs}sn"
    hours, mins = divmod(mins, 60)
    return f"{hours}sa {mins}dk"


def _progress_bar(done: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "░" * width
    pct = min(100, int(done / total * 100))
    filled = pct // (100 // width)
    return "▓" * filled + "░" * (width - filled) + f" %{pct}"


def _active_root_project() -> dict | None:
    """Cascading lookup — _root_project_helpers ile tek doğruluk kaynağı."""
    from ._root_project_helpers import get_active_root_project
    return get_active_root_project()


async def _fetch_json(url: str, timeout: float = 3.0) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
    except Exception as exc:  # noqa: BLE001
        log.warning("dashboard_cmd: %s erişilemedi — %s", url, exc)
    return {}


class DashboardCommand:
    """Tüm aktif işleri tek mesajda gösterir."""

    cmd_id      = "/dashboard"
    perm        = Perm.OWNER
    button_id   = "cmd_dashboard"
    label       = "Dashboard"
    description = "Aktif scan/backlog/agent/scheduler durumlarını tek ekranda gösterir."
    usage       = "/dashboard"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger
        from ...i18n import t
        from ...store.repositories import agent_run_repo

        lang      = session.get("lang", "tr")
        messenger = get_messenger()

        scanner_data  = await _fetch_json("http://localhost:8010/internal/scanner/status")
        backlog_data  = await _fetch_json("http://localhost:8010/internal/backlog/status")
        active_runs   = await agent_run_repo.agent_run_list_active()
        root_project  = _active_root_project()

        lines: list[str] = [t("dashboard.header", lang)]

        # ── Aktif proje ─────────────────────────────────────────────
        if root_project:
            pid = root_project.get("name") or root_project.get("id", "?")
            lines.append("")
            lines.append(t("dashboard.active_project", lang, project=pid))
        else:
            lines.append("")
            lines.append(t("dashboard.no_active_project", lang))

        # ── Scanner ─────────────────────────────────────────────────
        lines.append("")
        lines.append(self._format_scanner(scanner_data, lang, t))

        # ── Backlog executor ────────────────────────────────────────
        lines.append("")
        lines.append(self._format_backlog(backlog_data, lang, t))

        # ── Aktif agent run'lar ─────────────────────────────────────
        lines.append("")
        lines.append(self._format_agents(active_runs, lang, t))

        # ── Scheduler (cron jobs) ───────────────────────────────────
        lines.append("")
        lines.append(self._format_scheduler(lang, t))

        # ── Footer ──────────────────────────────────────────────────
        lines.append("")
        lines.append(t("dashboard.footer", lang))

        await messenger.send_text(sender, "\n".join(lines))

    # ── Bölüm formatlayıcıları ────────────────────────────────────────

    @staticmethod
    def _format_scanner(data: dict, lang: str, t) -> str:
        is_running = bool(data.get("running_agent_run"))
        paused     = bool(data.get("pause_requested"))

        if not is_running and not paused:
            return t("dashboard.scanner_idle", lang)

        phase        = data.get("phase") or "scanner"
        stype        = data.get("scan_type") or "?"
        run_obj      = data.get("running_agent_run") or {}
        started_at   = run_obj.get("started_at") or data.get("started_at")
        run_id_short = _short_id(run_obj.get("id") or data.get("active_run_id") or "")

        # Faz farkı: scanner → chunk bazlı, reviewer → batch bazlı.
        # Reviewer fazında chunk progress'i zaten %100; alakalı metrik batch.
        if phase == "reviewer":
            total = int(data.get("total_batches", 0) or 0)
            done  = int(data.get("completed_batches", 0) or 0)
            unit_label = t("dashboard.scanner_batch_unit", lang)
        else:
            total = int(data.get("total_chunks", 0) or 0)
            done  = int(data.get("completed_chunks", data.get("findings_count", 0)) or 0)
            unit_label = t("dashboard.scanner_chunk_unit", lang)

        state_icon = "⏸" if paused else "▶️"
        head = t("dashboard.scanner_active", lang,
                 icon=state_icon, scan_type=stype, phase=phase)
        bar  = _progress_bar(done, total)
        elapsed = _elapsed(started_at)
        return (
            f"{head}\n"
            f"  [{bar}] {done}/{total} {unit_label}\n"
            f"  Run: `{run_id_short}` · {elapsed}"
        )

    @staticmethod
    def _format_backlog(data: dict, lang: str, t) -> str:
        status         = data.get("status", "")
        queued_pending = int(data.get("queued_pending", 0))

        if status != "running":
            base = t("dashboard.backlog_idle", lang)
            # Idle ama kuyrukta yine de bekleyenler olabilir (örn. run kilidini
            # alamamış başlayacak runlar) — bunları yine de göster.
            if queued_pending > 0:
                base += "\n  " + t("dashboard.backlog_queue", lang, n=queued_pending)
            return base

        pid        = data.get("project_id", "?")
        total      = data.get("total_items", 0)
        completed  = data.get("completed", 0)
        failed     = data.get("failed", 0)
        started_at = data.get("started_at")
        run_id     = _short_id(data.get("run_id") or "")

        bar = _progress_bar(completed, total)
        head = t("dashboard.backlog_active", lang, project=pid)
        lines = [
            head,
            f"  [{bar}] {completed}/{total} · ❌{failed}",
            f"  Run: `{run_id}` · {_elapsed(started_at)}",
        ]
        if queued_pending > 0:
            lines.append("  " + t("dashboard.backlog_queue", lang, n=queued_pending))
        return "\n".join(lines)

    @staticmethod
    def _format_agents(runs: list[dict], lang: str, t) -> str:
        if not runs:
            return t("dashboard.agents_empty", lang)

        head = t("dashboard.agents_header", lang, count=len(runs))
        rows: list[str] = [head]
        # En fazla 5 satır göster — daha uzun listede kullanıcı /agents'e gider
        for run in runs[:5]:
            rid    = _short_id(run.get("id", ""))
            atype  = run.get("agent_type", "?")
            pid    = run.get("project_id") or run.get("session_id", "?")
            ts     = run.get("started_at") or run.get("created_at")
            rows.append(f"  ▶️ #{rid} — {atype} · {pid} · {_elapsed(ts)}")
        if len(runs) > 5:
            rows.append(t("dashboard.agents_more", lang, count=len(runs) - 5))
        return "\n".join(rows)

    @staticmethod
    def _format_scheduler(lang: str, t) -> str:
        try:
            from ...features.scheduler import list_cron_jobs
            jobs = list_cron_jobs() or []
        except Exception as exc:  # noqa: BLE001
            log.warning("dashboard_cmd: scheduler erişilemedi — %s", exc)
            return t("dashboard.scheduler_unavailable", lang)

        active_jobs = [j for j in jobs if j.get("active")]
        if not jobs:
            return t("dashboard.scheduler_empty", lang)

        head = t("dashboard.scheduler_header", lang,
                 active=len(active_jobs), total=len(jobs))
        rows: list[str] = [head]
        # İlk 5 aktif job'u göster
        for j in active_jobs[:5]:
            icon  = "✅" if j.get("active") else "⏸"
            tip   = _TIP_ICONS.get(j.get("action_type", ""), "⚙️")
            short = _short_id(j.get("id", ""))
            cron  = j.get("cron_expr") or t("dashboard.one_time", lang)
            desc  = (j.get("description") or "").strip()
            if len(desc) > 40:
                desc = desc[:40] + "…"
            rows.append(f"  {icon} {tip} `{short}` [{cron}] — {desc}")
        if len(active_jobs) > 5:
            rows.append(t("dashboard.scheduler_more", lang, count=len(active_jobs) - 5))
        return "\n".join(rows)


registry.register(DashboardCommand())
