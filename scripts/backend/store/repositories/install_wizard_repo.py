"""Install wizard state repository — install_wizard_state tablosu (SRP).

Stage-2 Telegram wizard'ı için kalıcı state. Tek kullanıcı modeli olsa da
chat_id PK olarak tutulur — gelecekte multi-tenant senaryosu için açık kapı.

State şeması:
  step:           'llm' | 'anthropic_auth' | 'anthropic_key' | 'ollama_url' |
                  'ollama_model' | 'gemini_key' | 'capabilities' | 'timezone' |
                  'timezone_custom' | 'totp' | 'done'
  data:           JSON — toplanan cevaplar (llm, anthropic_auth_method, ollama_url, ...)
  awaiting_text:  None ise sıradaki text mesajı normal yolda; aksi halde
                  bu field için input olarak değerlendirilir (örn. 'anthropic_key').
"""
from __future__ import annotations

import json
import time
from typing import Any

from .._connection import _conn
from ._thread_runner import run_in_thread


def _sync_get(chat_id: str) -> dict[str, Any] | None:
    with _conn() as con:
        row = con.execute(
            "SELECT step, data, awaiting_text, updated_at "
            "FROM install_wizard_state WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["data"]) if row["data"] else {}
    except json.JSONDecodeError:
        data = {}
    return {
        "step": row["step"],
        "data": data,
        "awaiting_text": row["awaiting_text"],
        "updated_at": row["updated_at"],
    }


def _sync_set(
    chat_id: str,
    step: str,
    data: dict[str, Any],
    awaiting_text: str | None,
) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    now = time.time()
    with _conn() as con:
        con.execute(
            "INSERT INTO install_wizard_state (chat_id, step, data, awaiting_text, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET "
            "step=excluded.step, data=excluded.data, "
            "awaiting_text=excluded.awaiting_text, updated_at=excluded.updated_at",
            (chat_id, step, payload, awaiting_text, now),
        )


def _sync_delete(chat_id: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM install_wizard_state WHERE chat_id = ?", (chat_id,))


# ── Async public API ──────────────────────────────────────────────

async def get_state(chat_id: str) -> dict[str, Any] | None:
    """Mevcut state'i getir; yoksa None."""
    return await run_in_thread(_sync_get, chat_id)


async def set_state(
    chat_id: str,
    step: str,
    data: dict[str, Any],
    awaiting_text: str | None = None,
) -> None:
    """State'i upsert et."""
    await run_in_thread(_sync_set, chat_id, step, data, awaiting_text)


async def delete_state(chat_id: str) -> None:
    """State satırını sil (wizard tamamlandığında veya reset)."""
    await run_in_thread(_sync_delete, chat_id)
