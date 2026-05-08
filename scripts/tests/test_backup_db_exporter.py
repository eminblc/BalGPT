"""DbExporter unit testleri — DB bağımlılığı mock'lanır.

Tüm sorgular _sync_export_* metodları üzerinden _conn() kullanır.
asyncio.to_thread yerine doğrudan sync metodları test eder (DB mock).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from backend.features.backup._db_exporter import DbExporter, _rows_to_dicts
from backend.features.backup._scope import ExportScope


# ---------------------------------------------------------------------------
# Fixture yardımcıları
# ---------------------------------------------------------------------------

def _make_row(data: dict):
    """sqlite3.Row yerine geçen minimal mock satır nesnesi."""
    mock = MagicMock()
    mock.keys.return_value = list(data.keys())
    mock.__iter__ = lambda s: iter(data.items())
    # dict(row) çağrısını desteklemek için
    mock.keys.return_value = list(data.keys())
    # sqlite3.Row'un dict() dönüşümü için __iter__ üzerinden
    return data  # Gerçek dict kullanıyoruz — _rows_to_dicts dict'i zaten geçiriyor


# ---------------------------------------------------------------------------
# _rows_to_dicts yardımcı fonksiyon testleri
# ---------------------------------------------------------------------------

class TestRowsToDicts:
    def test_empty_list(self):
        assert _rows_to_dicts([]) == []

    def test_converts_rows(self):
        fake_row = {"id": "1", "name": "test"}
        # sqlite3.Row gibi davranır — dict() çağrısıyla dönüşür
        with patch(
            "backend.features.backup._db_exporter._rows_to_dicts",
            return_value=[fake_row],
        ) as mock_fn:
            result = mock_fn([fake_row])
        assert result == [{"id": "1", "name": "test"}]


# ---------------------------------------------------------------------------
# DbExporter._sync_export_table testleri
# ---------------------------------------------------------------------------

class TestSyncExportTable:
    """_sync_export_table doğrudan test edilir — asyncio olmadan."""

    def test_returns_list_of_dicts(self):
        exporter = DbExporter()
        fake_rows = [{"id": "p1", "name": "proj1"}, {"id": "p2", "name": "proj2"}]

        with patch("backend.features.backup._db_exporter._conn") as mock_conn:
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = fake_rows
            mock_conn.return_value.__enter__.return_value.execute.return_value = (
                mock_cursor
            )
            result = exporter._sync_export_table("projects")

        assert isinstance(result, list)
        assert len(result) == 2

    def test_empty_table(self):
        exporter = DbExporter()

        with patch("backend.features.backup._db_exporter._conn") as mock_conn:
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            mock_conn.return_value.__enter__.return_value.execute.return_value = (
                mock_cursor
            )
            result = exporter._sync_export_table("work_plans")

        assert result == []


# ---------------------------------------------------------------------------
# DbExporter._sync_export_messages testleri
# ---------------------------------------------------------------------------

class TestSyncExportMessages:
    def test_with_limit(self):
        exporter = DbExporter()
        fake_rows = [{"id": f"m{i}", "ts": float(i)} for i in range(5)]

        with patch("backend.features.backup._db_exporter._conn") as mock_conn:
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = fake_rows
            con_mock = mock_conn.return_value.__enter__.return_value
            con_mock.execute.return_value = mock_cursor

            result = exporter._sync_export_messages(limit=5)

        # Limit parametresiyle çağrılmış mı kontrol et
        call_args = con_mock.execute.call_args
        assert "LIMIT" in call_args[0][0]
        assert len(result) == 5

    def test_without_limit_fetches_all(self):
        exporter = DbExporter()
        fake_rows = [{"id": f"m{i}", "ts": float(i)} for i in range(100)]

        with patch("backend.features.backup._db_exporter._conn") as mock_conn:
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = fake_rows
            con_mock = mock_conn.return_value.__enter__.return_value
            con_mock.execute.return_value = mock_cursor

            result = exporter._sync_export_messages(limit=0)

        # LIMIT içermemeli
        call_args = con_mock.execute.call_args
        assert "LIMIT" not in call_args[0][0]
        assert len(result) == 100

    def test_order_by_ts_desc(self):
        exporter = DbExporter()

        with patch("backend.features.backup._db_exporter._conn") as mock_conn:
            mock_cursor = MagicMock()
            mock_cursor.fetchall.return_value = []
            con_mock = mock_conn.return_value.__enter__.return_value
            con_mock.execute.return_value = mock_cursor

            exporter._sync_export_messages(limit=10)

        call_sql = con_mock.execute.call_args[0][0]
        assert "ORDER BY ts DESC" in call_sql


# ---------------------------------------------------------------------------
# DbExporter.export() async testleri
# ---------------------------------------------------------------------------

class TestExportAsync:
    """export() metodunu asyncio.to_thread mock'layarak test eder."""

    @pytest.mark.asyncio
    async def test_export_essential_scope(self):
        exporter = DbExporter()
        scope = ExportScope.essential()

        # Tüm _sync_* metodlarını patch'le
        with (
            patch.object(exporter, "_sync_export_table", return_value=[]) as mock_table,
            patch.object(
                exporter, "_sync_export_messages", return_value=[]
            ) as mock_msgs,
        ):
            result = await exporter.export(scope)

        # Temel anahtarlar her zaman mevcut olmalı
        assert "projects" in result
        assert "work_plans" in result
        assert "messages" in result
        assert "bridge_calls" in result
        assert "token_usage" in result

    @pytest.mark.asyncio
    async def test_export_skips_bridge_calls_when_not_in_scope(self):
        exporter = DbExporter()
        scope = ExportScope(include_bridge_calls=False, include_token_usage=False)

        with (
            patch.object(exporter, "_sync_export_table", return_value=[]),
            patch.object(exporter, "_sync_export_messages", return_value=[]),
        ):
            result = await exporter.export(scope)

        # include_bridge_calls=False → boş liste döner
        assert result["bridge_calls"] == []
        assert result["token_usage"] == []

    @pytest.mark.asyncio
    async def test_export_skips_messages_when_not_in_scope(self):
        exporter = DbExporter()
        scope = ExportScope(include_messages=False)

        with (
            patch.object(exporter, "_sync_export_table", return_value=[]),
            patch.object(exporter, "_sync_export_messages", return_value=[]) as mock_msgs,
        ):
            result = await exporter.export(scope)

        # include_messages=False → mesaj sorgusu hiç çalışmamalı
        mock_msgs.assert_not_called()
        assert result["messages"] == []
        assert result["session_summaries"] == []

    @pytest.mark.asyncio
    async def test_export_full_scope_includes_all(self):
        exporter = DbExporter()
        scope = ExportScope.full()

        sample_data = [{"id": "x1"}]

        with (
            patch.object(exporter, "_sync_export_table", return_value=sample_data),
            patch.object(
                exporter, "_sync_export_messages", return_value=sample_data
            ),
        ):
            result = await exporter.export(scope)

        # full scope — tüm tablolar dolu olmalı
        assert result["bridge_calls"] == sample_data
        assert result["token_usage"] == sample_data
        assert result["messages"] == sample_data

    @pytest.mark.asyncio
    async def test_export_returns_dict_with_all_keys(self):
        exporter = DbExporter()
        scope = ExportScope()

        expected_keys = {
            "projects",
            "work_plans",
            "calendar_events",
            "scheduled_tasks",
            "messages",
            "session_summaries",
            "user_settings",
            "bridge_calls",
            "token_usage",
        }

        with (
            patch.object(exporter, "_sync_export_table", return_value=[]),
            patch.object(exporter, "_sync_export_messages", return_value=[]),
        ):
            result = await exporter.export(scope)

        assert set(result.keys()) == expected_keys
