"""Deduplication repository — seen_messages tablosu (SEC-RL2 SRP)."""
from __future__ import annotations

import time

from ._thread_runner import run_in_thread

from .._connection import _conn


def _sync_dedup_is_seen(message_id: str, now: float, ttl: float = 300.0) -> bool:
    """
    Mesajı daha önce görüp görmediğimizi kontrol eder ve işaretler.
    Atomik — race condition güvenli (INSERT OR IGNORE).
    Returns True → duplicate (işleme alma), False → yeni mesaj.
    """
    cutoff = now - ttl
    with _conn() as con:
        con.execute("DELETE FROM seen_messages WHERE seen_at < ?", (cutoff,))
        cur = con.execute(
            "INSERT OR IGNORE INTO seen_messages (message_id, seen_at) VALUES (?, ?)",
            (message_id, now),
        )
        return cur.rowcount == 0


def _sync_dedup_load_recent(ttl: float = 300.0) -> set[str]:
    """Servis başlangıcında son TTL saniyesindeki mesaj ID'lerini yükle."""
    cutoff = time.time() - ttl
    with _conn() as con:
        rows = con.execute(
            "SELECT message_id FROM seen_messages WHERE seen_at >= ?", (cutoff,)
        ).fetchall()
    return {r["message_id"] for r in rows}


# ── Async public API ──────────────────────────────────────────────

async def dedup_is_seen(message_id: str, now: float, ttl: float = 300.0) -> bool:
    return await run_in_thread(_sync_dedup_is_seen, message_id, now, ttl)


async def dedup_load_recent(ttl: float = 300.0) -> set[str]:
    return await run_in_thread(_sync_dedup_load_recent, ttl)
