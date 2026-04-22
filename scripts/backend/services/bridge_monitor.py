"""Bridge sağlık monitörü — SRP-1 gereği main.py lifespan'dan ayrıştırıldı.

Sorumluluk: Bridge'in canlılığını periyodik olarak kontrol etmek ve gerektiğinde
otomatik systemctl restart tetiklemek.

main.py yalnızca:
    monitor = BridgeMonitor(settings.claude_bridge_url, _notify)
    await monitor.start()
    ...
    await monitor.stop()
çağırır; tüm izleme mantığı bu sınıfta kapsüllenmiştir.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from ..i18n import t as _t
from ..constants import BRIDGE_CHECK_INTERVAL_SEC, BRIDGE_AUTO_RESTART_AFTER, BRIDGE_RESTART_TIMEOUT_SEC

logger = logging.getLogger(__name__)


async def restart_bridge_service() -> tuple[bool, str]:
    """REFAC-11: Bridge systemd servisini yeniden başlat — BridgeMonitor'dan bağımsız çalışır.

    Returns:
        (success: bool, message: str)  — başarı durumu ve kısa açıklama
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "sudo", "-n", "systemctl", "restart",
            "personal-agent-bridge.service",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=BRIDGE_RESTART_TIMEOUT_SEC
            )
        except asyncio.TimeoutError:
            proc.kill()
            return False, _t("bridge_monitor.restart_timeout", "tr")
        if proc.returncode == 0:
            return True, _t("bridge_monitor.restart_success", "tr")
        stderr_str = stderr_b.decode(errors="replace").strip()
        detail = stderr_str[:200] or "—"
        return False, _t("bridge_monitor.restart_failed", "tr", detail=detail)
    except Exception as exc:
        return False, _t("bridge_monitor.restart_error", "tr", error=exc)


class BridgeMonitor:
    """Bridge sağlık izleyicisi.

    Args:
        bridge_url:          Bridge health endpoint'inin kök URL'si (ör. http://localhost:8013).
        notify_fn:           Owner'a bildirim gönderen async fonksiyon.
        check_interval:      Kontrol aralığı (saniye). Varsayılan 60.
        auto_restart_after:  Art arda kaç başarısızlıktan sonra restart tetiklenir. Varsayılan 3.
    """

    def __init__(
        self,
        bridge_url: str,
        notify_fn: Callable[[str], Coroutine[Any, Any, None]],
        check_interval: int = BRIDGE_CHECK_INTERVAL_SEC,
        auto_restart_after: int = BRIDGE_AUTO_RESTART_AFTER,
    ) -> None:
        self._bridge_url      = bridge_url
        self._notify          = notify_fn
        self._check_interval  = check_interval
        self._auto_restart_after = auto_restart_after
        self._task: asyncio.Task | None = None
        # İzleme durumu
        self._bridge_down = False
        self._fail_streak = 0

    async def start(self) -> None:
        """Arka plan izleme görevini başlat."""
        self._task = asyncio.create_task(self._loop())
        logger.info(
            "BridgeMonitor başlatıldı (interval=%ds, auto_restart_after=%d)",
            self._check_interval, self._auto_restart_after,
        )

    async def stop(self) -> None:
        """İzleme görevini iptal et ve tamamlanmasını bekle."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    # ── İç döngü ──────────────────────────────────────────────────

    async def _loop(self) -> None:
        import httpx
        while True:
            await asyncio.sleep(self._check_interval)
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    r = await client.get(f"{self._bridge_url}/health")
                if r.status_code == 200:
                    await self._on_success()
                else:
                    raise RuntimeError(f"status={r.status_code}")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                await self._on_failure(exc)

    async def _on_success(self) -> None:
        if self._bridge_down:
            logger.info("Bridge yeniden erişilebilir")
            await self._notify(_t("bridge_monitor.bridge_up", "tr"))
            self._bridge_down = False
        self._fail_streak = 0

    async def _on_failure(self, exc: Exception) -> None:
        self._fail_streak += 1
        logger.warning(
            "Bridge health-check başarısız (%d/%d): %s",
            self._fail_streak, self._auto_restart_after, exc,
        )
        if not self._bridge_down:
            await self._notify(_t("bridge_monitor.bridge_down", "tr", error=exc))
            self._bridge_down = True

        # ERR-1: art arda başarısızlık limitine ulaşıldı → otomatik restart
        if self._fail_streak >= self._auto_restart_after:
            await self._auto_restart()

    async def _auto_restart(self) -> None:
        """ERR-1: Bridge'i systemctl üzerinden otomatik olarak yeniden başlat (REFAC-11)."""
        self._fail_streak = 0
        logger.error(
            "Bridge %d kez yanıtsız — otomatik restart tetikleniyor",
            self._auto_restart_after,
        )
        await self._notify(_t("bridge_monitor.auto_restart", "tr"))
        success, msg = await restart_bridge_service()
        if success:
            logger.info(msg)
        else:
            logger.error(msg)
            await self._notify(_t("bridge_monitor.auto_restart_failed", "tr", msg=msg))
