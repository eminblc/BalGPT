"""BACKUP-7 — /export ve /import komutları + _backup_import_handler unit testleri."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------

def _make_session(lang="tr", pending=False):
    from backend.app_types import SessionState
    s = SessionState()
    s["lang"] = lang
    if pending:
        s.set_pending_backup_import()
    return s


# ===========================================================================
# ExportCommand._resolve_scope
# ===========================================================================


class TestExportCommandScopeResolution:
    """ExportCommand._resolve_scope — alt komut → ExportScope eşlemesi."""

    def setup_method(self):
        from backend.guards.commands.export_cmd import ExportCommand
        self.cmd = ExportCommand()

    def test_empty_arg_returns_essential(self):
        scope = self.cmd._resolve_scope("")
        assert scope is not None
        assert scope.include_media is False
        assert scope.include_bridge_calls is False

    def test_essential_arg_returns_essential(self):
        scope = self.cmd._resolve_scope("essential")
        assert scope is not None
        assert scope.include_media is False

    def test_full_arg_returns_full(self):
        scope = self.cmd._resolve_scope("full")
        assert scope is not None
        assert scope.include_media is True
        assert scope.include_bridge_calls is True

    def test_media_arg_returns_media_scope(self):
        scope = self.cmd._resolve_scope("media")
        assert scope is not None
        assert scope.include_media is True

    def test_unknown_arg_returns_none(self):
        assert self.cmd._resolve_scope("unknown_sub") is None


# ===========================================================================
# ExportCommand.execute
# ===========================================================================


class TestExportCommandExecute:
    """ExportCommand.execute uçtan uca akış (ExportService mock)."""

    @pytest.mark.asyncio
    async def test_sends_start_message(self):
        """Export başlarken kullanıcıya bilgi mesajı gönderilmeli."""
        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()
        mock_messenger.send_document = AsyncMock()
        # MediaMessenger isinstance check için send_document + supports_media ekle
        mock_messenger.supports_media = True

        mock_manifest = MagicMock()
        mock_manifest.table_row_counts = {"t1": 10}
        mock_manifest.file_count = 2

        mock_service = AsyncMock()
        mock_service.create_backup = AsyncMock(return_value=mock_manifest)

        session = _make_session()

        mock_stat = MagicMock()
        mock_stat.st_size = 4096

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger), \
             patch("backend.features.export_service.get_export_service",
                   return_value=mock_service), \
             patch("pathlib.Path.stat", return_value=mock_stat), \
             patch("pathlib.Path.unlink", return_value=None):
            from backend.guards.commands.export_cmd import ExportCommand
            cmd = ExportCommand()
            await cmd.execute("sender", "", session)

        # start msg + caption (messenger MediaMessenger değilse send_text fallback)
        assert mock_messenger.send_text.call_count >= 1
        mock_service.create_backup.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_subcommand_sends_usage(self):
        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()
        session = _make_session()

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger):
            from backend.guards.commands.export_cmd import ExportCommand
            cmd = ExportCommand()
            await cmd.execute("sender", "unknown_sub", session)

        mock_messenger.send_text.assert_called_once()
        args = mock_messenger.send_text.call_args[0]
        text = args[1]
        assert "/export" in text or "Usage" in text or "Kullanım" in text

    @pytest.mark.asyncio
    async def test_service_error_sends_error_message(self):
        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()

        mock_service = AsyncMock()
        mock_service.create_backup = AsyncMock(side_effect=RuntimeError("disk full"))

        session = _make_session()

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger), \
             patch("backend.features.export_service.get_export_service",
                   return_value=mock_service):
            from backend.guards.commands.export_cmd import ExportCommand
            cmd = ExportCommand()
            await cmd.execute("sender", "", session)

        # İlk: export_start, ikinci: hata mesajı (hassas detay kullanıcıya gösterilmez)
        assert mock_messenger.send_text.call_count == 2
        error_msg = mock_messenger.send_text.call_args_list[-1][0][1]
        # Ham exception mesajı kullanıcıya gösterilmemeli (IMP-GUARD-13)
        assert "disk full" not in error_msg
        # Hata mesajı genel bir i18n anahtarına dayanmalı
        assert error_msg  # boş değil


class TestExportCommandRegistration:
    def test_registered_in_registry(self):
        import backend.guards.commands  # noqa
        from backend.guards.commands.registry import registry
        assert "/export" in registry.all_ids()

    def test_perm_is_owner(self):
        from backend.guards.commands.export_cmd import ExportCommand
        from backend.guards.permission import Perm
        assert ExportCommand.perm == Perm.OWNER

    def test_cmd_id(self):
        from backend.guards.commands.export_cmd import ExportCommand
        assert ExportCommand.cmd_id == "/export"


# ===========================================================================
# ImportCommand.execute
# ===========================================================================


class TestImportCommandExecute:
    @pytest.mark.asyncio
    async def test_sets_pending_backup_import_in_session(self):
        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()
        session = _make_session()

        assert not session.get("pending_backup_import")

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger):
            from backend.guards.commands.import_cmd import ImportCommand
            cmd = ImportCommand()
            await cmd.execute("sender", "", session)

        assert session.get("pending_backup_import") is True
        mock_messenger.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_sends_import_prompt(self):
        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()
        session = _make_session()

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger):
            from backend.guards.commands.import_cmd import ImportCommand
            cmd = ImportCommand()
            await cmd.execute("sender", "", session)

        sent_text = mock_messenger.send_text.call_args[0][1]
        assert ".99rb" in sent_text or "yedek" in sent_text.lower() or "backup" in sent_text.lower()

    @pytest.mark.asyncio
    async def test_arg_is_ignored(self):
        """Herhangi bir arg değeri için aynı davranış."""
        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()
        session = _make_session()

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger):
            from backend.guards.commands.import_cmd import ImportCommand
            cmd = ImportCommand()
            await cmd.execute("sender", "merge", session)  # arg ignored

        assert session.get("pending_backup_import") is True


class TestImportCommandRegistration:
    def test_registered_in_registry(self):
        import backend.guards.commands  # noqa
        from backend.guards.commands.registry import registry
        assert "/import" in registry.all_ids()

    def test_perm_is_owner(self):
        from backend.guards.commands.import_cmd import ImportCommand
        from backend.guards.permission import Perm
        assert ImportCommand.perm == Perm.OWNER

    def test_cmd_id(self):
        from backend.guards.commands.import_cmd import ImportCommand
        assert ImportCommand.cmd_id == "/import"


# ===========================================================================
# SessionState.pending_backup_import
# ===========================================================================


class TestSessionStatePendingBackupImport:
    def test_set_pending_backup_import(self):
        from backend.app_types import SessionState
        s = SessionState()
        assert not s.get("pending_backup_import")
        s.set_pending_backup_import()
        assert s.get("pending_backup_import") is True

    def test_clear_backup_import(self):
        from backend.app_types import SessionState
        s = SessionState()
        s.set_pending_backup_import()
        s.clear_backup_import()
        assert not s.get("pending_backup_import")

    def test_direct_assignment_raises(self):
        from backend.app_types import SessionState
        s = SessionState()
        with pytest.raises(AttributeError):
            s["pending_backup_import"] = True


# ===========================================================================
# _backup_import_handler
# ===========================================================================


class TestIsBackupPending:
    def test_true_when_flag_set(self):
        from backend.routers._backup_import_handler import is_backup_pending
        s = _make_session(pending=True)
        assert is_backup_pending(s) is True

    def test_false_when_not_set(self):
        from backend.routers._backup_import_handler import is_backup_pending
        s = _make_session()
        assert is_backup_pending(s) is False

    def test_false_after_clear(self):
        from backend.routers._backup_import_handler import is_backup_pending
        s = _make_session(pending=True)
        s.clear_backup_import()
        assert is_backup_pending(s) is False


class TestHandleBackupBytes:
    @pytest.mark.asyncio
    async def test_returns_false_when_not_pending(self):
        from backend.routers._backup_import_handler import handle_backup_bytes
        session = _make_session()
        result = await handle_backup_bytes("sender", "backup.99rb", b"data", session)
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_and_sends_error_for_wrong_extension(self):
        from backend.routers._backup_import_handler import handle_backup_bytes
        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()
        session = _make_session(pending=True)

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger):
            result = await handle_backup_bytes("sender", "wrong.zip", b"data", session)

        assert result is True
        mock_messenger.send_text.assert_called_once()
        msg = mock_messenger.send_text.call_args[0][1]
        assert ".99rb" in msg or "Invalid" in msg or "bekleniyor" in msg

    @pytest.mark.asyncio
    async def test_clears_flag_after_bad_extension(self):
        from backend.routers._backup_import_handler import handle_backup_bytes, is_backup_pending
        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()
        session = _make_session(pending=True)

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger):
            await handle_backup_bytes("sender", "bad.zip", b"data", session)

        assert not is_backup_pending(session)

    @pytest.mark.asyncio
    async def test_calls_import_service_on_valid_file(self):
        from backend.routers._backup_import_handler import handle_backup_bytes
        from backend.features.backup._protocol import ImportMode, ImportResult

        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()

        mock_result = MagicMock(spec=ImportResult)
        mock_result.rows_inserted = {"messages": 100, "work_plans": 5}
        mock_result.tables_processed = ["messages", "work_plans"]
        mock_result.rows_skipped = {}
        mock_result.errors = []

        mock_service = AsyncMock()
        mock_service.restore_backup = AsyncMock(return_value=mock_result)

        session = _make_session(pending=True)

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger), \
             patch("backend.features.import_service.get_import_service",
                   return_value=mock_service):
            result = await handle_backup_bytes("sender", "backup.99rb", b"fake", session)

        assert result is True
        mock_service.restore_backup.assert_called_once()
        call_path, call_mode = mock_service.restore_backup.call_args[0]
        assert call_mode == ImportMode.MERGE

    @pytest.mark.asyncio
    async def test_sends_ok_message_after_successful_import(self):
        from backend.routers._backup_import_handler import handle_backup_bytes
        from backend.features.backup._protocol import ImportResult

        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()

        mock_result = MagicMock(spec=ImportResult)
        mock_result.rows_inserted = {"messages": 50}
        mock_result.tables_processed = ["messages"]
        mock_result.rows_skipped = {}
        mock_result.errors = []

        mock_service = AsyncMock()
        mock_service.restore_backup = AsyncMock(return_value=mock_result)

        session = _make_session(pending=True)

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger), \
             patch("backend.features.import_service.get_import_service",
                   return_value=mock_service):
            await handle_backup_bytes("sender", "backup.99rb", b"fake", session)

        sent = mock_messenger.send_text.call_args[0][1]
        assert "50" in sent or "tamamlandı" in sent.lower() or "complete" in sent.lower()

    @pytest.mark.asyncio
    async def test_sends_error_on_value_error(self):
        from backend.routers._backup_import_handler import handle_backup_bytes

        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()

        mock_service = AsyncMock()
        mock_service.restore_backup = AsyncMock(side_effect=ValueError("bad checksum"))

        session = _make_session(pending=True)

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger), \
             patch("backend.features.import_service.get_import_service",
                   return_value=mock_service):
            result = await handle_backup_bytes("sender", "backup.99rb", b"bad", session)

        assert result is True
        sent = mock_messenger.send_text.call_args[0][1]
        assert "bad checksum" in sent

    @pytest.mark.asyncio
    async def test_clears_flag_after_successful_import(self):
        from backend.routers._backup_import_handler import handle_backup_bytes, is_backup_pending
        from backend.features.backup._protocol import ImportResult

        mock_messenger = AsyncMock()
        mock_messenger.send_text = AsyncMock()

        mock_result = MagicMock(spec=ImportResult)
        mock_result.rows_inserted = {}
        mock_result.tables_processed = []
        mock_result.rows_skipped = {}
        mock_result.errors = []

        mock_service = AsyncMock()
        mock_service.restore_backup = AsyncMock(return_value=mock_result)

        session = _make_session(pending=True)

        with patch("backend.adapters.messenger.get_messenger",
                   return_value=mock_messenger), \
             patch("backend.features.import_service.get_import_service",
                   return_value=mock_service):
            await handle_backup_bytes("sender", "backup.99rb", b"fake", session)

        assert not is_backup_pending(session)
