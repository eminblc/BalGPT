"""Kullanıcı ayarları repository — user_settings tablosu (FEAT-6 SRP).

Restart sonrası da korunan kullanıcı tercihleri (/lang, /model vb.)
buradan okunur ve yazılır. Session yüklenirken _sync_* versiyonu
doğrudan çağrılır; çağıran kod async değildir.
"""
from __future__ import annotations

import time

from ._thread_runner import run_in_thread

from .._connection import _conn


# ── Sync implementasyonlar ────────────────────────────────────────

def _sync_user_setting_get(sender: str, key: str, default: str | None = None) -> str | None:
    """Belirli bir kullanıcı ayarını döndürür; yoksa default değeri."""
    with _conn() as con:
        row = con.execute(
            "SELECT value FROM user_settings WHERE sender = ? AND key = ?",
            (sender, key),
        ).fetchone()
    return row["value"] if row else default


def _sync_user_setting_set(sender: str, key: str, value: str) -> None:
    """Kullanıcı ayarını ekler veya günceller (UPSERT — atomik)."""
    now = time.time()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO user_settings (sender, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(sender, key) DO UPDATE SET
                value      = excluded.value,
                updated_at = excluded.updated_at
            """,
            (sender, key, value, now),
        )


def _sync_user_settings_get_all(sender: str) -> dict[str, str]:
    """Kullanıcıya ait tüm ayarları {key: value} sözlüğü olarak döndürür."""
    with _conn() as con:
        rows = con.execute(
            "SELECT key, value FROM user_settings WHERE sender = ?",
            (sender,),
        ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def _sync_user_setting_delete(sender: str, key: str) -> None:
    """Belirli bir kullanıcı ayarını siler."""
    with _conn() as con:
        con.execute(
            "DELETE FROM user_settings WHERE sender = ? AND key = ?",
            (sender, key),
        )


# ── Async public API ──────────────────────────────────────────────

async def user_setting_get(sender: str, key: str, default: str | None = None) -> str | None:
    return await run_in_thread(_sync_user_setting_get, sender, key, default)


async def user_setting_set(sender: str, key: str, value: str) -> None:
    await run_in_thread(_sync_user_setting_set, sender, key, value)


async def user_settings_get_all(sender: str) -> dict[str, str]:
    return await run_in_thread(_sync_user_settings_get_all, sender)


async def user_setting_delete(sender: str, key: str) -> None:
    await run_in_thread(_sync_user_setting_delete, sender, key)
