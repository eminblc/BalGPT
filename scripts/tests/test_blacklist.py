"""BlacklistManager testleri."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch


@pytest.fixture
def bl_manager(tmp_path):
    """Her test için temiz bir BlacklistManager örneği (geçici dosya yolu ile)."""
    bl_file = tmp_path / "blacklist.json"
    with patch("backend.guards.blacklist._BLACKLIST_FILE", bl_file):
        from importlib import import_module, reload
        import backend.guards.blacklist as mod
        # Dosya yokken başlat
        mgr = mod.BlacklistManager()
        yield mgr, bl_file


def test_empty_blacklist_not_blocked(bl_manager):
    mgr, _ = bl_manager
    assert mgr.is_blocked("905001234567") is False


def test_add_blocks_number(bl_manager):
    import asyncio
    mgr, _ = bl_manager
    asyncio.run(mgr.add("905001234567"))
    assert mgr.is_blocked("905001234567") is True


def test_add_persists_to_file(bl_manager):
    import asyncio
    mgr, bl_file = bl_manager
    asyncio.run(mgr.add("905001234567", "test reason"))
    data = json.loads(bl_file.read_text())
    numbers = [e["number"] for e in data]
    assert "905001234567" in numbers


def test_remove_unblocks_number(bl_manager):
    import asyncio
    mgr, _ = bl_manager
    asyncio.run(mgr.add("905001234567"))
    mgr.remove("905001234567")
    assert mgr.is_blocked("905001234567") is False


def test_remove_nonexistent_no_error(bl_manager):
    mgr, _ = bl_manager
    mgr.remove("905009999999")  # exception fırlatmamalı
    assert mgr.is_blocked("905009999999") is False


def test_add_multiple_numbers(bl_manager):
    import asyncio
    mgr, _ = bl_manager
    asyncio.run(mgr.add("111"))
    asyncio.run(mgr.add("222"))
    assert mgr.is_blocked("111") is True
    assert mgr.is_blocked("222") is True
    assert mgr.is_blocked("333") is False


def test_load_existing_file(tmp_path):
    """Mevcut blacklist.json dosyasından yükleme."""
    bl_file = tmp_path / "blacklist.json"
    bl_file.write_text(
        json.dumps([{"number": "905001111111"}, {"number": "905002222222"}]),
        encoding="utf-8",
    )
    with patch("backend.guards.blacklist._BLACKLIST_FILE", bl_file):
        from backend.guards.blacklist import BlacklistManager
        mgr = BlacklistManager()
    assert mgr.is_blocked("905001111111") is True
    assert mgr.is_blocked("905002222222") is True
    assert mgr.is_blocked("905003333333") is False


def test_load_corrupt_json_resets(tmp_path):
    """Bozuk JSON → boş liste ile devam etmeli."""
    bl_file = tmp_path / "blacklist.json"
    bl_file.write_text("invalid json !!!", encoding="utf-8")
    with patch("backend.guards.blacklist._BLACKLIST_FILE", bl_file):
        from backend.guards.blacklist import BlacklistManager
        mgr = BlacklistManager()
    assert mgr.is_blocked("905001234567") is False


def test_load_missing_file(tmp_path):
    """Dosya yoksa boş liste ile başlamalı."""
    bl_file = tmp_path / "nonexistent.json"
    with patch("backend.guards.blacklist._BLACKLIST_FILE", bl_file):
        from backend.guards.blacklist import BlacklistManager
        mgr = BlacklistManager()
    assert mgr.is_blocked("905001234567") is False
