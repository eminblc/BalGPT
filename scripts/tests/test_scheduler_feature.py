"""Scheduler feature — create_scheduled_task, create_one_shot_task, soft_delete_job,
list_cron_jobs, pause_cron_job, resume_cron_job testleri.

APScheduler ve SQLite store mock'lanır; gerçek iş zamanlama yapılmaz.
"""
import json
import logging
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


# ── SEC-SCAN2-F6 — _parse_cron alan aralığı doğrulama ─────────────

class TestParseCronFieldRangeValidation:
    """_parse_cron() değer aralığı doğrulaması (SEC-SCAN2-F6)."""

    def setup_method(self):
        from backend.features.scheduler import _parse_cron
        self._parse_cron = _parse_cron

    # Geçerli ifadeler — ValueError fırlatmamalı

    def test_valid_standard(self):
        """'0 9 * * *' → geçerli standart cron."""
        result = self._parse_cron("0 9 * * *")
        assert result["minute"] == "0"
        assert result["hour"] == "9"

    def test_valid_step(self):
        """'*/5 * * * *' → step ifadesi geçerli."""
        result = self._parse_cron("*/5 * * * *")
        assert result["minute"] == "*/5"

    def test_valid_range(self):
        """'0-30 * * * *' → aralık ifadesi geçerli."""
        result = self._parse_cron("0-30 * * * *")
        assert result["minute"] == "0-30"

    def test_valid_list(self):
        """'0,30 * * * *' → virgüllü liste geçerli."""
        result = self._parse_cron("0,30 * * * *")
        assert result["minute"] == "0,30"

    def test_valid_every_wildcard(self):
        """'* * * * *' → tam wildcard geçerli."""
        result = self._parse_cron("* * * * *")
        assert all(v == "*" for v in result.values())

    def test_valid_max_minute(self):
        """'59 23 31 12 7' → tüm alanlar maksimum sınırda geçerli."""
        result = self._parse_cron("59 23 31 12 7")
        assert result["minute"] == "59"
        assert result["hour"] == "23"

    # Geçersiz ifadeler — ValueError fırlatmalı

    def test_invalid_minute_60_raises(self):
        """'60 0 * * *' → dakika 60, max 59 → ValueError."""
        with pytest.raises(ValueError, match="minute"):
            self._parse_cron("60 0 * * *")

    def test_invalid_hour_24_raises(self):
        """'0 24 * * *' → saat 24, max 23 → ValueError."""
        with pytest.raises(ValueError, match="hour"):
            self._parse_cron("0 24 * * *")

    def test_invalid_day_32_raises(self):
        """'* * 32 * *' → gün 32, max 31 → ValueError."""
        with pytest.raises(ValueError, match="day"):
            self._parse_cron("* * 32 * *")

    def test_invalid_month_13_raises(self):
        """'* * * 13 *' → ay 13, max 12 → ValueError."""
        with pytest.raises(ValueError, match="month"):
            self._parse_cron("* * * 13 *")

    def test_invalid_day_of_week_8_raises(self):
        """'* * * * 8' → haftanın günü 8, max 7 → ValueError."""
        with pytest.raises(ValueError, match="day_of_week"):
            self._parse_cron("* * * * 8")

    def test_invalid_format_too_few_fields_raises(self):
        """'not-a-cron' → 5 alan gerekli → ValueError."""
        with pytest.raises(ValueError):
            self._parse_cron("not-a-cron")

    def test_invalid_format_too_many_fields_raises(self):
        """'0 0 * * * *' → 6 alan → ValueError."""
        with pytest.raises(ValueError):
            self._parse_cron("0 0 * * * *")

    def test_invalid_step_zero_raises(self):
        """'*/0 * * * *' → sıfır adım → ValueError."""
        with pytest.raises(ValueError):
            self._parse_cron("*/0 * * * *")

    def test_invalid_range_reversed_raises(self):
        """'30-10 * * * *' → ters aralık (a > b) → ValueError."""
        with pytest.raises(ValueError):
            self._parse_cron("30-10 * * * *")

    def test_invalid_list_out_of_range_raises(self):
        """'0,60 * * * *' → listede aralık dışı değer → ValueError."""
        with pytest.raises(ValueError, match="minute"):
            self._parse_cron("0,60 * * * *")

    def test_invalid_month_zero_raises(self):
        """'* * * 0 *' → ay 0, min 1 → ValueError."""
        with pytest.raises(ValueError, match="month"):
            self._parse_cron("* * * 0 *")

    def test_invalid_day_zero_raises(self):
        """'* * 0 * *' → gün 0, min 1 → ValueError."""
        with pytest.raises(ValueError, match="day"):
            self._parse_cron("* * 0 * *")


# ── SEC-SCAN2-F5 — JSON parse hatası loglanıyor ───────────────────

class TestExecuteTaskJsonParseLogging:
    """_execute_task ve _execute_one_shot_task JSON parse hatası log testi (SEC-SCAN2-F5)."""

    @pytest.mark.asyncio
    async def test_execute_task_invalid_json_logs_warning(self, caplog):
        """_execute_task: geçersiz action_payload → WARNING loglanır, hata fırlatmaz."""
        fake_task = {
            "id": "task-bad-json-1",
            "description": "Test görevi",
            "action_type": "send_message",
            "action_payload": "{invalid json",
            "status": "active",
        }

        with patch("backend.store.sqlite_store.task_get", AsyncMock(return_value=fake_task)), \
             patch("backend.store.sqlite_store.task_update_status", AsyncMock()), \
             patch("backend.store.sqlite_store.task_update_last_run", AsyncMock()), \
             patch("backend.features.scheduler._send_notification", AsyncMock()):
            from backend.features.scheduler import _execute_task

            with caplog.at_level(logging.WARNING, logger="backend.features.scheduler"):
                # Hata fırlatmamalı — graceful degradation
                await _execute_task("task-bad-json-1")

        assert any(
            "geçersiz JSON" in record.message or "action_payload" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ), f"WARNING logu bulunamadı. Loglar: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_execute_one_shot_task_invalid_json_logs_warning(self, caplog):
        """_execute_one_shot_task: geçersiz action_payload → WARNING loglanır, hata fırlatmaz."""
        fake_task = {
            "id": "task-oneshot-bad-json",
            "description": "One-shot test",
            "action_type": "send_message",
            "action_payload": "not-json-at-all",
            "status": "active",
        }

        with patch("backend.store.sqlite_store.task_get", AsyncMock(return_value=fake_task)), \
             patch("backend.store.sqlite_store.task_update_status", AsyncMock()), \
             patch("backend.store.sqlite_store.task_update_last_run", AsyncMock()), \
             patch("backend.store.sqlite_store.task_deactivate", AsyncMock()), \
             patch("backend.features.scheduler._send_notification", AsyncMock()):
            from backend.features.scheduler import _execute_one_shot_task

            with caplog.at_level(logging.WARNING, logger="backend.features.scheduler"):
                await _execute_one_shot_task("task-oneshot-bad-json")

        assert any(
            "geçersiz JSON" in record.message or "action_payload" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ), f"WARNING logu bulunamadı. Loglar: {[r.message for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_execute_task_valid_json_no_warning(self, caplog):
        """_execute_task: geçerli action_payload → WARNING loglanmaz."""
        fake_task = {
            "id": "task-good-json-1",
            "description": "Good task",
            "action_type": "send_message",
            "action_payload": json.dumps({"message": "Merhaba"}),
            "status": "active",
        }

        with patch("backend.store.sqlite_store.task_get", AsyncMock(return_value=fake_task)), \
             patch("backend.store.sqlite_store.task_update_status", AsyncMock()), \
             patch("backend.store.sqlite_store.task_update_last_run", AsyncMock()), \
             patch("backend.features.scheduler._send_notification", AsyncMock()):
            from backend.features.scheduler import _execute_task

            with caplog.at_level(logging.WARNING, logger="backend.features.scheduler"):
                await _execute_task("task-good-json-1")

        json_warning_logs = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "JSON" in r.message
        ]
        assert len(json_warning_logs) == 0

    @pytest.mark.asyncio
    async def test_execute_task_empty_payload_uses_description(self, caplog):
        """_execute_task: boş action_payload → task description mesaj olarak kullanılır."""
        fake_task = {
            "id": "task-empty-payload",
            "description": "Tanımlama metni",
            "action_type": "send_message",
            "action_payload": None,
            "status": "active",
        }
        sent_messages = []

        async def _capture_notification(text: str):
            sent_messages.append(text)

        with patch("backend.store.sqlite_store.task_get", AsyncMock(return_value=fake_task)), \
             patch("backend.store.sqlite_store.task_update_status", AsyncMock()), \
             patch("backend.store.sqlite_store.task_update_last_run", AsyncMock()), \
             patch("backend.features.scheduler._send_notification", side_effect=_capture_notification):
            from backend.features.scheduler import _execute_task

            await _execute_task("task-empty-payload")

        assert len(sent_messages) == 1
        assert "Tanımlama metni" in sent_messages[0]
