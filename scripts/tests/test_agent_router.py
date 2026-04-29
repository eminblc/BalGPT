"""Personal agent router — API key zorunluluğu ve endpoint routing testleri.

httpx.AsyncClient + ASGITransport ile FastAPI test client kullanılır.
Tüm feature fonksiyonları mock'lanır; DB'ye erişilmez.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from fastapi import FastAPI


def _make_app(api_key: str = "test-api-key-123"):
    """Test için izole edilmiş FastAPI app — sadece agent router."""
    from backend.routers.personal_agent_router import router
    app = FastAPI()
    app.include_router(router, prefix="/agent")

    # settings.api_key ve environment'ı patch'le
    mock_secret = MagicMock()
    mock_secret.get_secret_value.return_value = api_key
    return app, mock_secret


# ── API key zorunluluğu ───────────────────────────────────────────

async def test_missing_api_key_returns_401():
    app, mock_secret = _make_app()
    with patch("backend.guards.api_key.settings") as s:
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/agent/plans")
    assert resp.status_code == 401


async def test_wrong_api_key_returns_401():
    app, mock_secret = _make_app()
    with patch("backend.guards.api_key.settings") as s:
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/agent/plans",
                                    headers={"X-Api-Key": "wrong-key"})
    assert resp.status_code == 401


# ── /agent/plans ──────────────────────────────────────────────────

async def test_list_plans_with_valid_key_returns_200():
    app, mock_secret = _make_app()
    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit",
               return_value=None), \
         patch("backend.features.plans.list_plans",
               AsyncMock(return_value=[])):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/agent/plans",
                                    headers={"X-Api-Key": "test-api-key-123"})
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_plan_with_valid_key_returns_200():
    app, mock_secret = _make_app()
    fake_plan = {"id": "plan-1", "title": "Test Plan", "status": "active"}

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit",
               return_value=None), \
         patch("backend.features.plans.create_plan",
               AsyncMock(return_value=fake_plan)):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/plan",
                json={"title": "Test Plan"},
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Test Plan"


# ── /agent/calendar ───────────────────────────────────────────────

async def test_list_calendar_with_valid_key():
    app, mock_secret = _make_app()
    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit",
               return_value=None), \
         patch("backend.features.calendar.list_upcoming",
               AsyncMock(return_value=[])):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/agent/calendar",
                                    headers={"X-Api-Key": "test-api-key-123"})
    assert resp.status_code == 200


# ── /agent/projects ───────────────────────────────────────────────

async def test_list_projects_with_valid_key():
    app, mock_secret = _make_app()
    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit",
               return_value=None), \
         patch("backend.features.projects.list_projects",
               AsyncMock(return_value=[])):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/agent/projects",
                                    headers={"X-Api-Key": "test-api-key-123"})
    assert resp.status_code == 200


# ── /agent/plan/{id}/complete ─────────────────────────────────────

async def test_complete_plan_with_valid_key():
    app, mock_secret = _make_app()
    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit",
               return_value=None), \
         patch("backend.features.plans.complete_plan", AsyncMock()):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/plan/plan-1/complete",
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 200
    assert resp.json() == {"status": "completed"}


# ── /agent/calendar (POST) ────────────────────────────────────────

async def test_create_event_with_valid_key():
    """POST /agent/calendar — geçerli key → 200."""
    import time
    app, mock_secret = _make_app()
    fake_event = {"id": "evt-1", "title": "Toplantı", "event_time": time.time() + 3600}

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
         patch("backend.features.calendar.create_event",
               AsyncMock(return_value=fake_event)):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/calendar",
                json={"title": "Toplantı", "event_time": time.time() + 3600},
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 200
    assert resp.json()["id"] == "evt-1"


# ── /agent/project (POST) ─────────────────────────────────────────

async def test_create_project_with_valid_key():
    """POST /agent/project — geçerli key → 200."""
    app, mock_secret = _make_app()
    fake_project = {"id": "proj-1", "name": "yeni-proje"}

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
         patch("backend.features.projects.create_project",
               AsyncMock(return_value=fake_project)):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/project",
                json={"name": "yeni-proje", "description": "test"},
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 200
    assert resp.json()["name"] == "yeni-proje"


# ── /agent/project/{id}/beta ──────────────────────────────────────

async def test_start_beta_unauthorized_sender_returns_403():
    """POST /agent/project/{id}/beta — yetkisiz sender → 403."""
    app, mock_secret = _make_app()

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
         patch("backend.routers.api.projects_api.settings") as proj_settings, \
         patch("backend.routers.api.projects_api.get_perm_mgr",
               return_value=MagicMock(is_owner=MagicMock(return_value=False))):
        s.api_key = mock_secret
        s.environment = "development"
        proj_settings.whatsapp_owner = "+905300000000"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/project/proj-1/beta",
                json={"sender": "+901234567890"},
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 403


async def test_start_beta_authorized_sender_returns_200():
    """POST /agent/project/{id}/beta — yetkili sender → 200."""
    app, mock_secret = _make_app()

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
         patch("backend.routers.api.projects_api.settings") as proj_settings, \
         patch("backend.routers.api.projects_api.get_perm_mgr",
               return_value=MagicMock(is_owner=MagicMock(return_value=True))), \
         patch("backend.features.projects.start_beta_mode", AsyncMock()):
        s.api_key = mock_secret
        s.environment = "development"
        proj_settings.whatsapp_owner = "+905300000000"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/project/proj-1/beta",
                json={"sender": "+905300000000"},
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == "beta_started"


# ── /agent/schedule (POST) ────────────────────────────────────────

async def test_create_cron_schedule_agent():
    """POST /agent/schedule — cron → 200."""
    app, mock_secret = _make_app()
    fake_task = {"id": "sched-1", "description": "Daily"}

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
         patch("backend.features.scheduler.create_scheduled_task",
               AsyncMock(return_value=fake_task)):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/schedule",
                json={"description": "Daily", "cron_expr": "0 9 * * *"},
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 200
    assert resp.json()["id"] == "sched-1"


async def test_create_schedule_both_params_returns_400():
    """cron_expr + run_at ikisi birden → 400."""
    import time
    app, mock_secret = _make_app()

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/schedule",
                json={
                    "description": "Çift",
                    "cron_expr": "0 9 * * *",
                    "run_at": time.time() + 3600,
                },
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 400


async def test_create_schedule_neither_returns_400():
    """cron_expr ve run_at ikisi de yok → 400."""
    app, mock_secret = _make_app()

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/schedule",
                json={"description": "Eksik"},
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 400


# ── /agent/schedules (GET) ────────────────────────────────────────

async def test_list_schedules_agent():
    """GET /agent/schedules → 200."""
    app, mock_secret = _make_app()
    fake_list = [{"id": "s1"}, {"id": "s2"}]

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
         patch("backend.features.scheduler.list_cron_jobs", return_value=fake_list):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/agent/schedules",
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# ── /agent/schedule/{id} (DELETE) ────────────────────────────────

async def test_delete_schedule_agent():
    """DELETE /agent/schedule/{id} → {status: deleted}."""
    app, mock_secret = _make_app()

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
         patch("backend.features.scheduler.soft_delete_job", AsyncMock()):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete(
                "/agent/schedule/sched-99",
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == "deleted"


# ── /agent/schedule/{id}/pause ve /resume ────────────────────────

async def test_pause_schedule_agent():
    """POST /agent/schedule/{id}/pause → {status: paused}."""
    app, mock_secret = _make_app()

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
         patch("backend.features.scheduler.pause_cron_job"):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/schedule/sched-1/pause",
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"


async def test_resume_schedule_agent():
    """POST /agent/schedule/{id}/resume → {status: resumed}."""
    app, mock_secret = _make_app()

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
         patch("backend.features.scheduler.resume_cron_job"):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/schedule/sched-1/resume",
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == "resumed"


# ── /agent/pdf-import ────────────────────────────────────────────

async def test_pdf_import_with_valid_key():
    """POST /agent/pdf-import — geçerli key → 200."""
    app, mock_secret = _make_app()

    with patch("backend.guards.api_key.settings") as s, \
         patch("backend.routers.api._deps.require_api_rate_limit", return_value=None), \
         patch("backend.features.pdf_importer.import_from_whatsapp_media",
               AsyncMock(return_value={"status": "imported", "pages": 3})):
        s.api_key = mock_secret
        s.environment = "development"
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/agent/pdf-import",
                json={"media_id": "media-abc", "sender": "+905300000000"},
                headers={"X-Api-Key": "test-api-key-123"},
            )
    assert resp.status_code == 200
    assert resp.json()["status"] == "imported"
