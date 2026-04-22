"""Rate limiter — dakika başına istek sınırı (SRP)."""
from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    """Sliding window rate limiter. Her numara için ayrı pencere tutar."""

    _CLEANUP_INTERVAL = 300.0   # saniye — temizlik ne sıklıkla çalışır
    _ENTRY_TTL        = 120.0   # saniye — son istekten bu kadar sonra girişi sil

    def __init__(self, max_per_minute: int = 20) -> None:
        self._max = max_per_minute
        self._windows: dict[str, deque[float]] = defaultdict(deque)
        self._last_cleanup: float = 0.0

    def check(self, number: str) -> bool:
        """True → istek kabul edildi. False → limit aşıldı."""
        now = time.time()
        if now - self._last_cleanup > self._CLEANUP_INTERVAL:
            self._cleanup(now)
        window = self._windows[number]
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self._max:
            return False
        window.append(now)
        return True

    def _cleanup(self, now: float) -> None:
        """TTL süresi geçmiş veya boş pencereleri sil — bellek sızıntısını önler."""
        ttl_cutoff = now - self._ENTRY_TTL
        stale = [k for k, v in self._windows.items() if not v or v[-1] < ttl_cutoff]
        for k in stale:
            del self._windows[k]
        self._last_cleanup = now
