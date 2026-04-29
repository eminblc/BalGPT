"""Takvim endpoint'leri — /calendar (SRP)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ._deps import COMMON_DEPS
from ...config import settings

router = APIRouter(dependencies=COMMON_DEPS)

_CALENDAR_DISABLED = HTTPException(
    status_code=503,
    detail="Calendar devre dışı (RESTRICT_CALENDAR=true)",
)


class EventRequest(BaseModel):
    title: str
    event_time: float
    description: str = ""
    remind_before_minutes: int = 30
    recurring: str | None = None


@router.post("/calendar")
async def create_event(body: EventRequest):
    if settings.restrict_calendar:
        raise _CALENDAR_DISABLED
    from ...features.calendar import create_event
    return await create_event(body.title, body.event_time, body.description,
                               body.remind_before_minutes, body.recurring)


@router.get("/calendar")
async def list_events():
    if settings.restrict_calendar:
        raise _CALENDAR_DISABLED
    from ...features.calendar import list_upcoming
    return await list_upcoming()
