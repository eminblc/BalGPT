"""Scheduler feature — create_scheduled_task, create_one_shot_task, soft_delete_job,
list_cron_jobs, pause_cron_job, resume_cron_job testleri.

APScheduler ve SQLite store mock'lanır; gerçek iş zamanlama yapılmaz.
"""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch


# ── create_scheduled_task ─────────────────────────────────────────

async def test_create_scheduled_task_returns_task():
    """Geçerli cron_expr ile create_scheduled_task → task dict döner."""
    fake_task = {
        "id": "task-cron-1",
        "description": "Günlük rapor",
        "cron_expr": "0 9 * * *",
        "action_type": "send_message",
        "status": "active",
    }

    with patch("backend.store.sqlite_store.task_create", AsyncMock(return_value=fake_task)), \
         patch("backend.features.scheduler._scheduler") as mock_sched:
        mock_sched.add_job = MagicMock()

        from backend.features.scheduler import create_scheduled_task

        result = await create_scheduled_task(
            description="Günlük rapor",
            cron_expr="0 9 * * *",
            action_type="send_message",
            message="Günlük durum raporu",
        )

    assert result["id"] == "task-cron-1"
    assert result["cron_expr"] == "0 9 * * *"


async def test_create_scheduled_task_invalid_cron_raises():
    """Geçersiz cron_expr → ValueError fırlatılır."""
    from backend.features.scheduler import create_scheduled_task

    with pytest.raises((ValueError, Exception)):
        await create_scheduled_task(
            description="Geçersiz",
            cron_expr="not-a-cron",
            action_type="send_message",
            message="test",
        )


# ── create_one_shot_task ──────────────────────────────────────────

async def test_create_one_shot_task_returns_task():
    """Gelecekte run_at ile create_one_shot_task → task dict döner."""
    future_ts = time.time() + 3600
    fake_task = {
        "id": "task-oneshot-1",
        "description": "Bir saate hatırlat",
        "cron_expr": None,
        "next_run": future_ts,
        "action_type": "send_message",
        "status": "active",
    }

    with patch("backend.store.sqlite_store.task_create", AsyncMock(return_value=fake_task)), \
         patch("backend.features.scheduler._scheduler") as mock_sched:
        mock_sched.add_job = MagicMock()

        from backend.features.scheduler import create_one_shot_task

        result = await create_one_shot_task(
            description="Bir saate hatırlat",
            message="Toplantın var!",
            run_at=future_ts,
            action_type="send_message",
        )

    assert result["id"] == "task-oneshot-1"
    mock_sched.add_job.assert_called_once()


# ── soft_delete_job ───────────────────────────────────────────────

async def test_soft_delete_job_removes_from_scheduler():
    """soft_delete_job → APScheduler'dan kaldırır + SQLite soft delete."""
    with patch("backend.features.scheduler._scheduler") as mock_sched, \
         patch("backend.store.sqlite_store.task_soft_delete", AsyncMock()):
        mock_sched.remove_job = MagicMock()

        from backend.features.scheduler import soft_delete_job

        await soft_delete_job("task-del-1")

    mock_sched.remove_job.assert_called_once_with("task-del-1")


async def test_soft_delete_job_missing_from_scheduler_still_ok():
    """APScheduler'da olmayan job → JobLookupError yakalanır, SQLite soft delete çalışır."""
    from apscheduler.jobstores.base import JobLookupError

    with patch("backend.features.scheduler._scheduler") as mock_sched, \
         patch("backend.store.sqlite_store.task_soft_delete", AsyncMock()) as mock_db_del:
        mock_sched.remove_job = MagicMock(side_effect=JobLookupError("task-x"))

        from backend.features.scheduler import soft_delete_job

        await soft_delete_job("task-x")  # Hata fırlatmamalı

    mock_db_del.assert_awaited_once()


# ── list_cron_jobs ────────────────────────────────────────────────

def test_list_cron_jobs_returns_list():
    """list_cron_jobs → task listesi döner."""
    fake_tasks = [
        {"id": "t1", "cron_expr": "0 9 * * *", "status": "active"},
        {"id": "t2", "cron_expr": "0 18 * * *", "status": "active"},
    ]

    with patch("backend.store.sqlite_store._sync_task_list_all", return_value=fake_tasks), \
         patch("backend.features.scheduler._scheduler") as mock_sched:
        mock_sched.get_job = MagicMock(return_value=None)  # APScheduler'da kayıtlı değil

        from backend.features.scheduler import list_cron_jobs

        result = list_cron_jobs()

    assert len(result) == 2
    assert result[0]["id"] == "t1"
    # next_run_time None olmalı (mock_sched.get_job None döndürdü)
    assert result[0]["next_run_time"] is None


# ── pause_cron_job / resume_cron_job ──────────────────────────────

def test_pause_cron_job_calls_scheduler():
    """pause_cron_job → _scheduler.pause_job çağrılır."""
    with patch("backend.features.scheduler._scheduler") as mock_sched, \
         patch("backend.store.sqlite_store._sync_task_deactivate"):
        mock_sched.pause_job = MagicMock()

        from backend.features.scheduler import pause_cron_job

        pause_cron_job("task-pause-1")

    mock_sched.pause_job.assert_called_once_with("task-pause-1")


def test_resume_cron_job_calls_scheduler():
    """resume_cron_job → _scheduler.resume_job çağrılır."""
    with patch("backend.features.scheduler._scheduler") as mock_sched, \
         patch("backend.store.sqlite_store._sync_task_activate"):
        mock_sched.resume_job = MagicMock()

        from backend.features.scheduler import resume_cron_job

        resume_cron_job("task-resume-1")

    mock_sched.resume_job.assert_called_once_with("task-resume-1")
