"""Zamanlama endpoint'leri — /schedule, /schedules (SRP)."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from ._deps import COMMON_DEPS
from ...config import settings

router = APIRouter(dependencies=COMMON_DEPS, tags=["scheduler"])

_SCHEDULER_DISABLED = HTTPException(
    status_code=503,
    detail="Scheduler devre dışı (RESTRICT_SCHEDULER=true)",
)


class ScheduleRequest(BaseModel):
    description: str = Field(..., example="Her sabah 9'da haber özeti", description="İş açıklaması")
    action_type: str = Field(
        "run_bridge",
        example="run_bridge",
        description="'run_bridge' — mesajı Bridge'e gönder (Claude yanıtlar), 'send_message' — metni doğrudan kullanıcıya gönder",
    )
    message: str = Field(
        "",
        example="Bugünkü haber özetini hazırla",
        description="Bridge'e gönderilecek prompt (run_bridge) veya kullanıcıya gönderilecek metin (send_message). Boşsa description kullanılır.",
    )
    cron_expr: Optional[str] = Field(
        None,
        example="0 9 * * *",
        description="Cron ifadesi — yerel saat (TIMEZONE ayarına göre). cron_expr XOR run_at.",
    )
    run_at: Optional[float] = Field(
        None,
        example=1714654800.0,
        description="Tek seferlik çalışma zamanı (Unix timestamp UTC). cron_expr XOR run_at.",
    )


@router.post(
    "/schedule",
    summary="Zamanlı görev oluştur",
    response_model=dict,
    responses={
        200: {"description": "Oluşturulan görev kaydı"},
        400: {"description": "Geçersiz istek — cron_expr veya run_at gerekli, ikisi birden kullanılamaz"},
        503: {"description": "Scheduler devre dışı (RESTRICT_SCHEDULER=true)"},
    },
)
async def create_schedule(body: ScheduleRequest):
    """Cron tabanlı veya tek seferlik zamanlı görev oluşturur.

    **`cron_expr` XOR `run_at`** — ikisi birden kullanılamaz, biri zorunludur.

    - `cron_expr` belirtilirse: tekrarlayan görev (ör. `"0 9 * * *"` = her gün 09:00 yerel saat)
    - `run_at` belirtilirse: tek seferlik görev (unix timestamp UTC)

    `action_type`:
    - `run_bridge` — `message` alanındaki promptu Bridge'e gönderir, Claude yanıtlar ve kullanıcıya iletilir
    - `send_message` — `message` alanındaki metni doğrudan kullanıcıya gönderir
    """
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


@router.get(
    "/schedules",
    summary="Zamanlı görevleri listele",
    response_model=list,
    responses={
        200: {"description": "Aktif ve duraklatılmış zamanlı görevler"},
        503: {"description": "Scheduler devre dışı (RESTRICT_SCHEDULER=true)"},
    },
)
async def list_schedules():
    """Tüm cron ve tek seferlik görevleri döndürür.

    Silinmiş (soft-deleted) görevler dahil edilmez.
    Her kayıt: `id`, `description`, `action_type`, `cron_expr`/`run_at`, `status` alanlarını içerir.
    """
    if not settings.scheduler_enabled:
        raise _SCHEDULER_DISABLED
    from ...features.scheduler import list_cron_jobs
    return list_cron_jobs()


@router.delete(
    "/schedule/{task_id}",
    summary="Zamanlı görevi sil",
    response_model=dict,
    responses={
        200: {
            "description": "Görev silindi (soft delete)",
            "content": {"application/json": {"example": {"status": "deleted"}}},
        },
        503: {"description": "Scheduler devre dışı (RESTRICT_SCHEDULER=true)"},
    },
)
async def delete_schedule(task_id: str):
    """Belirtilen görevi soft-delete ile siler.

    Görev kaydı veritabanında korunur ancak APScheduler'dan kaldırılır.
    Silme işlemi geri alınamaz.
    """
    if not settings.scheduler_enabled:
        raise _SCHEDULER_DISABLED
    from ...features.scheduler import soft_delete_job
    await soft_delete_job(task_id)
    return {"status": "deleted"}


@router.post(
    "/schedule/{task_id}/pause",
    summary="Zamanlı görevi duraklat",
    response_model=dict,
    responses={
        200: {
            "description": "Görev duraklatıldı",
            "content": {"application/json": {"example": {"status": "paused"}}},
        },
        503: {"description": "Scheduler devre dışı (RESTRICT_SCHEDULER=true)"},
    },
)
async def pause_schedule(task_id: str):
    """Belirtilen cron görevini geçici olarak duraklatır.

    Görev APScheduler'da `paused` durumuna geçer; tetiklenmeyi durdurun,
    `/resume` ile yeniden etkinleştirilebilir.
    """
    if not settings.scheduler_enabled:
        raise _SCHEDULER_DISABLED
    from ...features.scheduler import pause_cron_job
    pause_cron_job(task_id)
    return {"status": "paused"}


@router.post(
    "/schedule/{task_id}/resume",
    summary="Duraklatılmış görevi devam ettir",
    response_model=dict,
    responses={
        200: {
            "description": "Görev devam ettirildi",
            "content": {"application/json": {"example": {"status": "resumed"}}},
        },
        503: {"description": "Scheduler devre dışı (RESTRICT_SCHEDULER=true)"},
    },
)
async def resume_schedule(task_id: str):
    """Daha önce duraklatılmış bir cron görevini yeniden etkinleştirir.

    Görev APScheduler'da `active` durumuna geçer ve bir sonraki cron
    zamanında tetiklenmeye başlar.
    """
    if not settings.scheduler_enabled:
        raise _SCHEDULER_DISABLED
    from ...features.scheduler import resume_cron_job
    resume_cron_job(task_id)
    return {"status": "resumed"}
