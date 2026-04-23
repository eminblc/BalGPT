"""Message repository — messages, session_summaries, bridge_calls tabloları (SRP)."""
from __future__ import annotations

import time

from ._thread_runner import run_in_thread
import uuid

from .._connection import _conn


# ── Messages ──────────────────────────────────────────────────────

def _sync_message_log(
    msg_id: str,
    direction: str,
    sender: str,
    msg_type: str,
    content: str = "",
    media_id: str | None = None,
    media_path: str | None = None,
    mime_type: str | None = None,
    context_id: str = "main",
    raw_json: str = "{}",
) -> None:
    """Mesajı (gelen veya giden) kaydet — asla silme."""
    with _conn() as con:
        con.execute(
            """INSERT OR IGNORE INTO messages
               (id,direction,sender,msg_type,content,media_id,media_path,mime_type,context_id,ts,raw_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (msg_id, direction, sender, msg_type, content or "",
             media_id, media_path, mime_type, context_id, time.time(), raw_json),
        )


def _sync_message_list(sender: str, limit: int = 50, offset: int = 0, since: float = 0.0) -> list[dict]:
    """Son N mesajı döndür (yeniden eskiye)."""
    with _conn() as con:
        if since:
            rows = con.execute(
                """SELECT * FROM messages WHERE sender=? AND ts>=?
                   ORDER BY ts DESC LIMIT ? OFFSET ?""",
                (sender, since, limit, offset),
            ).fetchall()
        else:
            rows = con.execute(
                """SELECT * FROM messages WHERE sender=?
                   ORDER BY ts DESC LIMIT ? OFFSET ?""",
                (sender, limit, offset),
            ).fetchall()
        return [dict(r) for r in rows]


def _sync_message_count(sender: str) -> int:
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) AS cnt FROM messages WHERE sender=?", (sender,)
        ).fetchone()
        return row["cnt"] if row else 0


def _sync_message_count_since(sender: str, since_ts: float) -> int:
    """Belirli bir zamandan sonraki mesaj sayısını döndür."""
    with _conn() as con:
        row = con.execute(
            "SELECT COUNT(*) AS cnt FROM messages WHERE sender=? AND ts>=?",
            (sender, since_ts),
        ).fetchone()
        return row["cnt"] if row else 0


# ── Session Summaries ─────────────────────────────────────────────

def _sync_session_summary_save(
    sender: str,
    context_id: str,
    started_at: float,
    ended_at: float,
    msg_count: int,
    summary: str = "",
) -> dict:
    summary_id = str(uuid.uuid4())
    now = time.time()
    with _conn() as con:
        con.execute(
            """INSERT INTO session_summaries
               (id,sender,context_id,started_at,ended_at,msg_count,summary,created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (summary_id, sender, context_id, started_at, ended_at, msg_count, summary, now),
        )
    return {"id": summary_id, "sender": sender, "context_id": context_id,
            "started_at": started_at, "ended_at": ended_at, "msg_count": msg_count,
            "summary": summary}


def _sync_session_summaries_list(sender: str, limit: int = 20) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT * FROM session_summaries WHERE sender=?
               ORDER BY ended_at DESC LIMIT ?""",
            (sender, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Bridge Calls ──────────────────────────────────────────────────

def _sync_bridge_call_log(
    sender: str,
    session_id: str,
    prompt: str,
    response: str = "",
    latency_ms: int = 0,
    success: bool = True,
    error_msg: str = "",
) -> None:
    call_id = str(uuid.uuid4())
    with _conn() as con:
        con.execute(
            """INSERT INTO bridge_calls
               (id,sender,session_id,prompt,response,latency_ms,success,error_msg,ts)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (call_id, sender, session_id, prompt, response,
             latency_ms, int(success), error_msg, time.time()),
        )


def _sync_bridge_calls_list(sender: str, limit: int = 20) -> list[dict]:
    with _conn() as con:
        rows = con.execute(
            """SELECT * FROM bridge_calls WHERE sender=?
               ORDER BY ts DESC LIMIT ?""",
            (sender, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Async public API ──────────────────────────────────────────────

async def message_log(
    msg_id: str,
    direction: str,
    sender: str,
    msg_type: str,
    content: str = "",
    media_id: str | None = None,
    media_path: str | None = None,
    mime_type: str | None = None,
    context_id: str = "main",
    raw_json: str = "{}",
) -> None:
    return await run_in_thread(
        _sync_message_log, msg_id, direction, sender, msg_type,
        content, media_id, media_path, mime_type, context_id, raw_json,
    )


async def message_list(sender: str, limit: int = 50, offset: int = 0) -> list[dict]:
    return await run_in_thread(_sync_message_list, sender, limit, offset)


async def message_count(sender: str) -> int:
    return await run_in_thread(_sync_message_count, sender)


async def session_summary_save(
    sender: str,
    context_id: str,
    started_at: float,
    ended_at: float,
    msg_count: int,
    summary: str = "",
) -> dict:
    return await run_in_thread(
        _sync_session_summary_save, sender, context_id, started_at, ended_at, msg_count, summary
    )


async def session_summaries_list(sender: str, limit: int = 20) -> list[dict]:
    return await run_in_thread(_sync_session_summaries_list, sender, limit)


async def bridge_call_log(
    sender: str,
    session_id: str,
    prompt: str,
    response: str = "",
    latency_ms: int = 0,
    success: bool = True,
    error_msg: str = "",
) -> None:
    return await run_in_thread(
        _sync_bridge_call_log, sender, session_id, prompt, response, latency_ms, success, error_msg
    )


async def bridge_calls_list(sender: str, limit: int = 20) -> list[dict]:
    return await run_in_thread(_sync_bridge_calls_list, sender, limit)
