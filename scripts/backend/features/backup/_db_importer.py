"""DbImporter — Python dict'i SQLite veritabanına aktarır.

SRP: Yalnızca veritabanı yazma ve çakışma çözüm sorumluluğu taşır.
     Orchestration → ImportService; binary format → BackupReader.

Tasarım notları:
  - Import öncesi /tmp/pre_import_backup.db snapshot'ı alınır (geri alma imkânı).
  - `totp_lockouts` ve `seen_messages` kasıtlı olarak atlanır (§2.2, §6).
  - Tüm yazma işlemleri tek bir transaction içinde çalışır (_conn context manager).
  - asyncio.to_thread ile event loop bloke edilmez.
  - Tablo adları internal sabit — kullanıcı girdisi değil (injection riski yok).
  - Rapor referansı: §4.7, §6.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import ClassVar

from ...store._connection import _conn, _resolve_db_path
from ._protocol import ImportMode, ImportResult

logger = logging.getLogger(__name__)

_SNAPSHOT_PATH = Path("/tmp/pre_import_backup.db")


class DbImporter:
    """Python dict → SQLite import; transaction garantili.

    DataImporter protokolünü uygular — DIP uyumlu.
    Bağımlılık: yalnızca _conn() ve _resolve_db_path() (store._connection).

    ImportMode stratejileri:
      MERGE        — tablo bazlı UPSERT (§6'daki strateji tablosu)
      REPLACE      — tablo temizle + INSERT
      SKIP_EXISTING — INSERT OR IGNORE (tüm tablolar)
    """

    # Tablolar ve MERGE modunda uygulanacak çakışma stratejisi (§6)
    _MERGE_STRATEGIES: ClassVar[dict[str, str]] = {
        "projects": "INSERT OR REPLACE",
        "messages": "INSERT OR IGNORE",
        "session_summaries": "INSERT OR IGNORE",
        "work_plans": "INSERT OR REPLACE",
        "calendar_events": "INSERT OR REPLACE",
        "scheduled_tasks": "INSERT OR REPLACE",
        "user_settings": "INSERT OR REPLACE",
        "bridge_calls": "INSERT OR IGNORE",
        "token_usage": "INSERT OR IGNORE",
    }

    # Import sırasında atlanacak tablolar (§2.2, §6)
    _SKIP_TABLES: ClassVar[frozenset[str]] = frozenset(
        {"totp_lockouts", "seen_messages"}
    )

    # ------------------------------------------------------------------
    # DataImporter Protokolü
    # ------------------------------------------------------------------

    async def import_data(self, data: dict, mode: ImportMode) -> ImportResult:
        """Veriyi belirtilen mod ile veritabanına yazar.

        Import öncesi otomatik snapshot alınır: /tmp/pre_import_backup.db

        Args:
            data: DbExporter.export() çıktısı — {tablo_adı: [row_dict, ...]}
            mode: Çakışma çözüm stratejisi (MERGE / REPLACE / SKIP_EXISTING)

        Returns:
            ImportResult (tables_processed, rows_inserted, rows_skipped, errors)
        """
        await asyncio.to_thread(self._take_snapshot)
        return await asyncio.to_thread(self._sync_import, data, mode)

    # ------------------------------------------------------------------
    # Özel yardımcılar
    # ------------------------------------------------------------------

    def _take_snapshot(self) -> None:
        """Import öncesi DB dosyasını /tmp/ altına kopyalar."""
        src = _resolve_db_path()
        if not src.exists():
            logger.warning("Snapshot alınamadı — DB dosyası bulunamadı: %s", src)
            return
        shutil.copy2(src, _SNAPSHOT_PATH)
        logger.info("Pre-import snapshot alındı: %s → %s", src, _SNAPSHOT_PATH)

    def _sync_import(self, data: dict, mode: ImportMode) -> ImportResult:
        """Tüm tabloları tek transaction'da yazar."""
        result = ImportResult()

        with _conn() as con:
            for table, rows in data.items():
                if table in self._SKIP_TABLES:
                    logger.debug("Tablo atlandı (skip list): %s", table)
                    continue

                if not isinstance(rows, list):
                    result.errors.append(
                        f"{table}: beklenen list, alınan {type(rows).__name__}"
                    )
                    continue

                result.tables_processed.append(table)

                if not rows:
                    result.rows_inserted[table] = 0
                    result.rows_skipped[table] = 0
                    continue

                try:
                    inserted, skipped = self._import_table(con, table, rows, mode)
                    result.rows_inserted[table] = inserted
                    result.rows_skipped[table] = skipped
                    logger.debug(
                        "Tablo import: %s — eklenen=%d atlanan=%d",
                        table, inserted, skipped,
                    )
                except Exception as exc:  # noqa: BLE001
                    result.errors.append(f"{table}: {exc}")
                    logger.error("Tablo import hatası — %s: %s", table, exc)

        total = sum(result.rows_inserted.values())
        logger.info(
            "DbImporter tamamlandı: mode=%s toplam_eklenen=%d hata=%d",
            mode.value, total, len(result.errors),
        )
        return result

    def _import_table(
        self,
        con,
        table: str,
        rows: list[dict],
        mode: ImportMode,
    ) -> tuple[int, int]:
        """Tek tabloyu verilen mod ile yazar.

        Returns:
            (inserted, skipped) satır sayıları.
        """
        columns = list(rows[0].keys())
        col_names = ", ".join(columns)
        placeholders = ", ".join("?" * len(columns))

        if mode == ImportMode.REPLACE:
            return self._import_replace(con, table, rows, col_names, placeholders)

        if mode == ImportMode.SKIP_EXISTING:
            return self._import_with_stmt(
                con, table, rows, col_names, placeholders,
                prefix="INSERT OR IGNORE",
            )

        # MERGE — tablo bazlı strateji
        prefix = self._MERGE_STRATEGIES.get(table, "INSERT OR IGNORE")
        return self._import_with_stmt(
            con, table, rows, col_names, placeholders, prefix=prefix
        )

    def _import_replace(
        self,
        con,
        table: str,
        rows: list[dict],
        col_names: str,
        placeholders: str,
    ) -> tuple[int, int]:
        """REPLACE modu: tabloyu temizle + tüm satırları INSERT."""
        con.execute(f"DELETE FROM {table}")  # noqa: S608
        stmt = (
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})"  # noqa: S608
        )
        for row in rows:
            con.execute(stmt, list(row.values()))
        return len(rows), 0

    def _import_with_stmt(
        self,
        con,
        table: str,
        rows: list[dict],
        col_names: str,
        placeholders: str,
        prefix: str,
    ) -> tuple[int, int]:
        """Verilen INSERT prefix'iyle her satırı dener; rowcount ile inserted/skipped sayar."""
        stmt = (
            f"{prefix} INTO {table} ({col_names}) VALUES ({placeholders})"  # noqa: S608
        )
        inserted = 0
        skipped = 0
        for row in rows:
            cursor = con.execute(stmt, list(row.values()))
            if cursor.rowcount > 0:
                inserted += 1
            else:
                skipped += 1
        return inserted, skipped
