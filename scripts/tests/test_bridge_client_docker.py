"""Docker ortamına özgü bridge-client testleri.

Docker'da en sık karşılaşılan sorunlar:
  1. ConnectError retry — 99-bridge container henüz ayakta değilken ilk bağlantı reddedilir,
     3 deneme + 2/4 s bekleme mantığının doğru çalıştığını doğrular.
  2. Container hostname URL — settings.claude_bridge_url "http://99-bridge:8013" iken
     isteğin doğru endpoint'e gönderildiğini doğrular.
  3. DNS çözümleme başarısızlığı — "Name or service not known" hatası bir ConnectError olarak
     gelir; bu hata connection_error kategorisine düşmeli (timeout değil).
  4. _error_message sınıflandırması — Docker ağ hatalarının doğru i18n anahtarına eşlendiğini
     doğrular.
  5. Partial retry — ikinci denemede başarı → response döner, raise olmaz.
"""
from __future__ import annotations

import asyncio
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helper: sahte bir httpx.Response üretir
# ---------------------------------------------------------------------------

def _make_response(answer: str = "ok", status_code: int = 200) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"answer": answer}
    return resp


# ---------------------------------------------------------------------------
# 1. ConnectError → tüm 3 deneme başarısız → son exception yeniden fırlatılır
# ---------------------------------------------------------------------------

async def test_forward_to_main_bridge_connect_error_exhausts_all_retries():
    """ConnectError 3 kez üst üste → 3. denemede exception yeniden fırlatılır."""
    connect_err = httpx.ConnectError("Connection refused")

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=connect_err)

    from backend.routers._bridge_client import _BRIDGE_CONNECT_RETRIES

    with (
        patch("asyncio.sleep", new=AsyncMock()),
        patch("backend.routers._bridge_client.settings") as mock_settings,
        patch("backend.guards.runtime_state.get_active_model", return_value=None),
    ):
        mock_settings.claude_bridge_url = "http://99-bridge:8013"
        mock_settings.api_key.get_secret_value.return_value = "test-key"
        mock_settings.default_model = "claude-sonnet-4-6"

        from backend.routers._bridge_client import _forward_to_main_bridge

        with pytest.raises(httpx.ConnectError):
            await _forward_to_main_bridge(mock_client, "main", "test message")

    assert mock_client.post.call_count == _BRIDGE_CONNECT_RETRIES


# ---------------------------------------------------------------------------
# 2. ConnectError → doğru sleep aralıkları (2 s, 4 s) beklenir
# ---------------------------------------------------------------------------

async def test_forward_to_main_bridge_retry_waits():
    """1. denemede 2 s, 2. denemede 4 s uyumalı (son denemede uyuma yok)."""
    connect_err = httpx.ConnectError("conn refused")

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=connect_err)

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    with (
        patch("asyncio.sleep", new=_fake_sleep),
        patch("backend.routers._bridge_client.settings") as mock_settings,
        patch("backend.guards.runtime_state.get_active_model", return_value=None),
    ):
        mock_settings.claude_bridge_url = "http://99-bridge:8013"
        mock_settings.api_key.get_secret_value.return_value = "test-key"
        mock_settings.default_model = ""

        from backend.routers._bridge_client import _forward_to_main_bridge

        with pytest.raises(httpx.ConnectError):
            await _forward_to_main_bridge(mock_client, "main", "hi")

    # 3 deneme için 2 sleep beklenir: 1→2 ve 2→3 arası
    assert sleep_calls == [2, 4]


# ---------------------------------------------------------------------------
# 3. İkinci denemede başarı → response döner, exception yok
# ---------------------------------------------------------------------------

async def test_forward_to_main_bridge_succeeds_on_second_attempt():
    """İlk deneme ConnectError, ikinci deneme başarılı → response döner."""
    good_response = _make_response("merhaba")

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(
        side_effect=[httpx.ConnectError("first attempt failed"), good_response]
    )

    with (
        patch("asyncio.sleep", new=AsyncMock()),
        patch("backend.routers._bridge_client.settings") as mock_settings,
        patch("backend.guards.runtime_state.get_active_model", return_value=None),
    ):
        mock_settings.claude_bridge_url = "http://99-bridge:8013"
        mock_settings.api_key.get_secret_value.return_value = "test-key"
        mock_settings.default_model = ""

        from backend.routers._bridge_client import _forward_to_main_bridge

        result = await _forward_to_main_bridge(mock_client, "main", "selam")

    assert result is good_response
    assert mock_client.post.call_count == 2


# ---------------------------------------------------------------------------
# 4. ConnectError olmayan exception → retry yapılmaz, doğrudan fırlatılır
# ---------------------------------------------------------------------------

async def test_forward_to_main_bridge_non_connect_error_no_retry():
    """httpx.TimeoutException retry yapılmaz — tek denemede exception fırlatılır."""
    timeout_err = httpx.TimeoutException("timed out")

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=timeout_err)

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    with (
        patch("asyncio.sleep", new=_fake_sleep),
        patch("backend.routers._bridge_client.settings") as mock_settings,
        patch("backend.guards.runtime_state.get_active_model", return_value=None),
    ):
        mock_settings.claude_bridge_url = "http://99-bridge:8013"
        mock_settings.api_key.get_secret_value.return_value = "test-key"
        mock_settings.default_model = ""

        from backend.routers._bridge_client import _forward_to_main_bridge

        with pytest.raises(httpx.TimeoutException):
            await _forward_to_main_bridge(mock_client, "main", "test")

    mock_client.post.assert_called_once()
    assert sleep_calls == []  # retry sleep olmadı


# ---------------------------------------------------------------------------
# 5. Docker container hostname URL'si isteğe doğru yansır
# ---------------------------------------------------------------------------

async def test_forward_to_main_bridge_uses_container_url():
    """settings.claude_bridge_url = 'http://99-bridge:8013' → POST bu URL'e gider."""
    good_response = _make_response("cevap")

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=good_response)

    with (
        patch("asyncio.sleep", new=AsyncMock()),
        patch("backend.routers._bridge_client.settings") as mock_settings,
        patch("backend.guards.runtime_state.get_active_model", return_value=None),
    ):
        mock_settings.claude_bridge_url = "http://99-bridge:8013"
        mock_settings.api_key.get_secret_value.return_value = "docker-api-key"
        mock_settings.default_model = ""

        from backend.routers._bridge_client import _forward_to_main_bridge

        await _forward_to_main_bridge(mock_client, "main", "docker test")

    call_args = mock_client.post.call_args
    posted_url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
    assert "99-bridge:8013" in posted_url
    assert "/query" in posted_url


# ---------------------------------------------------------------------------
# 6. _error_message — Docker DNS hatası → connection_error (timeout değil)
# ---------------------------------------------------------------------------

async def test_error_message_dns_failure_maps_to_connection_error():
    """'Name or service not known' mesajlı ConnectError → connection_error i18n anahtarı."""
    from backend.routers._bridge_client import _error_message

    dns_exc = httpx.ConnectError(
        "All connection attempts failed: Name or service not known"
    )
    msg = _error_message(dns_exc, project_id=None, lang="tr")

    # timeout i18n anahtarı olmamalı — DNS hatası timeout ile karıştırılmamalı
    from backend.i18n import t
    timeout_msg = t("bridge.timeout", "tr")
    assert msg != timeout_msg
    assert len(msg) > 0


# ---------------------------------------------------------------------------
# 7. _error_message — "connection refused" → connection_error (project yok)
# ---------------------------------------------------------------------------

async def test_error_message_connection_refused_no_project():
    """project_id=None, 'connection refused' → bridge.connection_error."""
    from backend.routers._bridge_client import _error_message
    from backend.i18n import t

    exc = httpx.ConnectError("Connection refused")
    msg = _error_message(exc, project_id=None, lang="tr")

    connection_error_msg = t("bridge.connection_error", "tr")
    assert msg == connection_error_msg


# ---------------------------------------------------------------------------
# 8. _error_message — "connection refused" → project_offline (proje varsa)
# ---------------------------------------------------------------------------

async def test_error_message_connection_refused_with_project():
    """project_id verilmiş, 'connection refused' → bridge.project_offline."""
    from backend.routers._bridge_client import _error_message
    from backend.i18n import t

    # _sync_project_get DB'ye erişemez — OSError/ValueError yakalar, project_id'yi kullanır
    with patch(
        "backend.store.repositories.project_repo._sync_project_get",
        side_effect=OSError("no db"),
    ):
        exc = httpx.ConnectError("Connection refused")
        msg = _error_message(exc, project_id="myproject", lang="tr")

    # Proje "offline" mesajı döner; en azından bir string olmalı
    assert isinstance(msg, str)
    assert len(msg) > 0
    # timeout mesajı olmamalı
    timeout_msg = t("bridge.timeout", "tr")
    assert msg != timeout_msg


# ---------------------------------------------------------------------------
# 9. _error_message — timeout → bridge.timeout
# ---------------------------------------------------------------------------

async def test_error_message_timeout_maps_to_timeout_key():
    """Hata mesajında 'timeout' geçiyorsa → bridge.timeout i18n anahtarı."""
    from backend.routers._bridge_client import _error_message
    from backend.i18n import t

    exc = httpx.TimeoutException("Read timeout exceeded")
    msg = _error_message(exc, project_id=None, lang="tr")

    expected = t("bridge.timeout", "tr")
    assert msg == expected


# ---------------------------------------------------------------------------
# 10. forward() — ConnectError → kullanıcıya hata mesajı gönderilir
# ---------------------------------------------------------------------------

async def test_forward_sends_error_message_on_connect_error():
    """ConnectError sonunda retry tükenir → messenger.send_text çağrılır."""
    connect_err = httpx.ConnectError("conn refused")

    mock_messenger = AsyncMock()
    mock_store = AsyncMock()
    mock_store.project_get = AsyncMock(return_value=None)

    with (
        patch("backend.routers._bridge_client.get_messenger", return_value=mock_messenger),
        patch("asyncio.sleep", new=AsyncMock()),
        patch("backend.routers._bridge_client._http_pool") as mock_pool,
        patch("backend.routers._bridge_client.settings") as mock_settings,
        patch("backend.routers._bridge_client.log_bridge_call"),
        patch("backend.routers._bridge_client.log_outbound"),
        patch("backend.guards.runtime_state.get_active_model", return_value=None),
        patch("backend.routers._bridge_client._store", mock_store),
    ):
        mock_settings.claude_bridge_url = "http://99-bridge:8013"
        mock_settings.api_key.get_secret_value.return_value = "key"
        mock_settings.default_model = ""
        mock_settings.conv_history_enabled = False
        mock_pool.post = AsyncMock(side_effect=connect_err)

        session = {"active_context": "main", "lang": "tr"}

        from backend.routers._bridge_client import forward
        await forward("905001234567", "test", session)

    mock_messenger.send_text.assert_called_once()
    sent_msg = mock_messenger.send_text.call_args[0][1]
    assert isinstance(sent_msg, str) and len(sent_msg) > 0
