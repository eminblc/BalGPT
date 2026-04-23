"""Repository katmanı testleri — geçici SQLite DB ile.

message_repo, plan_repo, project_repo, settings_repo, dedup_repo, event_repo, task_repo,
token_stat_repo
"""
import asyncio
import pytest
import time
from unittest.mock import patch


# ── Paylaşılan DB fixture ─────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    """Her test için temiz geçici SQLite DB; init_db çalıştırılmış."""
    db_file = tmp_path / "test_repo.db"
    with patch("backend.store._connection._resolve_db_path", return_value=db_file):
        from backend.store import sqlite_store
        sqlite_store.init_db()
        yield db_file


# ── plan_repo ─────────────────────────────────────────────────────

def test_plan_create_and_get(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.plan_repo import plan_create, plan_get
        plan = asyncio.run(plan_create("Test Görev", "Açıklama", 1))
    assert plan["title"] == "Test Görev"
    assert plan["priority"] == 1
    assert plan["status"] == "active"

    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        fetched = asyncio.run(plan_get(plan["id"]))
    assert fetched is not None
    assert fetched["id"] == plan["id"]


def test_plan_get_nonexistent(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.plan_repo import plan_get
        result = asyncio.run(plan_get("nonexistent-id"))
    assert result is None


def test_plan_list_active(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.plan_repo import plan_create, plan_list
        asyncio.run(plan_create("A", priority=2))
        asyncio.run(plan_create("B", priority=1))
        plans = asyncio.run(plan_list("active"))
    assert len(plans) == 2
    # Priority 1 önce gelmeli
    assert plans[0]["title"] == "B"


def test_plan_complete(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.plan_repo import plan_create, plan_complete, plan_get
        plan = asyncio.run(plan_create("Tamamlanacak"))
        asyncio.run(plan_complete(plan["id"]))
        updated = asyncio.run(plan_get(plan["id"]))
    assert updated["status"] == "completed"
    assert updated["completed_at"] is not None


def test_plan_delete(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.plan_repo import plan_create, plan_delete, plan_get
        plan = asyncio.run(plan_create("Silinecek"))
        asyncio.run(plan_delete(plan["id"]))
        result = asyncio.run(plan_get(plan["id"]))
    assert result is None


def test_plan_list_completed_empty_when_none(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.plan_repo import plan_list
        plans = asyncio.run(plan_list("completed"))
    assert plans == []


def test_plan_with_due_date(tmp_db):
    ts = time.time() + 3600
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.plan_repo import plan_create, plan_get
        plan = asyncio.run(plan_create("Due Date Plan", due_date=ts))
        fetched = asyncio.run(plan_get(plan["id"]))
    assert abs(fetched["due_date"] - ts) < 1


# ── settings_repo ─────────────────────────────────────────────────

def test_setting_set_and_get(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.settings_repo import user_setting_set, user_setting_get
        asyncio.run(user_setting_set("905001234567", "lang", "en"))
        value = asyncio.run(user_setting_get("905001234567", "lang"))
    assert value == "en"


def test_setting_default_for_missing(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.settings_repo import user_setting_get
        value = asyncio.run(user_setting_get("905001234567", "missing_key", "default_val"))
    assert value == "default_val"


def test_setting_upsert(tmp_db):
    """Aynı key için iki kez set → son değer kazanmalı."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.settings_repo import user_setting_set, user_setting_get
        asyncio.run(user_setting_set("905001234567", "lang", "tr"))
        asyncio.run(user_setting_set("905001234567", "lang", "en"))
        value = asyncio.run(user_setting_get("905001234567", "lang"))
    assert value == "en"


def test_setting_get_all(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.settings_repo import (
            user_setting_set, user_settings_get_all,
        )
        asyncio.run(user_setting_set("905001234567", "lang", "tr"))
        asyncio.run(user_setting_set("905001234567", "model", "claude-sonnet-4-6"))
        all_settings = asyncio.run(user_settings_get_all("905001234567"))
    assert all_settings["lang"] == "tr"
    assert all_settings["model"] == "claude-sonnet-4-6"


def test_setting_delete(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.settings_repo import (
            user_setting_set, user_setting_get, user_setting_delete,
        )
        asyncio.run(user_setting_set("905001234567", "lang", "en"))
        asyncio.run(user_setting_delete("905001234567", "lang"))
        value = asyncio.run(user_setting_get("905001234567", "lang"))
    assert value is None


def test_setting_isolated_per_sender(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.settings_repo import (
            user_setting_set, user_setting_get,
        )
        asyncio.run(user_setting_set("111", "lang", "tr"))
        asyncio.run(user_setting_set("222", "lang", "en"))
        assert asyncio.run(user_setting_get("111", "lang")) == "tr"
        assert asyncio.run(user_setting_get("222", "lang")) == "en"


# ── message_repo ──────────────────────────────────────────────────

def test_message_log_and_list(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.message_repo import message_log, message_list
        asyncio.run(message_log("msg-001", "inbound", "905001234567", "text", "merhaba"))
        messages = asyncio.run(message_list("905001234567"))
    assert len(messages) == 1
    assert messages[0]["content"] == "merhaba"
    assert messages[0]["direction"] == "inbound"


def test_message_log_dedup_on_id(tmp_db):
    """Aynı msg_id iki kez → sadece bir kayıt (INSERT OR IGNORE)."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.message_repo import message_log, message_count
        asyncio.run(message_log("msg-dup", "inbound", "905001234567", "text", "a"))
        asyncio.run(message_log("msg-dup", "inbound", "905001234567", "text", "b"))
        count = asyncio.run(message_count("905001234567"))
    assert count == 1


def test_message_list_limit(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.message_repo import message_log, message_list
        for i in range(5):
            asyncio.run(message_log(f"msg-{i}", "inbound", "905001234567", "text", f"msg{i}"))
        messages = asyncio.run(message_list("905001234567", limit=3))
    assert len(messages) == 3


def test_session_summary_save_and_list(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.message_repo import (
            session_summary_save, session_summaries_list,
        )
        now = time.time()
        asyncio.run(session_summary_save("905001234567", "main", now - 100, now, 5, "Test özeti"))
        summaries = asyncio.run(session_summaries_list("905001234567"))
    assert len(summaries) == 1
    assert summaries[0]["summary"] == "Test özeti"
    assert summaries[0]["msg_count"] == 5


def test_bridge_call_log_and_list(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.message_repo import bridge_call_log, bridge_calls_list
        asyncio.run(bridge_call_log(
            "905001234567", "main", "test prompt", "test response", 150, True
        ))
        calls = asyncio.run(bridge_calls_list("905001234567"))
    assert len(calls) == 1
    assert calls[0]["prompt"] == "test prompt"
    assert calls[0]["latency_ms"] == 150


# ── project_repo ──────────────────────────────────────────────────

def test_project_create_and_get(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.project_repo import project_create, project_get
        proj = asyncio.run(project_create("Test Proje", "Açıklama", path="/tmp/test-proje"))
    assert proj["id"] == "test-proje"
    assert proj["name"] == "Test Proje"

    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        fetched = asyncio.run(project_get("test-proje"))
    assert fetched["name"] == "Test Proje"


def test_project_get_nonexistent(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.project_repo import project_get
        result = asyncio.run(project_get("no-such-project"))
    assert result is None


def test_project_list(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.project_repo import project_create, project_list
        asyncio.run(project_create("Proje A", path="/tmp/proje-a"))
        asyncio.run(project_create("Proje B", path="/tmp/proje-b"))
        projects = asyncio.run(project_list())
    assert len(projects) == 2


def test_project_duplicate_raises(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.project_repo import project_create
        asyncio.run(project_create("Dup Proje", path="/tmp/dup-proje"))
        with pytest.raises(ValueError, match="zaten mevcut"):
            asyncio.run(project_create("Dup Proje", path="/tmp/dup-proje"))


def test_project_delete(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.project_repo import project_create, project_delete, project_get
        asyncio.run(project_create("Silinecek", path="/tmp/silinecek"))
        deleted = asyncio.run(project_delete("silinecek"))
        result = asyncio.run(project_get("silinecek"))
    assert deleted is True
    assert result is None


def test_project_delete_nonexistent(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.project_repo import project_delete
        result = asyncio.run(project_delete("ghost-project"))
    assert result is False


def test_project_update_status(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories.project_repo import (
            project_create, project_update_status, project_get,
        )
        asyncio.run(project_create("Status Proje", path="/tmp/status-proje"))
        asyncio.run(project_update_status("status-proje", "archived"))
        proj = asyncio.run(project_get("status-proje"))
    assert proj["status"] == "archived"


# ── slugify_project_name ──────────────────────────────────────────

def test_slugify_turkish_chars():
    from backend.store.repositories.project_repo import slugify_project_name
    assert slugify_project_name("Müzik API") == "muzik-api"
    assert slugify_project_name("Şehir Planı") == "sehir-plani"
    assert slugify_project_name("İstanbul") == "istanbul"


def test_slugify_special_chars():
    from backend.store.repositories.project_repo import slugify_project_name
    assert slugify_project_name("Hello World!") == "hello-world"
    assert slugify_project_name("My App 2") == "my-app-2"


def test_slugify_empty_fallback():
    from backend.store.repositories.project_repo import slugify_project_name
    assert slugify_project_name("!!!") == "proje"


def test_slugify_multiple_dashes():
    from backend.store.repositories.project_repo import slugify_project_name
    result = slugify_project_name("Test  --  Project")
    assert "--" not in result
    assert result == "test-project"


# ── token_stat_repo ───────────────────────────────────────────────

def test_token_add_and_get_totals(tmp_db):
    """add_usage sonrası get_totals doğru toplamları döndürmeli."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories import token_stat_repo
        asyncio.run(token_stat_repo.add_usage(
            "claude-3-5-haiku-20241022", "Haiku 4.5", "anthropic",
            input_tokens=100, output_tokens=50,
        ))
        asyncio.run(token_stat_repo.add_usage(
            "claude-3-5-haiku-20241022", "Haiku 4.5", "anthropic",
            input_tokens=200, output_tokens=80,
        ))
        totals = asyncio.run(token_stat_repo.get_totals(24))

    assert totals["calls"] == 2
    assert totals["input_tokens"] == 300
    assert totals["output_tokens"] == 130
    assert totals["total_tokens"] == 430


def test_token_get_totals_empty(tmp_db):
    """Kayıt yokken get_totals calls=0 dönmeli."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories import token_stat_repo
        totals = asyncio.run(token_stat_repo.get_totals(24))

    assert totals.get("calls") in (0, None)


def test_token_get_summary_groups_by_model(tmp_db):
    """Farklı modeller için get_summary ayrı satırlar döndürmeli."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories import token_stat_repo
        asyncio.run(token_stat_repo.add_usage(
            "claude-3-5-haiku-20241022", "Haiku 4.5", "anthropic", 100, 40,
        ))
        asyncio.run(token_stat_repo.add_usage(
            "claude-3-5-haiku-20241022", "Haiku 4.5", "anthropic", 50, 20,
        ))
        asyncio.run(token_stat_repo.add_usage(
            "gemini-2.0-flash", "Gemini 2.0 Flash", "gemini", 300, 100,
        ))
        summary = asyncio.run(token_stat_repo.get_summary(24))

    model_names = {r["model_name"] for r in summary}
    assert "Haiku 4.5" in model_names
    assert "Gemini 2.0 Flash" in model_names

    haiku = next(r for r in summary if r["model_name"] == "Haiku 4.5")
    assert haiku["calls"] == 2
    assert haiku["input_tokens"] == 150
    assert haiku["output_tokens"] == 60


def test_token_get_summary_empty(tmp_db):
    """Kayıt yokken get_summary boş liste döndürmeli."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories import token_stat_repo
        summary = asyncio.run(token_stat_repo.get_summary(24))

    assert summary == []


def test_token_total_tokens_stored_correctly(tmp_db):
    """total_tokens = input_tokens + output_tokens olarak saklanmalı."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories import token_stat_repo
        import sqlite3
        asyncio.run(token_stat_repo.add_usage(
            "llama3", "Ollama/llama3", "ollama", 111, 222,
        ))
        with sqlite3.connect(tmp_db) as con:
            row = con.execute(
                "SELECT input_tokens, output_tokens, total_tokens FROM token_usage LIMIT 1"
            ).fetchone()

    assert row[0] == 111
    assert row[1] == 222
    assert row[2] == 333


def test_token_context_field_stored(tmp_db):
    """context alanı doğru saklanmalı."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories import token_stat_repo
        import sqlite3
        asyncio.run(token_stat_repo.add_usage(
            "claude-3-5-haiku-20241022", "Haiku 4.5", "anthropic", 10, 5,
            context="intent_classifier",
        ))
        with sqlite3.connect(tmp_db) as con:
            row = con.execute("SELECT context FROM token_usage LIMIT 1").fetchone()

    assert row[0] == "intent_classifier"


def test_token_session_id_optional(tmp_db):
    """session_id None olarak geçilebilmeli."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories import token_stat_repo
        asyncio.run(token_stat_repo.add_usage(
            "claude-3-5-haiku-20241022", "Haiku 4.5", "anthropic", 5, 2,
            session_id=None,
        ))
        totals = asyncio.run(token_stat_repo.get_totals(24))

    assert totals["calls"] == 1


def test_token_timespan_filters_old_entries(tmp_db):
    """Zaman aralığı dışındaki kayıtlar get_totals'a dahil edilmemeli."""
    import sqlite3, time
    from datetime import datetime, timezone, timedelta

    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.repositories import token_stat_repo

        # Şimdiki kayıt
        asyncio.run(token_stat_repo.add_usage(
            "claude-3-5-haiku-20241022", "Haiku 4.5", "anthropic", 100, 50,
        ))
        # 25 saat öncesine ait sahte kayıt
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        with sqlite3.connect(tmp_db) as con:
            con.execute(
                """INSERT INTO token_usage
                   (id, timestamp, model_id, model_name, backend,
                    input_tokens, output_tokens, total_tokens, context)
                   VALUES ('old-id', ?, 'claude-3-5-haiku-20241022', 'Haiku 4.5',
                           'anthropic', 500, 200, 700, 'bridge_query')""",
                (old_ts,),
            )
        # 24 saatlik pencerede yalnızca güncel kayıt görünmeli
        totals = asyncio.run(token_stat_repo.get_totals(24))

    assert totals["calls"] == 1
    assert totals["input_tokens"] == 100
