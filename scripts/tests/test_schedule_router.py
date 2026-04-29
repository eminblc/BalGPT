"""_schedule_router.py testleri.

Kapsam:
- Localhost kısıtlaması: harici IP → 403
- _validate_schedule_body: cron_expr XOR run_at zorunluluğu
- POST /internal/schedule: cron ve run_at yolları
- DELETE, GET, PUT endpoint'leri
"""
from __future__ import annotations

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import FastAPI, HTTPException
from httpx import AsyncClient, ASGITransport


def _make_app():
    from backend.routers._schedule_router import router
    from backend.routers.internal_router import router as internal_router
    app = FastAPI()
    app.include_router(router)
    return app


# ── _validate_schedule_body ───────────────────────────────────────────────────

def test_validate_both_raises():
    """cron_expr VE run_at birlikte → 400."""
    from backend.routers._schedule_router import _validate_schedule_body, _ScheduleRequest
    body = _ScheduleRequest(
        description="test",
        cron_expr="0 9 * * *",
        run_at=time.time() + 3600,
    )
    with pytest.raises(HTTPException) as exc:
        _validate_schedule_body(body)
    assert exc.value.status_code == 400
    assert "XOR" in exc.value.detail


def test_validate_neither_raises():
    """Ne cron_expr ne run_at → 400."""
    from backend.routers._schedule_router import _validate_schedule_body, _ScheduleRequest
    body = _ScheduleRequest(description="test")
    with pytest.raises(HTTPException) as exc:
        _validate_schedule_body(body)
    assert exc.value.status_code == 400


def test_validate_cron_only_ok():
    """Sadece cron_expr → hata yok."""
    from backend.routers._schedule_router import _validate_schedule_body, _ScheduleRequest
    body = _ScheduleRequest(description="test", cron_expr="0 9 * * *")
    _validate_schedule_body(body)  # exception fırlatmamalı


def test_validate_run_at_only_ok():
    """Sadece run_at → hata yok."""
    from backend.routers._schedule_router import _validate_schedule_body, _ScheduleRequest
    body = _ScheduleRequest(description="test", run_at=time.time() + 60)
    _validate_schedule_body(body)  # exception fırlatmamalı


# ── Localhost kısıtlaması ─────────────────────────────────────────────────────

async def test_external_ip_create_returns_403():
    """Harici IP → is_localhost=False → 403."""
    app = _make_app()
    with patch("backend.routers._schedule_router.is_localhost", return_value=False):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/schedule",
                json={"description": "test", "cron_expr": "0 9 * * *"},
            )
    assert resp.status_code == 403


async def test_external_ip_list_returns_403():
    """Harici IP → is_localhost=False → 403."""
    app = _make_app()
    with patch("backend.routers._schedule_router.is_localhost", return_value=False):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.get("/internal/schedules")
    assert resp.status_code == 403


# ── POST /internal/schedule — cron yolu ─────────────────────────────────────

async def test_create_cron_schedule_ok():
    """Geçerli cron_expr ile POST → create_scheduled_task çağrılır."""
    app = _make_app()
    fake_task = {"id": "task-1", "description": "test", "status": "scheduled"}

    with patch(
        "backend.routers._schedule_router.is_localhost", return_value=True
    ), patch(
        "backend.features.scheduler.create_scheduled_task",
        AsyncMock(return_value=fake_task),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/schedule",
                json={"description": "morning report", "cron_expr": "0 9 * * *"},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "task-1"


# ── POST /internal/schedule — run_at yolu ────────────────────────────────────

async def test_create_one_shot_schedule_ok():
    """Geçerli run_at ile POST → create_one_shot_task çağrılır."""
    app = _make_app()
    fake_task = {"id": "task-2", "description": "reminder", "status": "scheduled"}
    future_ts = time.time() + 3600

    with patch(
        "backend.routers._schedule_router.is_localhost", return_value=True
    ), patch(
        "backend.features.scheduler.create_one_shot_task",
        AsyncMock(return_value=fake_task),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/schedule",
                json={"description": "reminder", "run_at": future_ts},
            )

    assert resp.status_code == 200
    assert resp.json()["id"] == "task-2"


async def test_create_past_run_at_returns_400():
    """Geçmişte kalan run_at → 400."""
    app = _make_app()

    with patch("backend.routers._schedule_router.is_localhost", return_value=True):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.post(
                "/internal/schedule",
                json={"description": "old task", "run_at": time.time() - 60},
            )

    assert resp.status_code == 400


# ── DELETE /internal/schedule/{task_id} ──────────────────────────────────────

async def test_delete_schedule_ok():
    """DELETE → soft_delete_job çağrılır, id döner."""
    app = _make_app()

    with patch(
        "backend.routers._schedule_router.is_localhost", return_value=True
    ), patch(
        "backend.features.scheduler.soft_delete_job",
        AsyncMock(return_value=None),
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.delete("/internal/schedule/task-abc")

    assert resp.status_code == 200
    assert resp.json()["id"] == "task-abc"
    assert resp.json()["status"] == "deleted"


# ── GET /internal/schedules ────────────────────────────────────────────────

async def test_list_schedules_ok():
    """GET /internal/schedules → list_cron_jobs sonucu döner."""
    app = _make_app()
    fake_list = [{"id": "t1"}, {"id": "t2"}]

    with patch(
        "backend.routers._schedule_router.is_localhost", return_value=True
    ), patch(
        "backend.features.scheduler.list_cron_jobs",
        return_value=fake_list,
    ):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            resp = await client.get("/internal/schedules")

    assert resp.status_code == 200
    assert len(resp.json()) == 2
