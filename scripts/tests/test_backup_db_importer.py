"""DbImporter unit testleri — DB bağımlılığı mock'lanır.

Test stratejisi:
  - _sync_import ve _import_table metodları doğrudan test edilir.
  - _conn() context manager patch ile sahte bağlantı nesnesine yönlendirilir.
  - snapshot (_take_snapshot) patch ile izole edilir.
  - asyncio.to_thread patch ile async sarmalayıcılar test edilir.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from backend.features.backup._db_importer import DbImporter, _SNAPSHOT_PATH
from backend.features.backup._protocol import ImportMode, ImportResult


# ---------------------------------------------------------------------------
# Fixture yardımcıları
# ---------------------------------------------------------------------------


def _make_importer() -> DbImporter:
    return DbImporter()


def _make_con_mock(rowcount: int = 1):
    """Sahte sqlite3.Connection döndürür; execute().rowcount ayarlanabilir."""
    con = MagicMock()
    cursor = MagicMock()
    cursor.rowcount = rowcount
    con.execute.return_value = cursor
    return con


# ---------------------------------------------------------------------------
# _take_snapshot testleri
# ---------------------------------------------------------------------------


class TestTakeSnapshot:
    def test_copies_db_when_exists(self, tmp_path):
        src = tmp_path / "personal_agent.db"
        src.write_bytes(b"fake-db")

        importer = _make_importer()

        with (
            patch(
                "backend.features.backup._db_importer._resolve_db_path",
                return_value=src,
            ),
            patch("backend.features.backup._db_importer.shutil.copy2") as mock_copy,
        ):
            importer._take_snapshot()

        mock_copy.assert_called_once_with(src, _SNAPSHOT_PATH)

    def test_skips_when_db_missing(self, tmp_path):
        missing = tmp_path / "nonexistent.db"
        importer = _make_importer()

        with (
            patch(
                "backend.features.backup._db_importer._resolve_db_path",
                return_value=missing,
            ),
            patch("backend.features.backup._db_importer.shutil.copy2") as mock_copy,
        ):
            importer._take_snapshot()  # hata fırlatmamalı

        mock_copy.assert_not_called()


# ---------------------------------------------------------------------------
# _import_table — REPLACE modu
# ---------------------------------------------------------------------------


class TestImportTableReplace:
    def test_deletes_then_inserts(self):
        importer = _make_importer()
        con = _make_con_mock(rowcount=1)
        rows = [{"id": "1", "name": "foo"}, {"id": "2", "name": "bar"}]

        inserted, skipped = importer._import_table(con, "projects", rows, ImportMode.REPLACE)

        # DELETE çağrısı yapılmalı
        assert call("DELETE FROM projects") in con.execute.call_args_list
        assert inserted == 2
        assert skipped == 0

    def test_returns_zero_skipped(self):
        importer = _make_importer()
        con = _make_con_mock(rowcount=1)
        rows = [{"id": "x"}]

        _, skipped = importer._import_table(con, "messages", rows, ImportMode.REPLACE)

        assert skipped == 0


# ---------------------------------------------------------------------------
# _import_table — SKIP_EXISTING modu
# ---------------------------------------------------------------------------


class TestImportTableSkipExisting:
    def test_counts_inserted_and_skipped(self):
        importer = _make_importer()
        con = MagicMock()
        # İlk satır eklendi (rowcount=1), ikinci atlandı (rowcount=0)
        cursor1, cursor2 = MagicMock(), MagicMock()
        cursor1.rowcount = 1
        cursor2.rowcount = 0
        con.execute.side_effect = [cursor1, cursor2]

        rows = [{"id": "1"}, {"id": "1"}]  # ikincisi duplicate
        inserted, skipped = importer._import_table(
            con, "messages", rows, ImportMode.SKIP_EXISTING
        )

        assert inserted == 1
        assert skipped == 1

    def test_uses_insert_or_ignore(self):
        importer = _make_importer()
        con = _make_con_mock(rowcount=1)
        rows = [{"id": "abc"}]

        importer._import_table(con, "projects", rows, ImportMode.SKIP_EXISTING)

        stmt_called = con.execute.call_args_list[0][0][0]
        assert "INSERT OR IGNORE" in stmt_called


# ---------------------------------------------------------------------------
# _import_table — MERGE modu (tablo bazlı strateji)
# ---------------------------------------------------------------------------


class TestImportTableMerge:
    @pytest.mark.parametrize(
        "table, expected_prefix",
        [
            ("projects", "INSERT OR REPLACE"),
            ("work_plans", "INSERT OR REPLACE"),
            ("calendar_events", "INSERT OR REPLACE"),
            ("scheduled_tasks", "INSERT OR REPLACE"),
            ("user_settings", "INSERT OR REPLACE"),
            ("messages", "INSERT OR IGNORE"),
            ("session_summaries", "INSERT OR IGNORE"),
            ("bridge_calls", "INSERT OR IGNORE"),
            ("token_usage", "INSERT OR IGNORE"),
        ],
    )
    def test_correct_strategy_per_table(self, table: str, expected_prefix: str):
        importer = _make_importer()
        con = _make_con_mock(rowcount=1)
        rows = [{"id": "1"}]

        importer._import_table(con, table, rows, ImportMode.MERGE)

        stmt_called = con.execute.call_args_list[0][0][0]
        assert expected_prefix in stmt_called, (
            f"{table}: beklenen '{expected_prefix}', alınan '{stmt_called}'"
        )

    def test_unknown_table_defaults_to_insert_or_ignore(self):
        importer = _make_importer()
        con = _make_con_mock(rowcount=1)
        rows = [{"id": "x"}]

        importer._import_table(con, "unknown_table", rows, ImportMode.MERGE)

        stmt_called = con.execute.call_args_list[0][0][0]
        assert "INSERT OR IGNORE" in stmt_called


# ---------------------------------------------------------------------------
# _sync_import — bütünleşik testler
# ---------------------------------------------------------------------------


class TestSyncImport:
    def _patch_conn(self, con):
        """_conn() context manager'ı verilen con nesnesiyle patch'ler."""
        from contextlib import contextmanager

        @contextmanager
        def fake_conn():
            yield con

        return patch("backend.features.backup._db_importer._conn", fake_conn)

    def test_skip_tables_are_excluded(self):
        importer = _make_importer()
        con = _make_con_mock(rowcount=0)
        data = {
            "totp_lockouts": [{"id": "1"}],
            "seen_messages": [{"msg_id": "abc"}],
        }

        with self._patch_conn(con):
            result = importer._sync_import(data, ImportMode.MERGE)

        # Hiçbir tablo işlenmemeli
        assert result.tables_processed == []
        # Hiçbir satır eklenmemeli
        assert result.rows_inserted == {}

    def test_empty_rows_processed_with_zero_counts(self):
        importer = _make_importer()
        con = _make_con_mock(rowcount=0)
        data = {"projects": []}

        with self._patch_conn(con):
            result = importer._sync_import(data, ImportMode.MERGE)

        assert "projects" in result.tables_processed
        assert result.rows_inserted["projects"] == 0
        assert result.rows_skipped["projects"] == 0

    def test_non_list_value_adds_error(self):
        importer = _make_importer()
        con = _make_con_mock(rowcount=0)
        data = {"projects": "not-a-list"}  # type: ignore[dict-item]

        with self._patch_conn(con):
            result = importer._sync_import(data, ImportMode.MERGE)

        assert any("projects" in err for err in result.errors)

    def test_exception_in_table_adds_error(self):
        importer = _make_importer()
        con = MagicMock()
        con.execute.side_effect = Exception("DB constraint")
        data = {"messages": [{"id": "1", "text": "hi"}]}

        with self._patch_conn(con):
            result = importer._sync_import(data, ImportMode.MERGE)

        assert any("messages" in err for err in result.errors)

    def test_merge_mode_inserts_rows(self):
        importer = _make_importer()
        con = _make_con_mock(rowcount=1)
        data = {"work_plans": [{"id": "1", "title": "plan"}]}

        with self._patch_conn(con):
            result = importer._sync_import(data, ImportMode.MERGE)

        assert result.rows_inserted.get("work_plans") == 1

    def test_replace_mode_deletes_first(self):
        importer = _make_importer()
        con = _make_con_mock(rowcount=1)
        data = {"projects": [{"id": "1", "name": "p"}]}

        with self._patch_conn(con):
            importer._sync_import(data, ImportMode.REPLACE)

        calls = [str(c) for c in con.execute.call_args_list]
        assert any("DELETE FROM projects" in c for c in calls)


# ---------------------------------------------------------------------------
# import_data — async wrapper testi
# ---------------------------------------------------------------------------


class TestImportDataAsync:
    @pytest.mark.asyncio
    async def test_calls_snapshot_and_sync_import(self):
        importer = _make_importer()
        data = {"messages": []}
        mode = ImportMode.MERGE
        expected_result = ImportResult(tables_processed=["messages"])

        with (
            patch.object(importer, "_take_snapshot") as mock_snap,
            patch.object(
                importer, "_sync_import", return_value=expected_result
            ) as mock_sync,
            patch("backend.features.backup._db_importer.asyncio.to_thread") as mock_thread,
        ):
            # asyncio.to_thread'i doğrudan çağırır gibi simüle et
            async def fake_to_thread(fn, *args):
                return fn(*args)

            mock_thread.side_effect = fake_to_thread

            result = await importer.import_data(data, mode)

        mock_snap.assert_called_once()
        mock_sync.assert_called_once_with(data, mode)
        assert result is expected_result

    @pytest.mark.asyncio
    async def test_returns_import_result(self):
        importer = _make_importer()

        with (
            patch.object(importer, "_take_snapshot"),
            patch.object(
                importer,
                "_sync_import",
                return_value=ImportResult(tables_processed=["projects"], rows_inserted={"projects": 3}),
            ),
            patch("backend.features.backup._db_importer.asyncio.to_thread") as mock_thread,
        ):
            async def fake_to_thread(fn, *args):
                return fn(*args)

            mock_thread.side_effect = fake_to_thread

            result = await importer.import_data({}, ImportMode.REPLACE)

        assert "projects" in result.tables_processed
        assert result.rows_inserted["projects"] == 3


# ---------------------------------------------------------------------------
# SKIP_TABLES sınıf değişkeni testi
# ---------------------------------------------------------------------------


class TestSkipTables:
    def test_contains_totp_lockouts(self):
        assert "totp_lockouts" in DbImporter._SKIP_TABLES

    def test_contains_seen_messages(self):
        assert "seen_messages" in DbImporter._SKIP_TABLES

    def test_is_frozenset(self):
        assert isinstance(DbImporter._SKIP_TABLES, frozenset)


# ---------------------------------------------------------------------------
# MERGE_STRATEGIES sınıf değişkeni testi
# ---------------------------------------------------------------------------


class TestMergeStrategies:
    def test_all_expected_tables_present(self):
        expected = {
            "projects", "messages", "session_summaries", "work_plans",
            "calendar_events", "scheduled_tasks", "user_settings",
            "bridge_calls", "token_usage",
        }
        assert expected == set(DbImporter._MERGE_STRATEGIES.keys())

    def test_no_skip_tables_in_strategies(self):
        for skip in DbImporter._SKIP_TABLES:
            assert skip not in DbImporter._MERGE_STRATEGIES
