"""İş planı endpoint'leri — /plan, /plans (SRP)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ._deps import COMMON_DEPS
from ...config import settings

router = APIRouter(dependencies=COMMON_DEPS)

_PLANS_DISABLED = HTTPException(
    status_code=503,
    detail="Plans devre dışı (RESTRICT_PLANS=true)",
)


class PlanRequest(BaseModel):
    title: str
    description: str = ""
    priority: int = 2
    due_date: float | None = None
    project_id: str | None = None


@router.post("/plan")
async def create_plan(body: PlanRequest):
    if not settings.plans_enabled:
        raise _PLANS_DISABLED
    from ...features.plans import create_plan
    return await create_plan(body.title, body.description, body.priority, body.due_date, body.project_id)


@router.get("/plans")
async def list_plans(status: str = "active"):
    if not settings.plans_enabled:
        raise _PLANS_DISABLED
    from ...features.plans import list_plans
    return await list_plans(status)


@router.post("/plan/{plan_id}/complete")
async def complete_plan(plan_id: str):
    if not settings.plans_enabled:
        raise _PLANS_DISABLED
    from ...features.plans import complete_plan
    await complete_plan(plan_id)
    return {"status": "completed"}
