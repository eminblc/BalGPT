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

    Tek atomik SQL işlemi — TOCTOU race condition'ını önler.
    INSERT + tek UPDATE ile hem sayaç hem kilit aynı transaction'da güncellenir.
    Returns: (yeni fail_count, locked_until) — locked_until=0 kilit yok demek.
    """
    now = time.time()
    locked_until = now + lockout_duration
    with _conn() as con:
        con.execute(
            """INSERT INTO totp_lockouts (sender, totp_type, fail_count, locked_until)
               VALUES (:sender, :totp_type, 1, 0)
               ON CONFLICT(sender, totp_type) DO UPDATE SET
                 fail_count = fail_count + 1,
                 locked_until = CASE WHEN fail_count + 1 >= 3 THEN :locked_until ELSE 0 END""",
            {"sender": sender, "totp_type": totp_type, "locked_until": locked_until},
        )
        row = con.execute(
            "SELECT fail_count, locked_until FROM totp_lockouts WHERE sender=? AND totp_type=?",
            (sender, totp_type),
        ).fetchone()
    if row:
        return (row["fail_count"], row["locked_until"])
    return (1, 0.0)


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
