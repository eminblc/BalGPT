"""Plans feature — CRUD davranışı ve WhatsApp format fonksiyonu testleri.

db (sqlite_store) mock'lanır; gerçek DB'ye erişilmez.
"""
import pytest
from unittest.mock import AsyncMock, patch


# ── create_plan ───────────────────────────────────────────────────

async def test_create_plan_calls_db():
    """create_plan → db.plan_create çağrılmalı, sonuç döndürülmeli."""
    fake_plan = {"id": "p1", "title": "Görev", "priority": 2, "status": "active"}
    mock_db = AsyncMock()
    mock_db.plan_create = AsyncMock(return_value=fake_plan)

    with patch("backend.features.plans.db", mock_db):
        from backend.features.plans import create_plan
        result = await create_plan("Görev", "", 2)

    mock_db.plan_create.assert_awaited_once_with("Görev", "", 2, None, None)
    assert result == fake_plan


async def test_create_plan_with_due_date():
    import time
    ts = time.time()
    mock_db = AsyncMock()
    mock_db.plan_create = AsyncMock(return_value={"id": "p2", "title": "T", "due_date": ts})
    with patch("backend.features.plans.db", mock_db):
        from backend.features.plans import create_plan
        await create_plan("T", due_date=ts)
    assert mock_db.plan_create.call_args[0][3] == ts


# ── list_plans ────────────────────────────────────────────────────

async def test_list_plans_active_by_default():
    mock_db = AsyncMock()
    mock_db.plan_list = AsyncMock(return_value=[])
    with patch("backend.features.plans.db", mock_db):
        from backend.features.plans import list_plans
        result = await list_plans()
    mock_db.plan_list.assert_awaited_once_with("active")
    assert result == []


async def test_list_plans_completed_status():
    mock_db = AsyncMock()
    mock_db.plan_list = AsyncMock(return_value=[{"id": "p1"}])
    with patch("backend.features.plans.db", mock_db):
        from backend.features.plans import list_plans
        result = await list_plans("completed")
    mock_db.plan_list.assert_awaited_once_with("completed")
    assert len(result) == 1


# ── complete_plan ─────────────────────────────────────────────────

async def test_complete_plan_calls_db():
    mock_db = AsyncMock()
    mock_db.plan_complete = AsyncMock()
    with patch("backend.features.plans.db", mock_db):
        from backend.features.plans import complete_plan
        await complete_plan("plan-123")
    mock_db.plan_complete.assert_awaited_once_with("plan-123")


# ── format_plan_list ──────────────────────────────────────────────

def test_format_empty_list():
    from backend.features.plans import format_plan_list
    result = format_plan_list([])
    assert "yok" in result.lower()


def test_format_plan_list_includes_title():
    from backend.features.plans import format_plan_list
    plans = [{"id": "p1", "title": "Kritik görev", "priority": 1, "due_date": None}]
    result = format_plan_list(plans)
    assert "Kritik görev" in result


def test_format_plan_list_priority_emoji():
    from backend.features.plans import format_plan_list
    plans = [{"id": "p1", "title": "A", "priority": 1, "due_date": None},
             {"id": "p2", "title": "B", "priority": 3, "due_date": None}]
    result = format_plan_list(plans)
    assert "⭐" in result   # öncelik 1
    assert "🟢" in result   # öncelik 3
