"""AgentRun repository testleri — geçici SQLite DB ile."""
import asyncio
import time
import pytest
from unittest.mock import patch


# ── Paylaşılan DB fixture ─────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Her test için temiz geçici SQLite DB; init_db çalıştırılmış."""
    db_file = tmp_path / "test_agent_run.db"
    with patch("backend.store._connection._resolve_db_path", return_value=db_file):
        from backend.store import sqlite_store
        sqlite_store.init_db()
        yield db_file


# ── Yardımcı ─────────────────────────────────────────────────────

def _create_run(tmp_db, agent_type="scheduler_cron", session_id="test-session",
                project_id=None, **kwargs):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_create
        return asyncio.run(agent_run_create(
            agent_type, session_id,
            project_id=project_id,
            **kwargs,
        ))


# ── test_agent_run_create_returns_id ─────────────────────────────

def test_agent_run_create_returns_id(tmp_db):
    """run oluşturulunca string id döner."""
    run_id = _create_run(tmp_db)
    assert isinstance(run_id, str)
    assert len(run_id) > 0


def test_agent_run_create_initial_status_pending(tmp_db):
    """Yeni oluşturulan run'ın status'u 'pending' olmalı."""
    run_id = _create_run(tmp_db)
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_get
        run = asyncio.run(agent_run_get(run_id))
    assert run is not None
    assert run["status"] == "pending"


# ── test_agent_run_status_running_sets_started_at ────────────────

def test_agent_run_status_running_sets_started_at(tmp_db):
    """status='running' yaptığında started_at set edilir."""
    run_id = _create_run(tmp_db)
    before = time.time()
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_update_status, agent_run_get
        asyncio.run(agent_run_update_status(run_id, "running"))
        run = asyncio.run(agent_run_get(run_id))
    assert run["status"] == "running"
    assert run["started_at"] is not None
    assert run["started_at"] >= before


# ── test_agent_run_status_completed_sets_completed_at ────────────

def test_agent_run_status_completed_sets_completed_at(tmp_db):
    """status='completed' yaptığında completed_at ve duration_ms set edilir."""
    run_id = _create_run(tmp_db)
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_update_status, agent_run_get
        asyncio.run(agent_run_update_status(run_id, "running"))
        before_complete = time.time()
        asyncio.run(agent_run_update_status(run_id, "completed", output="done"))
        run = asyncio.run(agent_run_get(run_id))

    assert run["status"] == "completed"
    assert run["completed_at"] is not None
    assert run["completed_at"] >= before_complete
    assert run["duration_ms"] is not None
    assert run["duration_ms"] >= 0
    assert run["output"] == "done"


def test_agent_run_status_completed_duration_ms_provided(tmp_db):
    """Explicit duration_ms sağlanınca o değer kullanılır."""
    run_id = _create_run(tmp_db)
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_update_status, agent_run_get
        asyncio.run(agent_run_update_status(run_id, "running"))
        asyncio.run(agent_run_update_status(run_id, "completed", duration_ms=1234))
        run = asyncio.run(agent_run_get(run_id))

    assert run["duration_ms"] == 1234


# ── test_agent_run_status_failed ─────────────────────────────────

def test_agent_run_status_failed(tmp_db):
    """status='failed' + error_msg kaydedilir."""
    run_id = _create_run(tmp_db)
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_update_status, agent_run_get
        asyncio.run(agent_run_update_status(run_id, "running"))
        asyncio.run(agent_run_update_status(
            run_id, "failed",
            error_msg="Connection timeout",
            exit_code=1,
        ))
        run = asyncio.run(agent_run_get(run_id))

    assert run["status"] == "failed"
    assert run["error_msg"] == "Connection timeout"
    assert run["exit_code"] == 1
    assert run["completed_at"] is not None


# ── test_agent_run_cancel ─────────────────────────────────────────

def test_agent_run_cancel(tmp_db):
    """cancel sonrası status='cancelled'."""
    run_id = _create_run(tmp_db)
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_cancel, agent_run_get
        asyncio.run(agent_run_cancel(run_id))
        run = asyncio.run(agent_run_get(run_id))

    assert run["status"] == "cancelled"
    assert run["completed_at"] is not None


# ── test_agent_run_list_filter_by_status ─────────────────────────

def test_agent_run_list_filter_by_status(tmp_db):
    """list() status filter çalışır."""
    run1 = _create_run(tmp_db, agent_type="type_a")
    run2 = _create_run(tmp_db, agent_type="type_b")

    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_update_status, agent_run_list
        asyncio.run(agent_run_update_status(run1, "running"))
        # run2 'pending' olarak kalır

        pending_runs = asyncio.run(agent_run_list(status="pending"))
        running_runs = asyncio.run(agent_run_list(status="running"))

    assert len(pending_runs) == 1
    assert pending_runs[0]["id"] == run2

    assert len(running_runs) == 1
    assert running_runs[0]["id"] == run1


# ── test_agent_run_list_filter_by_project ────────────────────────

def test_agent_run_list_filter_by_project(tmp_db):
    """list() project_id filter çalışır."""
    # project_id foreign key kısıtlaması; kısıtlamayı bypass etmek için
    # önce projeler tablosuna kayıt ekle
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.project_repo import project_create
        asyncio.run(project_create("Proje A", path="/tmp/proje-a-run"))
        asyncio.run(project_create("Proje B", path="/tmp/proje-b-run"))

    run_a1 = _create_run(tmp_db, project_id="proje-a")
    run_a2 = _create_run(tmp_db, project_id="proje-a")
    _run_b = _create_run(tmp_db, project_id="proje-b")

    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_list
        runs_a = asyncio.run(agent_run_list(project_id="proje-a"))
        runs_b = asyncio.run(agent_run_list(project_id="proje-b"))

    assert len(runs_a) == 2
    ids_a = {r["id"] for r in runs_a}
    assert run_a1 in ids_a
    assert run_a2 in ids_a

    assert len(runs_b) == 1


# ── test_agent_run_list_active ────────────────────────────────────

def test_agent_run_list_active(tmp_db):
    """list_active() sadece pending+running döner."""
    run_pending = _create_run(tmp_db, agent_type="pending_type")
    run_running = _create_run(tmp_db, agent_type="running_type")
    run_done = _create_run(tmp_db, agent_type="done_type")

    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import (
            agent_run_update_status, agent_run_list_active,
        )
        asyncio.run(agent_run_update_status(run_running, "running"))
        asyncio.run(agent_run_update_status(run_done, "completed"))

        active = asyncio.run(agent_run_list_active())

    active_ids = {r["id"] for r in active}
    assert run_pending in active_ids
    assert run_running in active_ids
    assert run_done not in active_ids


def test_agent_run_list_active_oldest_first(tmp_db):
    """list_active() sıralama: en eski önce (created_at ASC)."""
    run1 = _create_run(tmp_db, agent_type="first")
    time.sleep(0.01)
    run2 = _create_run(tmp_db, agent_type="second")

    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_list_active
        active = asyncio.run(agent_run_list_active())

    assert active[0]["id"] == run1
    assert active[1]["id"] == run2


# ── test_agent_run_get_not_found ─────────────────────────────────

def test_agent_run_get_not_found(tmp_db):
    """Olmayan id için None döner."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_get
        result = asyncio.run(agent_run_get("nonexistent-run-id"))
    assert result is None


# ── Ek senaryolar ─────────────────────────────────────────────────

def test_agent_run_metadata_persisted(tmp_db):
    """metadata dict DB'ye JSON olarak kaydedilir."""
    run_id = _create_run(tmp_db, metadata={"key": "value", "count": 42})
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_get
        run = asyncio.run(agent_run_get(run_id))
    import json
    meta = json.loads(run["metadata"])
    assert meta["key"] == "value"
    assert meta["count"] == 42


def test_agent_run_list_limit(tmp_db):
    """list() limit parametresi çalışır."""
    for _ in range(5):
        _create_run(tmp_db)

    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_list
        runs = asyncio.run(agent_run_list(limit=3))

    assert len(runs) == 3


def test_agent_run_list_newest_first(tmp_db):
    """list() en yeni run önce gelir (created_at DESC)."""
    run1 = _create_run(tmp_db, agent_type="older")
    time.sleep(0.01)
    run2 = _create_run(tmp_db, agent_type="newer")

    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_list
        runs = asyncio.run(agent_run_list())

    assert runs[0]["id"] == run2
    assert runs[1]["id"] == run1


def test_agent_run_prompt_and_sender_stored(tmp_db):
    """prompt ve sender alanları doğru saklanır."""
    run_id = _create_run(
        tmp_db,
        prompt="Test görevi çalıştır",
        sender="905001234567",
        source="whatsapp",
    )
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.agent_run_repo import agent_run_get
        run = asyncio.run(agent_run_get(run_id))

    assert run["prompt"] == "Test görevi çalıştır"
    assert run["sender"] == "905001234567"
    assert run["source"] == "whatsapp"
