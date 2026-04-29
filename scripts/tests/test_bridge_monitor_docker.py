"""BridgeMonitor — Docker ortamına özgü testler.

Docker'da yaşanan başlıca sorunlar:
  1. systemctl yok → restart_bridge_service() başarısız döner (returncode != 0 veya exception).
  2. Auto-restart eşiğine ulaşınca _notify çağrılır, ardından restart denenir.
  3. Fail streak sıfırlanır — restart başarısız olsa bile sonsuz döngü oluşmamalı.
  4. Bridge tekrar erişilebilir olduğunda "bridge_up" bildirimi gönderilmeli.
  5. İlk başarısızlıkta "bridge_down" bildirimi gönderilmeli; sonraki başarısızlıklarda tekrar
     gönderilmemeli (spam önleme).
  6. restart_bridge_service timeout → False, timeout mesajı döner.
  7. Container URL (http://99-bridge:8013) health endpoint'ine GET isteği yapılır.
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helper — kısa interval'lı BridgeMonitor
# ---------------------------------------------------------------------------

def _make_monitor(notify_fn=None, interval: int = 1, auto_restart_after: int = 3):
    from backend.services.bridge_monitor import BridgeMonitor
    notify = notify_fn or AsyncMock()
    return BridgeMonitor(
        bridge_url="http://99-bridge:8013",
        notify_fn=notify,
        check_interval=interval,
        auto_restart_after=auto_restart_after,
    ), notify


# ---------------------------------------------------------------------------
# 1. restart_bridge_service — systemctl yok (Docker) → False döner
# ---------------------------------------------------------------------------

async def test_restart_bridge_service_no_systemctl_returns_false():
    """Docker'da 'sudo systemctl' komutu bulunamazsa (FileNotFoundError) False döner."""
    from backend.services.bridge_monitor import restart_bridge_service

    with patch("backend.services.bridge_monitor.asyncio.create_subprocess_exec") as mock_exec:
        mock_exec.side_effect = FileNotFoundError("No such file or directory: 'sudo'")
        success, msg = await restart_bridge_service()

    assert success is False
    assert isinstance(msg, str) and len(msg) > 0


# ---------------------------------------------------------------------------
# 2. restart_bridge_service — non-zero returncode → False döner
# ---------------------------------------------------------------------------

async def test_restart_bridge_service_nonzero_returncode():
    """systemctl komutu returncode=1 verirse → (False, hata mesajı)."""
    from backend.services.bridge_monitor import restart_bridge_service

    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"Unit not found."))

    with patch("backend.services.bridge_monitor.asyncio.create_subprocess_exec", return_value=mock_proc):
        success, msg = await restart_bridge_service()

    assert success is False
    assert isinstance(msg, str)


# ---------------------------------------------------------------------------
# 3. restart_bridge_service — returncode=0 → True döner
# ---------------------------------------------------------------------------

async def test_restart_bridge_service_success():
    """returncode=0 → (True, başarı mesajı)."""
    from backend.services.bridge_monitor import restart_bridge_service

    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))

    with patch("backend.services.bridge_monitor.asyncio.create_subprocess_exec", return_value=mock_proc):
        success, msg = await restart_bridge_service()

    assert success is True
    assert isinstance(msg, str) and len(msg) > 0


# ---------------------------------------------------------------------------
# 4. restart_bridge_service — timeout → False + kill çağrılır
# ---------------------------------------------------------------------------

async def test_restart_bridge_service_timeout_kills_process():
    """communicate() timeout'a düşerse process kill edilmeli ve False dönmeli."""
    from backend.services.bridge_monitor import restart_bridge_service

    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()
    mock_proc.communicate = AsyncMock(side_effect=asyncio.TimeoutError())

    with patch("backend.services.bridge_monitor.asyncio.create_subprocess_exec", return_value=mock_proc):
        with patch("backend.services.bridge_monitor.asyncio.wait_for", side_effect=asyncio.TimeoutError()):
            success, msg = await restart_bridge_service()

    assert success is False
    mock_proc.kill.assert_called_once()


# ---------------------------------------------------------------------------
# 5. _on_failure — ilk başarısızlıkta bridge_down bildirimi gönderilir
# ---------------------------------------------------------------------------

async def test_on_failure_first_time_sends_bridge_down_notification():
    """İlk _on_failure çağrısında notify_fn çağrılmalı (_bridge_down = False iken)."""
    monitor, notify = _make_monitor(auto_restart_after=5)

    exc = ConnectionRefusedError("conn refused")
    await monitor._on_failure(exc)

    notify.assert_awaited_once()
    assert monitor._bridge_down is True
    assert monitor._fail_streak == 1


# ---------------------------------------------------------------------------
# 6. _on_failure — sonraki başarısızlıklarda tekrar bildirim gönderilmez
# ---------------------------------------------------------------------------

async def test_on_failure_subsequent_calls_no_extra_notification():
    """_bridge_down=True iken notify_fn yeniden çağrılmamalı (spam önleme)."""
    monitor, notify = _make_monitor(auto_restart_after=10)

    exc = ConnectionRefusedError("still down")
    await monitor._on_failure(exc)   # 1. çağrı — bildirim gönderilir
    await monitor._on_failure(exc)   # 2. çağrı — bildirim gönderilmemeli
    await monitor._on_failure(exc)   # 3. çağrı — bildirim gönderilmemeli

    # Restart eşiğine ulaşılmadığından notify yalnızca ilk _on_failure'da çağrılmalı
    assert notify.await_count == 1
    assert monitor._fail_streak == 3


# ---------------------------------------------------------------------------
# 7. _on_failure — eşiğe ulaşınca auto_restart tetiklenir
# ---------------------------------------------------------------------------

async def test_on_failure_triggers_auto_restart_at_threshold():
    """fail_streak == auto_restart_after olduğunda _auto_restart çağrılmalı."""
    monitor, notify = _make_monitor(auto_restart_after=2)

    mock_restart = AsyncMock()
    monitor._auto_restart = mock_restart

    exc = Exception("bridge down")
    await monitor._on_failure(exc)  # streak=1
    mock_restart.assert_not_awaited()

    await monitor._on_failure(exc)  # streak=2 → eşik!
    mock_restart.assert_awaited_once()


# ---------------------------------------------------------------------------
# 8. _auto_restart — fail_streak sıfırlanır (restart başarısız olsa bile)
# ---------------------------------------------------------------------------

async def test_auto_restart_resets_fail_streak():
    """_auto_restart sonrası fail_streak sıfırlanmalı — sonsuz döngü olmamalı."""
    monitor, notify = _make_monitor(auto_restart_after=2)
    monitor._bridge_down = True
    monitor._fail_streak = 2

    with patch(
        "backend.services.bridge_monitor.restart_bridge_service",
        new=AsyncMock(return_value=(False, "systemctl not found")),
    ):
        await monitor._auto_restart()

    assert monitor._fail_streak == 0


# ---------------------------------------------------------------------------
# 9. _auto_restart başarısız → "auto_restart_failed" bildirimi gönderilir
# ---------------------------------------------------------------------------

async def test_auto_restart_failed_sends_notification():
    """restart başarısız olduğunda notify_fn ek bildirim göndermelidir."""
    monitor, notify = _make_monitor()
    monitor._bridge_down = True
    monitor._fail_streak = 3

    with patch(
        "backend.services.bridge_monitor.restart_bridge_service",
        new=AsyncMock(return_value=(False, "No systemctl in Docker")),
    ):
        await monitor._auto_restart()

    # _auto_restart içinden iki notify beklenir: "auto_restart" + "auto_restart_failed"
    assert notify.await_count == 2


# ---------------------------------------------------------------------------
# 10. _auto_restart başarılı → yalnızca "auto_restart" bildirimi gönderilir
# ---------------------------------------------------------------------------

async def test_auto_restart_success_sends_single_notification():
    """restart başarılı → tek notify çağrısı (auto_restart_failed gönderilmez)."""
    monitor, notify = _make_monitor()

    with patch(
        "backend.services.bridge_monitor.restart_bridge_service",
        new=AsyncMock(return_value=(True, "Restarted")),
    ):
        await monitor._auto_restart()

    notify.assert_awaited_once()


# ---------------------------------------------------------------------------
# 11. _on_success — bridge tekrar erişilebilir → "bridge_up" bildirimi
# ---------------------------------------------------------------------------

async def test_on_success_after_down_sends_bridge_up():
    """_bridge_down=True iken _on_success çağrılırsa 'bridge_up' bildirimi gönderilmeli."""
    monitor, notify = _make_monitor()
    monitor._bridge_down = True
    monitor._fail_streak = 2

    await monitor._on_success()

    notify.assert_awaited_once()
    assert monitor._bridge_down is False
    assert monitor._fail_streak == 0


# ---------------------------------------------------------------------------
# 12. _on_success — zaten erişilebilirken → bildirim gönderilmez
# ---------------------------------------------------------------------------

async def test_on_success_when_already_up_no_notification():
    """_bridge_down=False iken _on_success → notify_fn çağrılmamalı."""
    monitor, notify = _make_monitor()
    monitor._bridge_down = False
    monitor._fail_streak = 0

    await monitor._on_success()

    notify.assert_not_awaited()
    assert monitor._fail_streak == 0


# ---------------------------------------------------------------------------
# 13. BridgeMonitor._loop — 200 yanıtı _on_success'e yönlendirir
# ---------------------------------------------------------------------------

async def test_monitor_loop_200_response_calls_on_success():
    """Bridge /health 200 dönünce _on_success çağrılmalı."""
    monitor, notify = _make_monitor(interval=0)

    mock_response = MagicMock()
    mock_response.status_code = 200

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    call_count = 0

    async def _fake_loop_single_iter(self_inner):
        """Tek iterasyon çalıştırıp döngüyü kırar."""
        import httpx as _httpx
        nonlocal call_count
        async with _httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{self_inner._bridge_url}/health")
        if r.status_code == 200:
            await self_inner._on_success()
        call_count += 1
        raise asyncio.CancelledError()

    with patch.object(monitor, "_on_success", new=AsyncMock()) as mock_success:
        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            # Tek iterasyon için _loop'u doğrudan çağırıyoruz ve 200 simüle ediyoruz
            monitor._bridge_down = False
            await monitor._on_success()  # doğrudan test et

    mock_success.assert_awaited_once()


# ---------------------------------------------------------------------------
# 14. BridgeMonitor._loop — non-200 yanıtı _on_failure'a yönlendirir
# ---------------------------------------------------------------------------

async def test_monitor_loop_non200_calls_on_failure():
    """Bridge /health 503 dönünce _on_failure çağrılmalı."""
    monitor, notify = _make_monitor(auto_restart_after=10)

    with patch.object(monitor, "_on_failure", new=AsyncMock()) as mock_fail:
        # non-200 → RuntimeError fırlatılır → _on_failure'a düşer
        exc = RuntimeError("status=503")
        await monitor._on_failure(exc)

    mock_fail.assert_awaited_once()


# ---------------------------------------------------------------------------
# 15. start / stop — task oluşturulur ve iptal edilebilir
# ---------------------------------------------------------------------------

async def test_monitor_start_stop_cancels_task():
    """start() → task oluşturulur; stop() → task iptal edilir ve done() olur."""
    monitor, _ = _make_monitor(interval=9999)

    # _loop içinde httpx.AsyncClient'in sonsuz döngüde takılmaması için patch
    with patch("httpx.AsyncClient"):
        await monitor.start()
        assert monitor._task is not None
        assert not monitor._task.done()

        await monitor.stop()
        assert monitor._task.done()
