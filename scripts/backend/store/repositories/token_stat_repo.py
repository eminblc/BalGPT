"""Token kullanım istatistikleri repository — token_usage tablosu (SRP)."""
from __future__ import annotations

import time

from ._thread_runner import run_in_thread
import uuid
from datetime import datetime, timezone


from .._connection import _conn


def _sync_add_usage(
    model_id: str,
    model_name: str,
    backend: str,
    input_tokens: int,
    output_tokens: int,
    session_id: str | None = None,
    context: str = "bridge_query",
) -> None:
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            """
            INSERT INTO token_usage
                (id, timestamp, model_id, model_name, backend,
                 input_tokens, output_tokens, total_tokens, session_id, context)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                ts,
                model_id,
                model_name,
                backend,
                input_tokens,
                output_tokens,
                input_tokens + output_tokens,
                session_id,
                context,
            ),
        )


def _sync_get_summary(since_ts: float) -> dict:
    """Verilen Unix timestamp'ten bu yana backend ve model bazında özet döndürür."""
    since_iso = datetime.fromtimestamp(since_ts, tz=timezone.utc).isoformat()
    with _conn() as con:
        rows = con.execute(
            """
            SELECT backend, model_name, model_id,
                   COUNT(*) AS calls,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(total_tokens) AS total_tokens
            FROM token_usage
            WHERE timestamp >= ?
            GROUP BY backend, model_name, model_id
            ORDER BY total_tokens DESC
            """,
            (since_iso,),
        ).fetchall()
    return [dict(r) for r in rows]


def _sync_get_totals(since_ts: float) -> dict:
    since_iso = datetime.fromtimestamp(since_ts, tz=timezone.utc).isoformat()
    with _conn() as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS calls,
                   SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,
                   SUM(total_tokens) AS total_tokens
            FROM token_usage
            WHERE timestamp >= ?
            """,
            (since_iso,),
        ).fetchone()
    return dict(row) if row else {}


# ── Async public API ──────────────────────────────────────────────


async def add_usage(
    model_id: str,
    model_name: str,
    backend: str,
    input_tokens: int,
    output_tokens: int,
    session_id: str | None = None,
    context: str = "bridge_query",
) -> None:
    """Token kullanımını kaydet — non-blocking."""
    await run_in_thread(
        _sync_add_usage,
        model_id,
        model_name,
        backend,
        input_tokens,
        output_tokens,
        session_id,
        context,
    )


async def get_summary(timespan_hours: int = 24) -> list[dict]:
    """Son `timespan_hours` saat içindeki backend+model bazında kullanım özeti."""
    since = time.time() - timespan_hours * 3600
    return await run_in_thread(_sync_get_summary, since)


async def get_totals(timespan_hours: int = 24) -> dict:
    """Son `timespan_hours` saat içindeki toplam token ve çağrı sayısı."""
    since = time.time() - timespan_hours * 3600
    return await run_in_thread(_sync_get_totals, since)
