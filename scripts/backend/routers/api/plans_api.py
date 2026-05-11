"""İş planı endpoint'leri — /plan, /plans (SRP)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ._deps import COMMON_DEPS
from ...config import settings

router = APIRouter(dependencies=COMMON_DEPS, tags=["plans"])

_PLANS_DISABLED = HTTPException(
    status_code=503,
    detail="Plans devre dışı (RESTRICT_PLANS=true)",
)


class PlanRequest(BaseModel):
    title: str = Field(..., description="Plan başlığı", json_schema_extra={"example": "API entegrasyonunu tamamla"})
    description: str = Field("", description="Opsiyonel açıklama", json_schema_extra={"example": "REST endpoint'leri yaz ve test et"})
    priority: int = Field(2, ge=1, le=4, description="Öncelik: 1=düşük, 2=orta, 3=yüksek, 4=kritik", json_schema_extra={"example": 2})
    due_date: float | None = Field(None, description="Bitiş tarihi (unix timestamp UTC), opsiyonel", json_schema_extra={"example": 1714568400.0})
    project_id: str | None = Field(None, description="Proje ID'si, opsiyonel", json_schema_extra={"example": "my-project"})


@router.post(
    "/plan",
    summary="İş planı oluştur",
    response_model=dict,
    responses={
        200: {"description": "Oluşturulan plan kaydı"},
        503: {"description": "Plans özelliği devre dışı (RESTRICT_PLANS=true)"},
    },
)
async def create_plan(body: PlanRequest):
    """Yeni bir iş planı oluşturur.

    `priority`: 1=düşük, 2=orta, 3=yüksek, 4=kritik. `due_date` opsiyonel olup
    unix timestamp (UTC) formatındadır. Plan belirli bir projeye bağlanacaksa
    `project_id` alanını doldurun.
    """
    if not settings.plans_enabled:
        raise _PLANS_DISABLED
    from ...features.plans import create_plan
    return await create_plan(body.title, body.description, body.priority, body.due_date, body.project_id)


@router.get(
    "/plans",
    summary="İş planlarını listele",
    response_model=list,
    responses={
        200: {"description": "İş planları listesi"},
        503: {"description": "Plans özelliği devre dışı (RESTRICT_PLANS=true)"},
    },
)
async def list_plans(
    status: str = Query(
        "active",
        description="Filtre durumu: 'active' (varsayılan), 'completed', 'all'",
        examples=["active", "completed", "all"],
    ),
):
    """Mevcut iş planlarını döndürür.

    `status` parametresiyle filtrelenebilir:
    - `active` — yalnızca devam eden planlar (varsayılan)
    - `completed` — yalnızca tamamlanan planlar
    - `all` — tüm planlar
    """
    if not settings.plans_enabled:
        raise _PLANS_DISABLED
    from ...features.plans import list_plans
    return await list_plans(status)


@router.post(
    "/plan/{plan_id}/complete",
    summary="Planı tamamlandı olarak işaretle",
    response_model=dict,
    responses={
        200: {"description": "Tamamlama durumu", "content": {"application/json": {"example": {"status": "completed"}}}},
        503: {"description": "Plans özelliği devre dışı (RESTRICT_PLANS=true)"},
    },
)
async def complete_plan(plan_id: str):
    """Belirtilen planı tamamlandı olarak işaretler.

    Plan durumu `completed` olarak güncellenir ve tekrarlanan sorgularda
    `status=completed` filtresiyle görünür hale gelir.
    """
    if not settings.plans_enabled:
        raise _PLANS_DISABLED
    from ...features.plans import complete_plan
    await complete_plan(plan_id)
    return {"status": "completed"}
