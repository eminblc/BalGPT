"""RateLimiter — sliding window testleri."""
import time
import pytest
from unittest.mock import patch
from backend.guards.rate_limiter import RateLimiter


def test_allows_within_limit():
    rl = RateLimiter(max_per_minute=5)
    for _ in range(5):
        assert rl.check("user1") is True


def test_blocks_when_limit_exceeded():
    rl = RateLimiter(max_per_minute=3)
    for _ in range(3):
        rl.check("user1")
    assert rl.check("user1") is False


def test_different_users_independent():
    rl = RateLimiter(max_per_minute=2)
    rl.check("user1")
    rl.check("user1")
    # user1 doldu, user2 etkilenmemeli
    assert rl.check("user2") is True


def test_window_slides_after_60s():
    rl = RateLimiter(max_per_minute=2)
    now = time.time()

    with patch("backend.guards.rate_limiter.time") as mock_time:
        mock_time.time.return_value = now
        rl.check("user1")
        rl.check("user1")
        assert rl.check("user1") is False  # limit doldu

        # 61 saniye ilerlet — pencere kayar
        mock_time.time.return_value = now + 61
        assert rl.check("user1") is True


def test_cleanup_removes_stale_entries():
    rl = RateLimiter(max_per_minute=10)
    now = time.time()

    with patch("backend.guards.rate_limiter.time") as mock_time:
        mock_time.time.return_value = now
        rl.check("stale_user")

        # TTL + cleanup interval kadar ilerlet
        future = now + RateLimiter._CLEANUP_INTERVAL + RateLimiter._ENTRY_TTL + 1
        mock_time.time.return_value = future
        rl.check("trigger_cleanup")  # cleanup'ı tetikle

    assert "stale_user" not in rl._windows
