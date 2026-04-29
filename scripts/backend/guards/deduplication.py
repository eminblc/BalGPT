"""Duplicate mesaj koruması — aynı mesajın iki kez işlenmesini engeller (SRP).

SEC-RL2: Kalıcılık katmanı eklendi.
  - Bellek içi önbellek → hızlı yol (çoğu istek burada döner)
  - SQLite → restart sonrası Meta'nın yeniden gönderdiği mesajlar da engellenir
  - Startup'ta son TTL saniyesindeki ID'ler SQLite'tan yüklenir
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict

logger = logging.getLogger(__name__)


class DedupGuard:
    """Son N mesaj ID'sini önbellekte + SQLite'ta tutar."""

    def __init__(self, ttl: float = 300.0, max_size: int = 500) -> None:
        self._ttl = ttl
        self._max = max_size
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._db_available = False
        self._load_from_db()

    def _load_from_db(self) -> None:
        """Startup'ta SQLite'tan son TTL saniyesindeki ID'leri belleğe yükle."""
        try:
            from ..store.sqlite_store import _sync_dedup_load_recent
            recent = _sync_dedup_load_recent(self._ttl)
            now = time.time()
            for msg_id in recent:
                self._seen[msg_id] = now  # yaklaşık zaman (yeterli)
            self._db_available = True
            if recent:
                logger.info("DedupGuard: %d mesaj ID'si SQLite'tan yüklendi", len(recent))
        except Exception as exc:
            # "no such table" → lifespan'den önce çağrıldı, beklenen durum.
            # is_duplicate() içindeki lazy-reconnect init_db() sonrası tekrar dener.
            if "no such table" in str(exc).lower():
                logger.debug("DedupGuard: SQLite henüz hazır değil (lazy reconnect aktif): %s", exc)
            else:
                logger.warning("DedupGuard: SQLite yüklenemedi, yalnızca bellek kullanılacak: %s", exc)
            self._db_available = False

    def is_duplicate(self, message_id: str) -> bool:
        now = time.time()
        self._evict(now)

        # Hızlı yol: bellekte varsa duplicate
        if message_id in self._seen:
            return True

        # SQLite yolu: atomik INSERT OR IGNORE — restart sonrası koruması
        # _db_available False ise lazy-reconnect dene (init_db() sonradan çalışmış olabilir)
        if not self._db_available:
            self._load_from_db()

        if self._db_available:
            try:
                from ..store.sqlite_store import _sync_dedup_is_seen
                if _sync_dedup_is_seen(message_id, now, self._ttl):
                    # DB'de vardı ama bellekte yoktu (restart olmuş) — belleğe ekle
                    self._seen[message_id] = now
                    return True
            except Exception as exc:
                logger.warning("DedupGuard: SQLite sorgusu başarısız, belleğe düşülüyor: %s", exc)
                self._db_available = False

        # Yeni mesaj — belleğe ekle
        if len(self._seen) >= self._max:
            self._seen.popitem(last=False)
        self._seen[message_id] = now
        return False

    def _evict(self, now: float) -> None:
        cutoff = now - self._ttl
        while self._seen and next(iter(self._seen.values())) < cutoff:
            self._seen.popitem(last=False)
