"""Zamanlama endpoint'leri — /schedule, /schedules (SRP)."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from ._deps import COMMON_DEPS
from ...config import settings

router = APIRouter(dependencies=COMMON_DEPS)

_SCHEDULER_DISABLED = HTTPException(
    status_code=503,
    detail="Scheduler devre dışı (RESTRICT_SCHEDULER=true)",
)


class ScheduleRequest(BaseModel):
    description: str
    action_type: str = "run_bridge"     # "run_bridge" | "send_message"
    message: str = ""                   # override; boşsa description kullanılır
    cron_expr: Optional[str] = None     # tekrarlayan: "0 9 * * *" (UTC)
    run_at: Optional[float] = None      # tek seferlik: unix timestamp (UTC)


@router.post("/schedule")
async def create_schedule(body: ScheduleRequest):
    """Cron veya tek seferlik job oluştur. cron_expr XOR run_at."""
    if not settings.scheduler_enabled:
        raise _SCHEDULER_DISABLED
    if body.cron_expr and body.run_at is not None:
        raise HTTPException(status_code=400, detail="cron_expr XOR run_at — ikisi birden kullanılamaz")
    if not body.cron_expr and body.run_at is None:
        raise HTTPException(status_code=400, detail="cron_expr veya run_at gerekli")

    if body.cron_expr:
        from ...features.scheduler import create_scheduled_task
        try:
            return await create_scheduled_task(
                description = body.description,
                cron_expr   = body.cron_expr,
                action_type = body.action_type,
                message     = body.message,
            )
        except ValueError as e:
            logger.error("create_scheduled_task ValueError: %s", e)
            raise HTTPException(status_code=400, detail="Geçersiz cron ifadesi")
    else:
        from ...features.scheduler import create_one_shot_task
        return await create_one_shot_task(
            description = body.description,
            message     = body.message,
            run_at      = body.run_at,
            action_type = body.action_type,
        )


@router.get("/schedules")
async def list_schedules():
    if not settings.scheduler_enabled:
        raise _SCHEDULER_DISABLED
    from ...features.scheduler import list_cron_jobs
    return list_cron_jobs()


@router.delete("/schedule/{task_id}")
async def delete_schedule(task_id: str):
    """Soft delete — job geçmişi korunur."""
    if not settings.scheduler_enabled:
        raise _SCHEDULER_DISABLED
    from ...features.scheduler import soft_delete_job
    await soft_delete_job(task_id)
    return {"status": "deleted"}


@router.post("/schedule/{task_id}/pause")
async def pause_schedule(task_id: str):
    if not settings.scheduler_enabled:
        raise _SCHEDULER_DISABLED
    from ...features.scheduler import pause_cron_job
    pause_cron_job(task_id)
    return {"status": "paused"}


@router.post("/schedule/{task_id}/resume")
async def resume_schedule(task_id: str):
    if not settings.scheduler_enabled:
        raise _SCHEDULER_DISABLED
    from ...features.scheduler import resume_cron_job
    resume_cron_job(task_id)
    return {"status": "resumed"}
