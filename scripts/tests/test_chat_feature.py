"""Chat feature — send_to_bridge ve reset_bridge_session testleri.

httpx çağrıları mock'lanır; gerçek Bridge bağlantısı yapılmaz.
"""
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch


# ── send_to_bridge — happy path ───────────────────────────────────

async def test_send_to_bridge_returns_answer():
    """Başarılı Bridge yanıtı → answer string döner."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"answer": "Merhaba!"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from backend.features.chat import send_to_bridge
        result = await send_to_bridge("sess-1", "Merhaba")

    assert result == "Merhaba!"


async def test_send_to_bridge_empty_answer():
    """answer alanı yoksa boş string döner."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {}  # 'answer' yok

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from backend.features.chat import send_to_bridge
        result = await send_to_bridge("sess-2", "test")

    assert result == ""


# ── send_to_bridge — API error ────────────────────────────────────

async def test_send_to_bridge_api_error_returns_i18n():
    """CLI'den 'API Error:' ile başlayan yanıt → i18n hata mesajı döner."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"answer": "API Error: rate_limit_exceeded"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from backend.features.chat import send_to_bridge
        result = await send_to_bridge("sess-3", "test", lang="tr")

    # i18n key chat.bridge_api_error → ham "API Error:" stringi DÖNMEMELI
    assert not result.startswith("API Error:")
    assert len(result) > 0


# ── send_to_bridge — timeout ──────────────────────────────────────

async def test_send_to_bridge_timeout_returns_i18n():
    """httpx.TimeoutException → i18n timeout mesajı döner, exception yutulur."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from backend.features.chat import send_to_bridge
        result = await send_to_bridge("sess-4", "test", lang="tr")

    assert isinstance(result, str)
    assert len(result) > 0


# ── send_to_bridge — generic exception ───────────────────────────

async def test_send_to_bridge_exception_returns_i18n():
    """Genel exception → i18n 'bridge unavailable' mesajı döner."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=ConnectionRefusedError("refused"))

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from backend.features.chat import send_to_bridge
        result = await send_to_bridge("sess-5", "test", lang="en")

    assert isinstance(result, str)
    assert len(result) > 0


# ── send_to_bridge — init_prompt iletilmesi ───────────────────────

async def test_send_to_bridge_passes_init_prompt():
    """init_prompt parametresi POST body'ye doğru aktarılmalı."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"answer": "ok"}

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from backend.features.chat import send_to_bridge
        await send_to_bridge("sess-6", "mesaj", init_prompt="Sen bir asistansın.")

    call_kwargs = mock_client.post.call_args
    body = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs[0][1]
    assert body["init_prompt"] == "Sen bir asistansın."
    assert body["session_id"] == "sess-6"
    assert body["message"] == "mesaj"


# ── reset_bridge_session — happy path ────────────────────────────

async def test_reset_bridge_session_returns_true():
    """Başarılı reset → True döner."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from backend.features.chat import reset_bridge_session
        result = await reset_bridge_session("sess-reset-1")

    assert result is True


# ── reset_bridge_session — hata ───────────────────────────────────

async def test_reset_bridge_session_exception_returns_false():
    """Herhangi bir exception → False döner, exception yutulur."""
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("conn refused"))

    with patch("httpx.AsyncClient") as mock_cls:
        mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        from backend.features.chat import reset_bridge_session
        result = await reset_bridge_session("sess-reset-2")

    assert result is False
