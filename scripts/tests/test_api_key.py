"""require_api_key FastAPI dependency testleri.

FastAPI'nin test client'ı olmadan, dependency fonksiyonunu doğrudan çağırarak test eder.
"""
import pytest
from unittest.mock import patch, MagicMock
from fastapi import HTTPException


async def _call_require_api_key(x_api_key: str | None):
    from backend.guards.api_key import require_api_key
    return await require_api_key(x_api_key=x_api_key)


# ── api_key tanımlı değil ─────────────────────────────────────────

async def test_no_api_key_configured_dev_mode_passes():
    """api_key boş + environment != production → geçmeli (dev modu)."""
    with patch("backend.guards.api_key.settings") as s:
        s.api_key = None
        s.environment = "development"
        # Hata fırlatmamalı
        await _call_require_api_key(None)


async def test_no_api_key_configured_production_raises_500():
    """api_key boş + production → 500 InternalServerError."""
    with patch("backend.guards.api_key.settings") as s:
        s.api_key = None
        s.environment = "production"
        with pytest.raises(HTTPException) as exc_info:
            await _call_require_api_key(None)
    assert exc_info.value.status_code == 500


# ── api_key tanımlı ───────────────────────────────────────────────

def _settings_with_key(key: str):
    s = MagicMock()
    mock_secret = MagicMock()
    mock_secret.get_secret_value.return_value = key
    s.api_key = mock_secret
    s.environment = "development"
    return s


async def test_correct_api_key_passes():
    with patch("backend.guards.api_key.settings", _settings_with_key("secret-key-123")):
        await _call_require_api_key("secret-key-123")


async def test_wrong_api_key_raises_401():
    with patch("backend.guards.api_key.settings", _settings_with_key("secret-key-123")):
        with pytest.raises(HTTPException) as exc_info:
            await _call_require_api_key("wrong-key")
    assert exc_info.value.status_code == 401


async def test_missing_api_key_header_raises_401():
    with patch("backend.guards.api_key.settings", _settings_with_key("secret-key-123")):
        with pytest.raises(HTTPException) as exc_info:
            await _call_require_api_key(None)
    assert exc_info.value.status_code == 401


async def test_empty_api_key_header_raises_401():
    with patch("backend.guards.api_key.settings", _settings_with_key("secret-key-123")):
        with pytest.raises(HTTPException) as exc_info:
            await _call_require_api_key("")
    assert exc_info.value.status_code == 401
