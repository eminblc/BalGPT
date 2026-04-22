"""Konuşma geçmişi feature testleri.

BUG-C1 regresyonu dahil: `import time` eksikliği `end_session()`'da NameError'a
yol açıyordu — bu test o hatanın bir daha çıkmamasını garanti eder.
"""
import pytest
from unittest.mock import MagicMock, patch


# ── BUG-C1 regresyon testi ────────────────────────────────────────

def test_end_session_no_name_error():
    """end_session() çağrısı NameError fırlatmamalı (BUG-C1: import time eksikti)."""
    # save_session_summary, history.py'de modül seviyesinde import edildiğinden
    # backend.features.history.save_session_summary adresiyle patch'lenir.
    with patch("backend.features.history.save_session_summary") as mock_save:
        from backend.features.history import end_session

        session = {
            "started_at": 1_000_000.0,
            "active_context": "main",
        }

        # Hata fırlatmamalı
        end_session("+905300000000", session)

    mock_save.assert_called_once()


def test_end_session_uses_session_started_at():
    """end_session, session'daki started_at değerini kullanır."""
    import time

    captured = {}

    def fake_save(sender, context_id, started_at, ended_at):
        captured["started_at"] = started_at
        captured["context_id"] = context_id

    with patch("backend.features.history.save_session_summary", side_effect=fake_save):
        from backend.features.history import end_session

        ts = time.time() - 3600
        end_session("+905300000000", {"started_at": ts, "active_context": "project:test"})

    assert captured["started_at"] == ts
    assert captured["context_id"] == "project:test"


# ── get_session_summaries ─────────────────────────────────────────

async def test_get_session_summaries_returns_list():
    """get_session_summaries → DB'den özet listesi döner."""
    fake_summaries = [
        {"id": "s1", "context_id": "main", "msg_count": 5},
        {"id": "s2", "context_id": "project:test", "msg_count": 12},
    ]

    with patch("backend.store.sqlite_store.session_summaries_list",
               return_value=fake_summaries) as mock_db:
        # session_summaries_list async mi sync mi kontrol et
        import asyncio
        import inspect
        if inspect.iscoroutinefunction(mock_db):
            pass
        # AsyncMock ile değiştir
        from unittest.mock import AsyncMock
        with patch("backend.store.sqlite_store.session_summaries_list",
                   AsyncMock(return_value=fake_summaries)):
            from backend.features.history import get_session_summaries
            result = await get_session_summaries("+905300000000", limit=10)

    assert len(result) == 2
    assert result[0]["context_id"] == "main"
