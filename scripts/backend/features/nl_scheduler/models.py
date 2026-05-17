"""Doğal dil zamanlama çıkarımı için veri modelleri."""
from __future__ import annotations
from typing import TypedDict


class ScheduleParams(TypedDict, total=False):
    """LLM'den çıkarılan zamanlama parametreleri."""
    project_id:     str    # "petekv5"
    action_type:    str    # "run_scanner" | "run_backlog_executor"
    scan_type:      str    # "security" | "bugfix" (run_scanner için)
    prefix:         str    # "SEC" (run_backlog_executor için, boş = tümü)
    max_items:      int    # backlog executor için (default 3)
    auto_review:    bool   # scanner için otomatik review (default True)
    dry_run:        bool   # test modu (default False)
    cron_expr:      str    # "*/30 * * * *"
    human_readable: str    # "Her 30 dakikada bir"
    description:    str    # Scheduler'da gösterilecek açıklama


class PendingSchedule(TypedDict):
    """Session'da bekleyen onay için tutulan zamanlama."""
    params: ScheduleParams
    original_text: str
