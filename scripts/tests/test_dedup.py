"""DedupGuard — bellek içi dedup testleri (DB bağımlılığı yok)."""
import time
import pytest
from unittest.mock import patch
from backend.guards.deduplication import DedupGuard


@pytest.fixture
def dedup(monkeypatch):
    """DB olmadan sadece bellek içi DedupGuard."""
    monkeypatch.setattr(DedupGuard, "_load_from_db", lambda self: None)
    guard = DedupGuard(ttl=300.0, max_size=500)
    guard._db_available = False
    return guard


def test_new_message_not_duplicate(dedup):
    assert dedup.is_duplicate("msg-001") is False


def test_same_message_is_duplicate(dedup):
    dedup.is_duplicate("msg-002")
    assert dedup.is_duplicate("msg-002") is True


def test_different_messages_not_duplicate(dedup):
    dedup.is_duplicate("msg-003")
    assert dedup.is_duplicate("msg-004") is False


def test_eviction_after_ttl(dedup):
    now = time.time()
    with patch("backend.guards.deduplication.time") as mock_time:
        mock_time.time.return_value = now
        dedup.is_duplicate("msg-evict")

        # TTL sonrası mesaj bellekten silinmeli
        mock_time.time.return_value = now + dedup._ttl + 1
        assert dedup.is_duplicate("msg-evict") is False


def test_max_size_evicts_oldest(dedup):
    dedup._max = 3
    dedup.is_duplicate("a")
    dedup.is_duplicate("b")
    dedup.is_duplicate("c")
    # 4. ekleme en eskiyi (a) siler
    dedup.is_duplicate("d")
    assert "a" not in dedup._seen
    assert "d" in dedup._seen


def test_empty_message_id(dedup):
    # Boş string kabul edilmeli ama duplicate sayılmamalı (ilk kez)
    assert dedup.is_duplicate("") is False
    assert dedup.is_duplicate("") is True
