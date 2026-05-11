"""Takvim endpoint'leri — /calendar (SRP)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ._deps import COMMON_DEPS
from ...config import settings

router = APIRouter(dependencies=COMMON_DEPS, tags=["calendar"])

_CALENDAR_DISABLED = HTTPException(
    status_code=503,
    detail="Calendar devre dışı (RESTRICT_CALENDAR=true)",
)


class EventRequest(BaseModel):
    title: str = Field(..., description="Etkinlik başlığı", json_schema_extra={"example": "Doktor randevusu"})
    event_time: float = Field(..., description="Unix timestamp (UTC)", json_schema_extra={"example": 1714568400.0})
    description: str = Field("", description="Opsiyonel açıklama", json_schema_extra={"example": "Kardiyoloji kontrolü"})
    remind_before_minutes: int = Field(30, description="Kaç dakika önce hatırlatılsın", json_schema_extra={"example": 30})
    recurring: str | None = Field(None, description="Tekrar tipi: 'daily', 'weekly', 'monthly' veya None", json_schema_extra={"example": "daily"})


@router.post(
    "/calendar",
    summary="Takvim etkinliği oluştur",
    response_model=dict,
    responses={
        200: {"description": "Oluşturulan etkinlik"},
        503: {"description": "Takvim özelliği devre dışı (RESTRICT_CALENDAR=true)"},
    },
)
async def create_event(body: EventRequest):
    """Yeni bir takvim etkinliği oluşturur.

    `event_time` UTC unix timestamp olmalıdır. Hatırlatıcı, etkinlik zamanından
    `remind_before_minutes` dakika önce gönderilir. Tekrarlayan etkinlikler için
    `recurring` alanını kullanın: `'daily'`, `'weekly'`, `'monthly'`.
    """
    if settings.restrict_calendar:
        raise _CALENDAR_DISABLED
    from ...features.calendar import create_event
    return await create_event(body.title, body.event_time, body.description,
                               body.remind_before_minutes, body.recurring)


@router.get(
    "/calendar",
    summary="Yaklaşan etkinlikleri listele",
    response_model=list,
    responses={
        200: {"description": "Yaklaşan takvim etkinlikleri listesi"},
        503: {"description": "Takvim özelliği devre dışı (RESTRICT_CALENDAR=true)"},
    },
)
async def list_events():
    """Yaklaşan tüm takvim etkinliklerini döndürür.

    Etkinlikler olay zamanına göre sıralanmış olarak döner.
    Geçmiş etkinlikler dahil edilmez.
    """
    if settings.restrict_calendar:
        raise _CALENDAR_DISABLED
    from ...features.calendar import list_upcoming
    return await list_upcoming()
