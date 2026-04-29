"""sqlite_store — proje CRUD testleri (geçici DB ile)."""
import asyncio
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch


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
