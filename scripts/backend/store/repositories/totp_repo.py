"""TOTP Lockouts repository — totp_lockouts tablosu (SEC-A4 SRP)."""
from __future__ import annotations

import time

from ._thread_runner import run_in_thread

from .._connection import _conn


def _sync_totp_get_lockout(sender: str, totp_type: str) -> tuple[int, float]:
    """(fail_count, locked_until) döndür. Kayıt yoksa (0, 0.0)."""
    with _conn() as con:
        row = con.execute(
            "SELECT fail_count, locked_until FROM totp_lockouts WHERE sender=? AND totp_type=?",
            (sender, totp_type),
        ).fetchone()
        return (row["fail_count"], row["locked_until"]) if row else (0, 0.0)


def _sync_totp_record_failure(sender: str, totp_type: str, lockout_duration: float = 900.0) -> tuple[int, float]:
    """Başarısız deneme sayısını artır. 3. denemede 15 dk kilit koy.

    Tek atomik SQL işlemi — SELECT + UPDATE race condition'ını önler.
    Returns: (yeni fail_count, locked_until) — locked_until=0 kilit yok demek.
    """
    now = time.time()
    with _conn() as con:
        con.execute(
            """INSERT INTO totp_lockouts (sender, totp_type, fail_count, locked_until)
               VALUES (?, ?, 1, 0)
               ON CONFLICT(sender, totp_type) DO UPDATE SET
                 fail_count = fail_count + 1""",
            (sender, totp_type),
        )
        row = con.execute(
            "SELECT fail_count FROM totp_lockouts WHERE sender=? AND totp_type=?",
            (sender, totp_type),
        ).fetchone()
        fail_count = row["fail_count"] if row else 1
        locked_until = (now + lockout_duration) if fail_count >= 3 else 0.0
        if locked_until:
            con.execute(
                "UPDATE totp_lockouts SET locked_until=? WHERE sender=? AND totp_type=?",
                (locked_until, sender, totp_type),
            )
    return (fail_count, locked_until)


def _sync_totp_reset_lockout(sender: str, totp_type: str) -> None:
    """Başarılı doğrulama sonrası sayacı sıfırla."""
    with _conn() as con:
        con.execute(
            "DELETE FROM totp_lockouts WHERE sender=? AND totp_type=?",
            (sender, totp_type),
        )


# ── Async public API ──────────────────────────────────────────────

async def totp_get_lockout(sender: str, totp_type: str) -> tuple[int, float]:
    return await run_in_thread(_sync_totp_get_lockout, sender, totp_type)


async def totp_record_failure(
    sender: str, totp_type: str, lockout_duration: float = 900.0
) -> tuple[int, float]:
    return await run_in_thread(_sync_totp_record_failure, sender, totp_type, lockout_duration)


async def totp_reset_lockout(sender: str, totp_type: str) -> None:
    return await run_in_thread(_sync_totp_reset_lockout, sender, totp_type)
