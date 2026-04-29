"""Zamanlama endpoint'leri — yalnızca localhost erişimine açık (SRP).

Bridge'deki Claude bu router'ı kullanarak cron job ve tek seferlik görev oluşturur.
API key gerekmez; yalnızca 127.0.0.1 / ::1 erişebilir.

internal_router.py'den ayrıldı: SRP — zamanlama sorumluluğu tek modülde (SOLID-SRP-1).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from ._localhost_guard import is_localhost

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal")


class _ScheduleRequest(BaseModel):
    description: str
    action_type: str = "send_message"   # "send_message" | "run_bridge"
    message: str = ""
    cron_expr: Optional[str] = None     # tekrarlayan: "0 9 * * *" (TR saati)
    run_at: Optional[float] = None      # tek seferlik: unix timestamp (UTC)


def _require_localhost(request: Request) -> None:
    if not is_localhost(request):
        host = request.client.host if request.client else "?"
        logger.warning("_schedule_router: localhost dışı erişim engellendi host=%s", host)
        raise HTTPException(status_code=403, detail="Localhost only")


def _validate_schedule_body(body: _ScheduleRequest) -> None:
    """cron_expr XOR run_at zorunluluğunu doğrular."""
    if body.cron_expr and body.run_at is not None:
        raise HTTPException(
            status_code=400,
            detail="cron_expr XOR run_at — ikisi birden kullanılamaz",
        )
    if not body.cron_expr and body.run_at is None:
        raise HTTPException(
            status_code=400,
            detail="cron_expr veya run_at gerekli",
        )


@router.post("/schedule")
async def internal_create_schedule(request: Request, body: _ScheduleRequest):
    """Bridge'deki Claude bu endpoint'i çağırarak job oluşturur.

    cron_expr XOR run_at — ikisi birden veya ikisi de None → 400.
    APScheduler Europe/Istanbul timezone ile çalışır — cron ifadeleri TR saati olarak girilmeli.
    """
    _require_localhost(request)
    _validate_schedule_body(body)

    if body.cron_expr:
        from ..features.scheduler import create_scheduled_task
        try:
            task = await create_scheduled_task(
                description=body.description,
                cron_expr=body.cron_expr,
                action_type=body.action_type,
                message=body.message,
            )
        except ValueError as e:
            logger.error("create_scheduled_task ValueError: %s", e)
            raise HTTPException(status_code=400, detail="Geçersiz cron ifadesi")
    else:
        import time
        if body.run_at < time.time():
            raise HTTPException(
                status_code=400,
                detail="run_at geçmişte — gelecek bir zaman olmalı",
            )
        from ..features.scheduler import create_one_shot_task
        task = await create_one_shot_task(
            description=body.description,
            message=body.message,
            run_at=body.run_at,
            action_type=body.action_type,
        )

    logger.info("internal /schedule oluşturuldu: %s", task.get("id"))
    return task


@router.delete("/schedule/{task_id}")
async def internal_delete_schedule(request: Request, task_id: str):
    """Soft delete — job geçmişi korunur, APScheduler'dan kaldırılır."""
    _require_localhost(request)
    from ..features.scheduler import soft_delete_job
    await soft_delete_job(task_id)
    logger.info("internal /schedule soft-deleted: %s", task_id)
    return {"status": "deleted", "id": task_id}


@router.get("/schedules")
async def internal_list_schedules(request: Request):
    """Tüm job'ları listele (aktif + soft-deleted dahil)."""
    _require_localhost(request)
    from ..features.scheduler import list_cron_jobs
    return list_cron_jobs()


@router.put("/schedule/{task_id}")
async def internal_update_schedule(request: Request, task_id: str, body: _ScheduleRequest):
    """Güncelle = mevcut soft-delete + yenisini oluştur."""
    _require_localhost(request)
    _validate_schedule_body(body)

    from ..features.scheduler import soft_delete_job
    await soft_delete_job(task_id)

    if body.cron_expr:
        from ..features.scheduler import create_scheduled_task
        try:
            task = await create_scheduled_task(
                description=body.description,
                cron_expr=body.cron_expr,
                action_type=body.action_type,
                message=body.message,
            )
        except ValueError as e:
            logger.error("update_scheduled_task ValueError: %s", e)
            raise HTTPException(status_code=400, detail="Geçersiz cron ifadesi")
    else:
        import time
        from ..features.scheduler import create_one_shot_task
        task = await create_one_shot_task(
            description=body.description,
            message=body.message,
            run_at=body.run_at,
            action_type=body.action_type,
        )

    logger.info("internal /schedule güncellendi: %s → %s", task_id, task.get("id"))
    return task
