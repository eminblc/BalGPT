"""DbExporter — SQLite veritabanını Python dict'e aktarır.

SRP: Yalnızca veritabanı okuma ve dict dönüşümü sorumluluğu taşır.
     Orchestration → ExportService; binary format → BackupWriter.

Tasarım notları:
  - Tüm sorgular asyncio.to_thread üzerinden çalışır — event loop bloke edilmez.
  - `totp_lockouts` ve `seen_messages` kasıtlı olarak dışlanır (§2.2).
  - `_export_messages(limit=0)` → tüm mesajlar; limit>0 → son N mesaj (ORDER BY ts DESC).
  - Rapor referansı: §4.6, §4.9.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import TYPE_CHECKING

from ...store._connection import _conn

if TYPE_CHECKING:
    from ._scope import ExportScope

logger = logging.getLogger(__name__)


def _rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict]:
    """sqlite3.Row listesini seri hale getirilebilir dict listesine dönüştürür."""
    return [dict(row) for row in rows]


class DbExporter:
    """SQLite → Python dict dönüşümü.

    DataExporter protokolünü uygular — DIP uyumlu.
    Bağımlılık: yalnızca _conn() context manager (store._connection).

    OOP notu: ORM veya repository'e bağımlılık yoktur; doğrudan SQL sorgusu kullanır.
    Bu, export'un mevcut repository API'sinden bağımsız kalmasını sağlar ve
    şema değişikliklerinde tek bir noktayı güncellemeyi gerektirir.
    """

    # ------------------------------------------------------------------
    # DataExporter Protokolü
    # ------------------------------------------------------------------

    async def export(self, scope: "ExportScope") -> dict:
        """Kapsama göre veritabanını dict olarak döndürür.

        Returns:
            {
                "projects": [...],
                "work_plans": [...],
                "calendar_events": [...],
                "scheduled_tasks": [...],
                "messages": [...],
                "session_summaries": [...],
                "user_settings": [...],
                "bridge_calls": [...],
                "token_usage": [...],
            }
        """
        projects = await self._export_table("projects")

        work_plans = (
            await self._export_table("work_plans") if scope.include_plans else []
        )
        calendar_events = (
            await self._export_table("calendar_events") if scope.include_calendar else []
        )
        scheduled_tasks = (
            await self._export_tasks() if scope.include_tasks else []
        )

        messages: list[dict] = []
        session_summaries: list[dict] = []
        if scope.include_messages:
            messages = await self._export_messages(scope.messages_limit)
            session_summaries = await self._export_table("session_summaries")

        user_settings = (
            await self._export_table("user_settings") if scope.include_settings else []
        )
        bridge_calls = (
            await self._export_table("bridge_calls") if scope.include_bridge_calls else []
        )
        token_usage = (
            await self._export_table("token_usage") if scope.include_token_usage else []
        )

        result = {
            "projects": projects,
            "work_plans": work_plans,
            "calendar_events": calendar_events,
            "scheduled_tasks": scheduled_tasks,
            "messages": messages,
            "session_summaries": session_summaries,
            "user_settings": user_settings,
            "bridge_calls": bridge_calls,
            "token_usage": token_usage,
        }

        counts = {k: len(v) for k, v in result.items()}
        logger.info("DbExporter tamamlandı: %s", counts)
        return result

    # ------------------------------------------------------------------
    # Özel yardımcılar
    # ------------------------------------------------------------------

    async def _export_table(self, table: str) -> list[dict]:
        """Tablonun tüm satırlarını döndürür.

        Args:
            table: Tablo adı (kullanıcı girdisi değil — internal sabit; injection riski yok).
        """
        return await asyncio.to_thread(self._sync_export_table, table)

    def _sync_export_table(self, table: str) -> list[dict]:
        with _conn() as con:
            rows = con.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        return _rows_to_dicts(rows)

    async def _export_messages(self, limit: int) -> list[dict]:
        """Mesajları ORDER BY ts DESC ile çeker.

        Args:
            limit: Maksimum satır sayısı. 0 = tüm mesajlar.
        """
        return await asyncio.to_thread(self._sync_export_messages, limit)

    def _sync_export_messages(self, limit: int) -> list[dict]:
        with _conn() as con:
            if limit > 0:
                rows = con.execute(
                    "SELECT * FROM messages ORDER BY ts DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT * FROM messages ORDER BY ts DESC"
                ).fetchall()
        return _rows_to_dicts(rows)

    async def _export_tasks(self) -> list[dict]:
        """Tüm görevleri döndürür — aktif/pasif ayrımı olmaksızın."""
        return await self._export_table("scheduled_tasks")
