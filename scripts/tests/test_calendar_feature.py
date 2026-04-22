"""Takvim feature — create_event ve list_upcoming testleri.

DB çağrıları mock'lanır; gerçek SQLite bağlantısı açılmaz.
"""
import pytest
import time
from unittest.mock import AsyncMock, patch


async def test_create_event_returns_dict():
    """create_event → DB'ye yazar ve oluşturulan event dict döner."""
    fake_event = {
        "id": "evt-uuid-1",
        "title": "Doktor Randevusu",
        "event_time": time.time() + 86400,
        "description": "",
        "remind_before_minutes": 30,
        "recurring": None,
    }

    with patch(
        "backend.store.sqlite_wrapper.store.event_create",
        AsyncMock(return_value=fake_event),
    ):
        from backend.features.calendar import create_event

        result = await create_event(
            title="Doktor Randevusu",
            event_time=fake_event["event_time"],
        )

    assert result["id"] == "evt-uuid-1"
    assert result["title"] == "Doktor Randevusu"


async def test_list_upcoming_returns_list():
    """list_upcoming → DB'den gelecek etkinlikleri döner."""
    fake_events = [
        {"id": "e1", "title": "Toplantı", "event_time": time.time() + 3600},
        {"id": "e2", "title": "Randevu", "event_time": time.time() + 7200},
    ]

    with patch(
        "backend.store.sqlite_wrapper.store.event_list_upcoming",
        AsyncMock(return_value=fake_events),
    ):
        from backend.features.calendar import list_upcoming

        result = await list_upcoming(limit=5)

    assert len(result) == 2
    assert result[0]["title"] == "Toplantı"
    assert result[1]["id"] == "e2"
