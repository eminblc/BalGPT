"""Credential store feature testleri — get_credential ve list_credentials."""
import pytest
from unittest.mock import patch, MagicMock


# ── get_credential ────────────────────────────────────────────────

def test_get_credential_found_returns_true_and_value():
    """Tanımlı credential → (True, mesaj, değer) döner."""
    mock_settings = MagicMock()
    mock_settings.get_site_credential.return_value = "kullanici123"
    mock_settings.list_site_credentials.return_value = []

    with patch("backend.features.credential_store.settings", mock_settings):
        from backend.features.credential_store import get_credential

        ok, msg, value = get_credential("mercek_itu", "user")

    assert ok is True
    assert value == "kullanici123"
    assert "mercek_itu" in msg
    mock_settings.get_site_credential.assert_called_once_with("mercek_itu", "user")


def test_get_credential_not_found_returns_false():
    """Tanımsız credential → (False, hata mesajı, None) döner."""
    mock_settings = MagicMock()
    mock_settings.get_site_credential.return_value = None

    with patch("backend.features.credential_store.settings", mock_settings):
        from backend.features.credential_store import get_credential

        ok, msg, value = get_credential("bilinmeyen_site", "pass")

    assert ok is False
    assert value is None
    assert "bilinmeyen_site" in msg


def test_get_credential_secret_field_not_logged():
    """Şifre alanları logunun görünür değeri '***' olmalı (log maskeleme)."""
    mock_settings = MagicMock()
    mock_settings.get_site_credential.return_value = "gizli-sifre-123"

    with patch("backend.features.credential_store.settings", mock_settings), \
         patch("backend.features.credential_store.logger") as mock_logger:
        from backend.features.credential_store import get_credential

        ok, _, value = get_credential("site_x", "password")

    # Gerçek şifre loga yazılmamalı
    log_calls = str(mock_logger.info.call_args_list)
    assert "gizli-sifre-123" not in log_calls
    assert ok is True
    assert value == "gizli-sifre-123"


# ── list_credentials ──────────────────────────────────────────────

def test_list_credentials_returns_slugs():
    """list_credentials → tanımlı site slug listesini döner."""
    mock_settings = MagicMock()
    mock_settings.list_site_credentials.return_value = ["mercek_itu", "gmail", "github"]

    with patch("backend.features.credential_store.settings", mock_settings):
        from backend.features.credential_store import list_credentials

        result = list_credentials()

    assert result == ["mercek_itu", "gmail", "github"]
    mock_settings.list_site_credentials.assert_called_once()
