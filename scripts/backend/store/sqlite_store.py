"""SQLite kalıcı depolama — şema, bağlantı ve repository re-export'ları.

Veri erişim implementasyonları store/repositories/ altında entity bazında ayrılmıştır (SRP).
Bu modül geriye dönük uyum için tüm public API'yi re-export eder;
mevcut `from ..store import sqlite_store as db` çağrıları değişmeden çalışır.

AUD-K2: Tüm public DB fonksiyonları asyncio.to_thread() sarmalayıcılar üzerinden
erişilir; event loop bloke edilmez. Sync implementasyonlar `_sync_*` prefix ile özel
kalır; message_logger ve deduplication gibi sync bağlamlar bunları doğrudan kullanır.
"""
from __future__ import annotations

import asyncio
import sqlite3

from ..config import settings
from ._connection import _conn, _resolve_db_path  # noqa: F401 — re-export

# ── Şema (init_db) — tablolar ve indeksler ────────────────────────


def init_db() -> None:
    """Şemayı oluştur — idempotent, her startup'ta çağrılır."""
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            description TEXT DEFAULT '',
            status      TEXT DEFAULT 'idle',
            path        TEXT NOT NULL,
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL,
            source_pdf  TEXT,
            metadata    TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS work_plans (
            id           TEXT PRIMARY KEY,
            title        TEXT NOT NULL,
            description  TEXT DEFAULT '',
            status       TEXT DEFAULT 'active',
            priority     INTEGER DEFAULT 2,
            due_date     REAL,
            created_at   REAL NOT NULL,
            completed_at REAL,
            project_id   TEXT REFERENCES projects(id)
        );

        CREATE TABLE IF NOT EXISTS calendar_events (
            id                     TEXT PRIMARY KEY,
            title                  TEXT NOT NULL,
            description            TEXT DEFAULT '',
            event_time             REAL NOT NULL,
            remind_before_minutes  INTEGER DEFAULT 30,
            recurring              TEXT,
            notified               INTEGER DEFAULT 0,
            created_at             REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scheduled_tasks (
            id             TEXT PRIMARY KEY,
            description    TEXT NOT NULL,
            cron_expr      TEXT,
            next_run       REAL,
            last_run       REAL,
            active         INTEGER DEFAULT 1,
            action_type    TEXT NOT NULL,
            action_payload TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS agent_runs (
            id              TEXT PRIMARY KEY,
            agent_type      TEXT NOT NULL,
            project_id      TEXT REFERENCES projects(id),
            session_id      TEXT NOT NULL,
            task_id         TEXT REFERENCES scheduled_tasks(id),
            source          TEXT DEFAULT 'internal',
            sender          TEXT,
            prompt          TEXT,
            status          TEXT DEFAULT 'pending',
            started_at      REAL,
            completed_at    REAL,
            duration_ms     INTEGER,
            output          TEXT,
            error_msg       TEXT,
            exit_code       INTEGER,
            metadata        TEXT DEFAULT '{}',
            created_at      REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_plans_status   ON work_plans(status);
        CREATE INDEX IF NOT EXISTS idx_events_time    ON calendar_events(event_time);
        CREATE INDEX IF NOT EXISTS idx_tasks_active   ON scheduled_tasks(active, next_run);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_project ON agent_runs(project_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(session_id, status);
        CREATE INDEX IF NOT EXISTS idx_agent_runs_status  ON agent_runs(status, started_at DESC);

        -- ── Mesaj geçmişi ─────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS messages (
            id          TEXT PRIMARY KEY,
            direction   TEXT NOT NULL,
            sender      TEXT NOT NULL,
            msg_type    TEXT NOT NULL,
            content     TEXT DEFAULT '',
            media_id    TEXT,
            media_path  TEXT,
            mime_type   TEXT,
            context_id  TEXT DEFAULT 'main',
            ts          REAL NOT NULL,
            raw_json    TEXT DEFAULT '{}'
        );

        CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender, ts);

        CREATE TABLE IF NOT EXISTS session_summaries (
            id          TEXT PRIMARY KEY,
            sender      TEXT NOT NULL,
            context_id  TEXT NOT NULL,
            started_at  REAL NOT NULL,
            ended_at    REAL NOT NULL,
            msg_count   INTEGER DEFAULT 0,
            summary     TEXT DEFAULT '',
            created_at  REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_summaries_sender ON session_summaries(sender, ended_at);

        CREATE TABLE IF NOT EXISTS bridge_calls (
            id          TEXT PRIMARY KEY,
            sender      TEXT NOT NULL,
            session_id  TEXT NOT NULL,
            prompt      TEXT DEFAULT '',
            response    TEXT DEFAULT '',
            latency_ms  INTEGER DEFAULT 0,
            success     INTEGER DEFAULT 1,
            error_msg   TEXT DEFAULT '',
            ts          REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_bridge_sender ON bridge_calls(sender, ts);

        -- ── TOTP kilitleri ────────────────────────────────────────
        CREATE TABLE IF NOT EXISTS totp_lockouts (
            sender      TEXT NOT NULL,
            totp_type   TEXT NOT NULL,
            fail_count  INTEGER DEFAULT 0,
            locked_until REAL DEFAULT 0,
            PRIMARY KEY (sender, totp_type)
        );

        -- ── Mesaj tekrarı önleme ──────────────────────────────────
        CREATE TABLE IF NOT EXISTS seen_messages (
            message_id  TEXT PRIMARY KEY,
            seen_at     REAL NOT NULL
        );

        -- ── Kullanıcı ayarları — FEAT-6 ───────────────────────────
        -- Restart sonrası da korunan kullanıcı tercihleri (/lang, /model vb.)
        CREATE TABLE IF NOT EXISTS user_settings (
            sender      TEXT NOT NULL,
            key         TEXT NOT NULL,
            value       TEXT NOT NULL,
            updated_at  REAL NOT NULL,
            PRIMARY KEY (sender, key)
        );

        -- ── Token kullanım istatistikleri — TOKEN-STATS-1 ────────────
        CREATE TABLE IF NOT EXISTS token_usage (
            id            TEXT PRIMARY KEY,
            timestamp     TEXT NOT NULL,
            model_id      TEXT NOT NULL,
            model_name    TEXT NOT NULL,
            backend       TEXT NOT NULL,
            input_tokens  INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            total_tokens  INTEGER NOT NULL,
            session_id    TEXT,
            context       TEXT DEFAULT 'bridge_query',
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_token_usage_ts      ON token_usage(timestamp);
        CREATE INDEX IF NOT EXISTS idx_token_usage_backend ON token_usage(backend, timestamp);

        -- ── Telegram install wizard state ─────────────────────────
        -- Stage-2 wizard runs after install.sh; collects LLM/TZ/caps via inline buttons.
        -- Single row per chat_id; deleted on completion or reset.
        CREATE TABLE IF NOT EXISTS install_wizard_state (
            chat_id        TEXT PRIMARY KEY,
            step           TEXT NOT NULL,
            data           TEXT NOT NULL DEFAULT '{}',
            awaiting_text  TEXT,
            updated_at     REAL NOT NULL
        );

        -- ── Per-item token kullanımı — TOKEN-PER-ITEM-1 ───────────
        -- Backlog item, scanner chunk, reviewer batch gibi tek bir
        -- "iş birimine" ait token tüketimini kayıt altına alır.
        -- token_usage tablosunun per-call kaydıyla tamamlayıcı (birbirini dışlamaz).
        CREATE TABLE IF NOT EXISTS task_token_usage (
            id            TEXT PRIMARY KEY,
            task_id       TEXT NOT NULL,
            task_type     TEXT NOT NULL,
            run_id        TEXT,
            model_id      TEXT NOT NULL DEFAULT '',
            model_name    TEXT NOT NULL DEFAULT '',
            backend       TEXT NOT NULL DEFAULT '',
            input_tokens  INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read    INTEGER NOT NULL DEFAULT 0,
            cache_write   INTEGER NOT NULL DEFAULT 0,
            started_at    REAL,
            finished_at   REAL,
            created_at    REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_task_token_type_ts ON task_token_usage(task_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_task_token_run_id  ON task_token_usage(run_id);
        """)


_MIGRATE_SCHEDULED_TASKS_COLUMNS: dict[str, str] = {
    "status":       "TEXT DEFAULT 'scheduled'",
    "deleted_at":   "REAL",
    "project_id":   "TEXT",
    "scope":        "TEXT DEFAULT 'global'",
    "output":       "TEXT",
    "error_detail": "TEXT",
}


def _migrate_scheduled_tasks(con: sqlite3.Connection) -> None:
    """scheduled_tasks tablosuna soft-delete kolonlarını ekle (idempotent)."""
    for col, definition in _MIGRATE_SCHEDULED_TASKS_COLUMNS.items():
        if col not in _MIGRATE_SCHEDULED_TASKS_COLUMNS:
            raise ValueError(f"Bilinmeyen migration kolonu: {col!r}")
        ddl = f"ALTER TABLE scheduled_tasks ADD COLUMN {col} {definition}"  # col whitelist'te
        try:
            con.execute(ddl)
        except sqlite3.OperationalError as e:
            msg = str(e)
            if "already exists" not in msg and "duplicate column name" not in msg:
                raise  # beklenmedik hata — yutma


def init_db_migrations() -> None:
    """init_db() sonrası çalışan incremental migration'lar — idempotent."""
    with _conn() as con:
        _migrate_scheduled_tasks(con)


async def db_ping() -> bool:
    """DB bağlantısı sağlıklı mı? /health endpoint'i için."""
    def _check():
        with _conn() as con:
            con.execute("SELECT 1")
    try:
        await asyncio.to_thread(_check)
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# Repository re-export'ları — geriye dönük uyum
# Tüm `from ..store import sqlite_store as db; db.<fn>()` çağrıları
# değişmeden çalışmaya devam eder.
# ══════════════════════════════════════════════════════════════════

from .repositories.project_repo import (  # noqa: E402, F401
    slugify_project_name,
    _PROJECT_ID_RE,
    _sync_project_create,
    _sync_project_get,
    _sync_project_list,
    _sync_project_update_status,
    _sync_project_delete,
    _sync_project_update_metadata,
    project_create,
    project_get,
    project_list,
    project_update_status,
    project_delete,
    project_update_metadata,
)

from .repositories.plan_repo import (  # noqa: E402, F401
    _sync_plan_create,
    _sync_plan_get,
    _sync_plan_list,
    _sync_plan_complete,
    _sync_plan_delete,
    plan_create,
    plan_get,
    plan_list,
    plan_complete,
    plan_delete,
)

from .repositories.event_repo import (  # noqa: E402, F401
    _sync_event_create,
    _sync_event_get,
    _sync_event_list_upcoming,
    _sync_event_mark_notified,
    _sync_event_delete,
    _sync_events_due_for_reminder,
    event_create,
    event_get,
    event_list_upcoming,
    event_mark_notified,
    event_delete,
    events_due_for_reminder,
)

from .repositories.task_repo import (  # noqa: E402, F401
    _sync_task_create,
    _sync_task_get,
    _sync_task_list_active,
    _sync_task_deactivate,
    _sync_task_activate,
    _sync_task_delete,
    _sync_task_list_all,
    _sync_task_find_by_prefix,
    _sync_task_update_last_run,
    _sync_task_soft_delete,
    _sync_task_update_status,
    task_create,
    task_get,
    task_list_active,
    task_deactivate,
    task_activate,
    task_delete,
    task_list_all,
    task_find_by_prefix,
    task_update_last_run,
    task_soft_delete,
    task_update_status,
)

from .repositories.message_repo import (  # noqa: E402, F401
    _sync_message_log,
    _sync_message_list,
    _sync_message_count,
    _sync_message_count_since,
    _sync_session_summary_save,
    _sync_session_summaries_list,
    _sync_bridge_call_log,
    _sync_bridge_calls_list,
    message_log,
    message_list,
    message_count,
    session_summary_save,
    session_summaries_list,
    bridge_call_log,
    bridge_calls_list,
)

from .repositories.totp_repo import (  # noqa: E402, F401
    _sync_totp_get_lockout,
    _sync_totp_record_failure,
    _sync_totp_reset_lockout,
    totp_get_lockout,
    totp_record_failure,
    totp_reset_lockout,
)

from .repositories.dedup_repo import (  # noqa: E402, F401
    _sync_dedup_is_seen,
    _sync_dedup_load_recent,
    dedup_is_seen,
    dedup_load_recent,
)

from .repositories.settings_repo import (  # noqa: E402, F401
    _sync_user_setting_get,
    _sync_user_setting_set,
    _sync_user_settings_get_all,
    _sync_user_setting_delete,
    user_setting_get,
    user_setting_set,
    user_settings_get_all,
    user_setting_delete,
)

from .repositories.agent_run_repo import (  # noqa: E402, F401
    _sync_agent_run_create,
    _sync_agent_run_update_status,
    _sync_agent_run_get,
    _sync_agent_run_list,
    _sync_agent_run_cancel,
    _sync_agent_run_list_active,
    _sync_agent_run_list_by_project,
    agent_run_create,
    agent_run_update_status,
    agent_run_get,
    agent_run_list,
    agent_run_cancel,
    agent_run_list_active,
    agent_run_list_by_project,
)
