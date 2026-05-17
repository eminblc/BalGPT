"""sqlite_store — proje CRUD testleri (geçici DB ile)."""
import asyncio
import sqlite3
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock


@pytest.fixture
def tmp_db(tmp_path):
    """Her test için yeni bir geçici SQLite DB döner."""
    db_file = tmp_path / "test.db"
    # _conn() artık _connection.py'deki _resolve_db_path'ı çağırır
    with patch("backend.store._connection._resolve_db_path", return_value=db_file):
        from backend.store import sqlite_store
        sqlite_store.init_db()
        yield db_file


# ── slugify_project_name + _PROJECT_ID_RE entegrasyonu ────────────

def test_slugify_passes_regex(tmp_db):
    from backend.store.sqlite_store import slugify_project_name, _PROJECT_ID_RE
    for name in ["Test Projesi", "Müzik API", "hello world", "My App 2"]:
        slug = slugify_project_name(name)
        assert _PROJECT_ID_RE.match(slug), f"'{slug}' regex'e uymadı (kaynak: '{name}')"


# ── Proje oluşturma ────────────────────────────────────────────────

def test_project_create_and_get(tmp_db):
    from backend.store import sqlite_store
    sqlite_store.init_db()

    project = asyncio.run(_create("Test Projesi", tmp_db))
    assert project["name"] == "Test Projesi"
    assert project["id"] == "test-projesi"
    assert project["description"] == "Açıklama"

    fetched = asyncio.run(_get("test-projesi", tmp_db))
    assert fetched is not None
    assert fetched["id"] == "test-projesi"


def test_project_create_turkish(tmp_db):
    project = asyncio.run(_create("Müzik API", tmp_db))
    assert project["id"] == "muzik-api"


def test_project_duplicate_raises(tmp_db):
    asyncio.run(_create("Duplicate Proje", tmp_db))
    with pytest.raises(ValueError, match="zaten mevcut"):
        asyncio.run(_create("Duplicate Proje", tmp_db))


def test_project_list(tmp_db):
    asyncio.run(_create("Proje A", tmp_db))
    asyncio.run(_create("Proje B", tmp_db))
    projects = asyncio.run(_list(tmp_db))
    ids = [p["id"] for p in projects]
    assert "proje-a" in ids
    assert "proje-b" in ids


def test_project_create_custom_path(tmp_db, tmp_path):
    custom = str(tmp_path / "ozel-yol")
    project = asyncio.run(_create("Ozel Yol", tmp_db, path=custom))
    assert project["path"] == custom


# ── Yardımcı async wrapperlar ─────────────────────────────────────

async def _create(name, tmp_db, path=None):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.sqlite_store import project_create
        return await project_create(name, "Açıklama", path=path)


async def _get(project_id, tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.sqlite_store import project_get
        return await project_get(project_id)


async def _list(tmp_db):
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.sqlite_store import project_list
        return await project_list()


# ── SEC-SCAN2-S1 — Whitelist doğrulaması ─────────────────────────

def test_migration_columns_are_valid_identifiers():
    """_MIGRATE_SCHEDULED_TASKS_COLUMNS key'leri geçerli Python identifier olmalı (SQL injection yok)."""
    from backend.store.sqlite_store import _MIGRATE_SCHEDULED_TASKS_COLUMNS
    for col in _MIGRATE_SCHEDULED_TASKS_COLUMNS:
        assert col.isidentifier(), (
            f"'{col}' geçerli bir Python identifier değil — potansiyel SQL injection riski"
        )


def test_migration_columns_no_sql_injection_patterns():
    """Whitelist key'leri SQL injection karakterleri içermemeli."""
    from backend.store.sqlite_store import _MIGRATE_SCHEDULED_TASKS_COLUMNS
    dangerous_patterns = [";", "--", " ", "'", '"', "/*", "*/", "DROP", "ALTER", "INSERT"]
    for col in _MIGRATE_SCHEDULED_TASKS_COLUMNS:
        for pattern in dangerous_patterns:
            assert pattern.lower() not in col.lower(), (
                f"'{col}' şüpheli pattern içeriyor: '{pattern}'"
            )


def test_migration_adds_expected_columns(tmp_db):
    """Migration sonrası beklenen kolonlar scheduled_tasks tablosunda mevcut olmalı."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store.sqlite_store import _MIGRATE_SCHEDULED_TASKS_COLUMNS, init_db_migrations
        init_db_migrations()

        # DB'deki mevcut kolonları kontrol et
        with sqlite3.connect(str(tmp_db)) as con:
            cursor = con.execute("PRAGMA table_info(scheduled_tasks)")
            existing_cols = {row[1] for row in cursor.fetchall()}

        for col in _MIGRATE_SCHEDULED_TASKS_COLUMNS:
            assert col in existing_cols, (
                f"Migration sonrası '{col}' kolonu scheduled_tasks'ta bulunamadı"
            )


# ── SEC-SCAN2-S6 — OperationalError handling ──────────────────────

def test_migrate_already_exists_error_is_silenced():
    """'already exists' içeren OperationalError sessizce geçilmeli — hata fırlatılmamalı.

    Mock ile test edilir çünkü SQLite gerçekte 'duplicate column name' döndürür;
    üretim kodunun 'already exists' guard'ı bu tam string için tasarlanmıştır.
    """
    from backend.store import sqlite_store

    mock_con = MagicMock()
    mock_con.execute.side_effect = sqlite3.OperationalError("table t: already exists")

    # 'already exists' içeren hata sessizce geçilmeli
    sqlite_store._migrate_scheduled_tasks(mock_con)  # hata fırlatmamalı


def test_migrate_unexpected_operational_error_is_reraised(tmp_db):
    """'already exists' dışındaki OperationalError yeniden fırlatılmalı."""
    with patch("backend.store._connection._resolve_db_path", return_value=tmp_db):
        from backend.store import sqlite_store
        from backend.store._connection import _conn

        unexpected_error = sqlite3.OperationalError("disk I/O error")

        mock_con = MagicMock()
        mock_con.execute.side_effect = unexpected_error

        with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
            sqlite_store._migrate_scheduled_tasks(mock_con)
