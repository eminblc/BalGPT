"""CommandRegistry ve tüm !komut handler'larının davranış testleri."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture(autouse=True)
def reset_messenger_singleton():
    """Her test öncesi messenger singleton'ını sıfırla."""
    import backend.adapters.messenger.messenger_factory as mf
    mf._instance = None
    yield
    mf._instance = None


# ── CommandRegistry ────────────────────────────────────────────────

def test_registry_register_and_get():
    from backend.guards.commands.registry import CommandRegistry
    from backend.guards.permission import Perm

    class _Cmd:
        cmd_id = "!test"
        perm   = Perm.OWNER
        async def execute(self, sender, arg, session): ...

    reg = CommandRegistry()
    reg.register(_Cmd())
    assert reg.get("!test") is not None
    assert reg.get("!missing") is None


def test_registry_all_ids():
    from backend.guards.commands.registry import CommandRegistry
    from backend.guards.permission import Perm

    class _A:
        cmd_id = "!a"; perm = Perm.OWNER
        async def execute(self, s, a, se): ...

    class _B:
        cmd_id = "!b"; perm = Perm.OWNER
        async def execute(self, s, a, se): ...

    reg = CommandRegistry()
    reg.register(_A()); reg.register(_B())
    assert set(reg.all_ids()) == {"!a", "!b"}


def test_registry_reject_missing_perm():
    from backend.guards.commands.registry import CommandRegistry

    class _NoPerm:
        cmd_id = "!noperm"
        async def execute(self, s, a, se): ...

    reg = CommandRegistry()
    with pytest.raises(TypeError, match="perm"):
        reg.register(_NoPerm())


def test_registry_describe_returns_metadata():
    from backend.guards.commands.registry import CommandRegistry
    from backend.guards.permission import Perm

    class _Described:
        cmd_id      = "!described"
        perm        = Perm.OWNER
        label       = "Test Label"
        description = "Açıklama"
        usage       = "!described [arg]"
        async def execute(self, s, a, se): ...

    reg = CommandRegistry()
    reg.register(_Described())
    info = reg.describe("!described")
    assert info["label"] == "Test Label"
    assert info["description"] == "Açıklama"
    assert info["usage"] == "!described [arg]"


def test_registry_describe_unknown_returns_none():
    from backend.guards.commands.registry import CommandRegistry
    reg = CommandRegistry()
    assert reg.describe("!notregistered") is None


def test_registry_describe_defaults_without_attrs():
    from backend.guards.commands.registry import CommandRegistry
    from backend.guards.permission import Perm

    class _Minimal:
        cmd_id = "!min"; perm = Perm.OWNER
        async def execute(self, s, a, se): ...

    reg = CommandRegistry()
    reg.register(_Minimal())
    info = reg.describe("!min")
    assert info["label"] == "!min"  # cmd_id fallback
    assert info["description"] == ""
    assert info["usage"] == "!min"


# ── Singleton registry'de komutların kaydı ─────────────────────────

def test_known_commands_registered():
    """Tüm bilinen komutların singleton registry'e kayıtlı olduğunu doğrular."""
    import backend.guards.commands  # noqa — tüm komutları import et
    from backend.guards.commands.registry import registry

    expected = {
        "/help", "/history", "/lang", "/lock", "/unlock",
        "/model", "/cancel", "/root-reset", "/project", "/schedule",
        "/restart", "/shutdown", "/root-project", "/root-exit",
        "/beta", "/root-check", "/root-log", "/project-delete",
        "/terminal", "/timezone", "/tokens",
    }
    registered = set(registry.all_ids())
    missing = expected - registered
    assert not missing, f"Kayıtlı olmayan komutlar: {missing}"


# ── !lang komutu ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lang_valid_change():
    mock_messenger = AsyncMock()
    mock_setting   = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.guards.commands.lang_cmd.LangCommand.execute",
               wraps=None) as _:
        pass  # import guard

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.store.repositories.settings_repo.user_setting_set",
               mock_setting):
        from backend.guards.commands.lang_cmd import LangCommand
        await LangCommand().execute("905001234567", "en", session)

    assert session["lang"] == "en"
    mock_messenger.send_text.assert_awaited_once()
    mock_setting.assert_awaited_once_with("905001234567", "lang", "en")


@pytest.mark.asyncio
async def test_lang_invalid_code():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger):
        from backend.guards.commands.lang_cmd import LangCommand
        await LangCommand().execute("905001234567", "fr", session)

    assert session.get("lang") == "tr"  # değişmemeli
    mock_messenger.send_text.assert_awaited_once()


# ── !lock / !unlock ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lock_sets_locked_true():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.runtime_state.set_locked") as mock_set:
        from backend.guards.commands.lock_cmd import LockCommand
        await LockCommand().execute("905001234567", "", session)

    mock_set.assert_called_once_with(True)
    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_unlock_sets_locked_false():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.runtime_state.set_locked") as mock_set:
        from backend.guards.commands.unlock_cmd import UnlockCommand
        await UnlockCommand().execute("905001234567", "", session)

    mock_set.assert_called_once_with(False)
    mock_messenger.send_text.assert_awaited_once()


# ── !model komutu ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_model_no_arg_shows_current():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    mock_settings = MagicMock()
    mock_settings.llm_backend = "anthropic"
    mock_settings.default_model = "claude-sonnet-4-6"

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.config.settings", mock_settings), \
         patch("backend.guards.runtime_state.get_active_model", return_value=None):
        from backend.guards.commands.model_cmd import ModelCommand
        await ModelCommand().execute("905001234567", "", session)

    mock_messenger.send_buttons.assert_awaited_once()
    body = mock_messenger.send_buttons.call_args[0][1]
    buttons = mock_messenger.send_buttons.call_args[0][2]
    assert "claude-sonnet-4-6" in body
    assert len(buttons) == 3
    assert any(b["id"] == "model_select_sonnet" for b in buttons)


@pytest.mark.asyncio
async def test_model_alias_change():
    mock_messenger = AsyncMock()
    mock_setting   = AsyncMock()
    session = {"lang": "tr"}

    mock_settings = MagicMock()
    mock_settings.llm_backend = "anthropic"
    mock_settings.default_model = "claude-sonnet-4-6"

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.config.settings", mock_settings), \
         patch("backend.guards.runtime_state.get_active_model",
               return_value="claude-sonnet-4-6"), \
         patch("backend.guards.runtime_state.set_active_model") as mock_set_model, \
         patch("backend.store.repositories.settings_repo.user_setting_set", mock_setting):
        from backend.guards.commands.model_cmd import ModelCommand
        await ModelCommand().execute("905001234567", "haiku", session)

    mock_set_model.assert_called_once_with("claude-haiku-4-5-20251001")


@pytest.mark.asyncio
async def test_model_already_active():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    mock_settings = MagicMock()
    mock_settings.llm_backend = "anthropic"
    mock_settings.default_model = "claude-sonnet-4-6"

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.config.settings", mock_settings), \
         patch("backend.guards.runtime_state.get_active_model",
               return_value="claude-sonnet-4-6"):
        from backend.guards.commands.model_cmd import ModelCommand
        await ModelCommand().execute("905001234567", "sonnet", session)

    msg = mock_messenger.send_text.call_args[0][1]
    assert "claude-sonnet-4-6" in msg


# ── !cancel komutu ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancel_clears_auth_state():
    mock_messenger = AsyncMock()
    session = {
        "awaiting_totp": True,
        "pending_command": "/shutdown",
        "lang": "tr",
    }

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger):
        from backend.guards.commands.cancel_cmd import CancelCommand
        await CancelCommand().execute("905001234567", "", session)

    assert not session.get("awaiting_totp")
    assert not session.get("pending_command")
    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert msg  # bir şey söyledi


@pytest.mark.asyncio
async def test_cancel_no_pending_tries_bridge():
    mock_messenger = AsyncMock()
    session = {"lang": "tr", "active_context": "main"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.commands.cancel_cmd._cancel_bridge_query",
               AsyncMock(return_value=False)):
        from backend.guards.commands.cancel_cmd import CancelCommand
        await CancelCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_bridge_ok():
    mock_messenger = AsyncMock()
    session = {"lang": "tr", "active_context": "main"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.commands.cancel_cmd._cancel_bridge_query",
               AsyncMock(return_value=True)):
        from backend.guards.commands.cancel_cmd import CancelCommand
        await CancelCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()


# ── !root-reset komutu ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_root_reset_ok():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.features.chat.reset_bridge_session", AsyncMock(return_value=True)), \
         patch("backend.features.project_wizard.clear_wizard"):
        from backend.guards.commands.root_reset_cmd import RootResetCommand
        await RootResetCommand().execute("905001234567", "", session)

    assert mock_messenger.send_text.await_count == 2  # başlıyor + tamam


@pytest.mark.asyncio
async def test_root_reset_failed():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.features.chat.reset_bridge_session", AsyncMock(return_value=False)), \
         patch("backend.features.project_wizard.clear_wizard"):
        from backend.guards.commands.root_reset_cmd import RootResetCommand
        await RootResetCommand().execute("905001234567", "", session)

    assert mock_messenger.send_text.await_count == 2  # başlıyor + hata


# ── !history komutu ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_history_messages():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.features.history.get_recent_messages", AsyncMock(return_value=[])), \
         patch("backend.features.history.format_history", return_value="Geçmiş yok"):
        from backend.guards.commands.history_cmd import HistoryCommand
        await HistoryCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_summary():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.features.history.get_session_summaries", AsyncMock(return_value=[])), \
         patch("backend.features.history.format_summaries", return_value="Özet yok"):
        from backend.guards.commands.history_cmd import HistoryCommand
        await HistoryCommand().execute("905001234567", "özet", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_history_custom_limit():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    captured = {}

    async def fake_get(sender, limit=15):
        captured["limit"] = limit
        return []

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.features.history.get_recent_messages", fake_get), \
         patch("backend.features.history.format_history", return_value=""):
        from backend.guards.commands.history_cmd import HistoryCommand
        await HistoryCommand().execute("905001234567", "5", session)

    assert captured["limit"] == 5


# ── !project komutu ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_project_focus_clear():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.session_mgr.set_active_project") as mock_set, \
         patch("backend.features.projects.update_active_context_project"):
        from backend.guards.commands.project_focus_cmd import ProjectFocusCommand
        await ProjectFocusCommand().execute("905001234567", "none", session)

    mock_set.assert_called_once_with("905001234567", None)
    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_project_focus_not_found():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.store.sqlite_store.project_get", AsyncMock(return_value=None)):
        from backend.guards.commands.project_focus_cmd import ProjectFocusCommand
        await ProjectFocusCommand().execute("905001234567", "missing-id", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "missing-id" in msg


@pytest.mark.asyncio
async def test_project_focus_set_ok():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    fake_project = {"id": "my-proj", "name": "My Project"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.store.sqlite_store.project_get", AsyncMock(return_value=fake_project)), \
         patch("backend.guards.session_mgr.set_active_project") as mock_set, \
         patch("backend.features.projects.update_active_context_project"):
        from backend.guards.commands.project_focus_cmd import ProjectFocusCommand
        await ProjectFocusCommand().execute("905001234567", "my-proj", session)

    mock_set.assert_called_once_with("905001234567", "my-proj")
    msg = mock_messenger.send_text.call_args[0][1]
    assert "My Project" in msg


# ── !beta-exit komutu ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_beta_exit_already_main():
    mock_messenger = AsyncMock()
    session = {"lang": "tr", "active_context": "main"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger):
        from backend.guards.commands.beta_exit import BetaExitCommand
        await BetaExitCommand().execute("905001234567", "", session)

    msg = mock_messenger.send_text.call_args[0][1]
    assert msg  # mesaj gönderildi


@pytest.mark.asyncio
async def test_beta_exit_from_beta_context():
    mock_messenger = AsyncMock()
    session = {"lang": "tr", "active_context": "project:my-app", "beta_project_id": "my-app"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.session_mgr.exit_beta") as mock_exit:
        from backend.guards.commands.beta_exit import BetaExitCommand
        await BetaExitCommand().execute("905001234567", "", session)

    mock_exit.assert_called_once_with("905001234567")
    mock_messenger.send_text.assert_awaited_once()


# ── !root-exit komutu ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_root_exit_no_project_set(tmp_path):
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    ctx_file = tmp_path / "active_context.json"
    ctx_file.write_text("{}", encoding="utf-8")

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.commands.root_exit_cmd._ACTIVE_CONTEXT_PATH", ctx_file):
        from backend.guards.commands.root_exit_cmd import RootExitCommand
        await RootExitCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_root_exit_clears_project(tmp_path):
    import json
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    ctx_file = tmp_path / "active_context.json"
    ctx_file.write_text(
        json.dumps({"active_root_project": {"name": "Test", "path": "/tmp/test"}}),
        encoding="utf-8",
    )

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.commands.root_exit_cmd._ACTIVE_CONTEXT_PATH", ctx_file), \
         patch("backend.features.chat.reset_bridge_session", AsyncMock(return_value=True)):
        from backend.guards.commands.root_exit_cmd import RootExitCommand
        await RootExitCommand().execute("905001234567", "", session)

    updated = json.loads(ctx_file.read_text())
    assert "active_root_project" not in updated
    mock_messenger.send_text.assert_awaited_once()


# ── !schedule komutu ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_schedule_list_empty():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.features.scheduler.list_cron_jobs", return_value=[]):
        from backend.guards.commands.schedule_cmd import ScheduleCommand
        await ScheduleCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_unknown_subcommand():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger):
        from backend.guards.commands.schedule_cmd import ScheduleCommand
        await ScheduleCommand().execute("905001234567", "bilinmeyen", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_remove_no_prefix():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger):
        from backend.guards.commands.schedule_cmd import ScheduleCommand
        await ScheduleCommand().execute("905001234567", "sil", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_add_bad_format():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger):
        from backend.guards.commands.schedule_cmd import ScheduleCommand
        # Eksik cron alanları
        await ScheduleCommand().execute("905001234567", "ekle 0 9", session)

    mock_messenger.send_text.assert_awaited_once()


# ── !help komutu ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_help_full_menu():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.runtime_state.get_active_model", return_value=None), \
         patch("backend.config.settings") as mock_settings:
        mock_settings.llm_backend = "anthropic"
        mock_settings.default_model = "claude-sonnet-4-6"
        from backend.guards.commands.help_cmd import HelpCommand
        await HelpCommand().execute("905001234567", "", session)

    # Hem butonlar hem liste gönderilmeli
    assert mock_messenger.send_buttons.await_count >= 1


@pytest.mark.asyncio
async def test_help_single_cmd_known():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger):
        from backend.guards.commands.help_cmd import HelpCommand
        await HelpCommand().execute("905001234567", "/restart", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "restart" in msg.lower() or "Restart" in msg


@pytest.mark.asyncio
async def test_help_single_cmd_unknown():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger):
        from backend.guards.commands.help_cmd import HelpCommand
        await HelpCommand().execute("905001234567", "/nonexistent", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "/nonexistent" in msg


# ── !restart komutu ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_restart_sends_notification_and_fires_task():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    task_mock = MagicMock()

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("asyncio.create_task", return_value=task_mock) as mock_create_task:
        from backend.guards.commands.restart_cmd import RestartCommand
        await RestartCommand().execute("905001234567", "", session)

    mock_create_task.assert_called_once()
    task_mock.add_done_callback.assert_called_once()
    mock_messenger.send_text.assert_awaited_once()


# ── !shutdown komutu ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shutdown_sends_ok_and_kills_process():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("os.kill") as mock_kill:
        from backend.guards.commands.shutdown_cmd import ShutdownCommand
        import signal
        await ShutdownCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()
    mock_kill.assert_called_once()
    args = mock_kill.call_args[0]
    assert args[1] == signal.SIGTERM


# ── !root-check komutu ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_root_check_no_data():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    empty_summary = {"last_in": None, "last_bridge": None, "last_out": None}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("asyncio.to_thread", return_value=empty_summary):
        from backend.guards.commands.root_check_cmd import RootCheckCommand
        await RootCheckCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_root_check_with_data():
    import time
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    now = time.time()

    summary = {
        "last_in":     {"ts": now - 10, "content": "test", "msg_type": "text"},
        "last_bridge": {"ts": now - 5,  "success": 1},
        "last_out":    {"ts": now - 3},
    }

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("asyncio.to_thread", return_value=summary):
        from backend.guards.commands.root_check_cmd import RootCheckCommand
        await RootCheckCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert msg  # boş mesaj olmamalı


@pytest.mark.asyncio
async def test_root_check_db_error():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("asyncio.to_thread", side_effect=RuntimeError("db bağlantı hatası")):
        from backend.guards.commands.root_check_cmd import RootCheckCommand
        await RootCheckCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()


# ── !root-log komutu ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_root_log_file_not_found():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.commands.root_log_cmd._LOG_PATH") as mock_path:
        mock_path.exists.return_value = False
        from backend.guards.commands.root_log_cmd import RootLogCommand
        await RootLogCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_root_log_reads_last_lines(tmp_path):
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    log_file = tmp_path / "root_actions.log"
    log_file.write_text("\n".join(f"line {i}" for i in range(10)), encoding="utf-8")

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.commands.root_log_cmd._LOG_PATH", log_file):
        from backend.guards.commands.root_log_cmd import RootLogCommand
        await RootLogCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "line 9" in msg  # son satır dahil edilmeli


# ── !root-project komutu ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_root_project_no_arg_none_set(tmp_path):
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    ctx_file = tmp_path / "active_context.json"
    ctx_file.write_text("{}", encoding="utf-8")

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.commands.root_project_cmd._ACTIVE_CONTEXT_PATH", ctx_file):
        from backend.guards.commands.root_project_cmd import RootProjectCommand
        await RootProjectCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_root_project_no_arg_shows_current(tmp_path):
    import json
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    ctx_file = tmp_path / "active_context.json"
    ctx_file.write_text(
        json.dumps({"active_root_project": {"id": "myp", "name": "My Project", "path": "/tmp/myp"}}),
        encoding="utf-8",
    )

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.commands.root_project_cmd._ACTIVE_CONTEXT_PATH", ctx_file):
        from backend.guards.commands.root_project_cmd import RootProjectCommand
        await RootProjectCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "My Project" in msg


@pytest.mark.asyncio
async def test_root_project_invalid_id():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger):
        from backend.guards.commands.root_project_cmd import RootProjectCommand
        await RootProjectCommand().execute("905001234567", "invalid id with spaces!", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_root_project_not_found():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.store.sqlite_store.project_get", AsyncMock(return_value=None)):
        from backend.guards.commands.root_project_cmd import RootProjectCommand
        await RootProjectCommand().execute("905001234567", "no-such-proj", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "no-such-proj" in msg


@pytest.mark.asyncio
async def test_root_project_set_ok(tmp_path):
    import json
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    ctx_file = tmp_path / "active_context.json"
    ctx_file.write_text("{}", encoding="utf-8")
    fake_project = {"id": "myp", "name": "My Project", "path": "/tmp/myp"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.store.sqlite_store.project_get", AsyncMock(return_value=fake_project)), \
         patch("backend.features.chat.reset_bridge_session", AsyncMock(return_value=True)), \
         patch("backend.guards.commands.root_project_cmd._ACTIVE_CONTEXT_PATH", ctx_file):
        from backend.guards.commands.root_project_cmd import RootProjectCommand
        await RootProjectCommand().execute("905001234567", "myp", session)

    updated = json.loads(ctx_file.read_text())
    assert updated.get("active_root_project", {}).get("id") == "myp"
    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "My Project" in msg


# ── !project-delete komutu ────────────────────────────────────────

@pytest.mark.asyncio
async def test_project_delete_no_arg_empty_list():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.store.sqlite_store.project_list", AsyncMock(return_value=[])):
        from backend.guards.commands.project_delete_cmd import ProjectDeleteCommand
        await ProjectDeleteCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_project_delete_no_arg_shows_list():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    fake_projects = [{"id": "p1", "name": "Project One"}, {"id": "p2", "name": "Project Two"}]

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.store.sqlite_store.project_list", AsyncMock(return_value=fake_projects)):
        from backend.guards.commands.project_delete_cmd import ProjectDeleteCommand
        await ProjectDeleteCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "p1" in msg or "Project One" in msg


@pytest.mark.asyncio
async def test_project_delete_not_found():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.store.sqlite_store.project_get", AsyncMock(return_value=None)):
        from backend.guards.commands.project_delete_cmd import ProjectDeleteCommand
        await ProjectDeleteCommand().execute("905001234567", "no-such", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "no-such" in msg


@pytest.mark.asyncio
async def test_project_delete_ok():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    fake_project = {"id": "p1", "name": "Project One", "path": "/tmp/p1"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.store.sqlite_store.project_get", AsyncMock(return_value=fake_project)), \
         patch("backend.store.sqlite_store.project_delete", AsyncMock(return_value=True)):
        from backend.guards.commands.project_delete_cmd import ProjectDeleteCommand
        await ProjectDeleteCommand().execute("905001234567", "p1", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "Project One" in msg


# ── !terminal komutu ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_terminal_safe_cmd_runs_directly():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    mock_result = MagicMock()
    mock_result.timed_out = False
    mock_result.returncode = 0
    mock_result.stdout = "hello"
    mock_result.cwd = "/tmp"

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.features.terminal.is_dangerous", return_value=False), \
         patch("backend.features.terminal.execute_command", AsyncMock(return_value=mock_result)):
        from backend.guards.commands.terminal_cmd import TerminalCommand
        await TerminalCommand().execute("905001234567", "ls /tmp", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "hello" in msg


@pytest.mark.asyncio
async def test_terminal_dangerous_cmd_requests_totp():
    mock_messenger = AsyncMock()
    session_obj = MagicMock()
    session_obj.get.return_value = "tr"
    session_obj.pop.return_value = None

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.features.terminal.is_dangerous", return_value=True):
        from backend.guards.commands.terminal_cmd import TerminalCommand
        await TerminalCommand().execute("905001234567", "rm -rf /tmp/test", session_obj)

    session_obj.set_terminal_pending.assert_called_once_with("rm -rf /tmp/test")
    session_obj.start_totp.assert_called_once_with(cmd="/terminal")
    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminal_no_arg_no_pending():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger):
        from backend.guards.commands.terminal_cmd import TerminalCommand
        await TerminalCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_terminal_timed_out():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    mock_result = MagicMock()
    mock_result.timed_out = True
    mock_result.returncode = -1
    mock_result.stdout = ""
    mock_result.cwd = "/tmp"

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.features.terminal.is_dangerous", return_value=False), \
         patch("backend.features.terminal.execute_command", AsyncMock(return_value=mock_result)):
        from backend.guards.commands.terminal_cmd import TerminalCommand
        await TerminalCommand().execute("905001234567", "sleep 999", session)

    mock_messenger.send_text.assert_awaited_once()


# ── !timezone komutu ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_timezone_no_arg_shows_current():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.guards.commands.timezone_cmd._get_current_tz", return_value="Europe/Istanbul"):
        from backend.guards.commands.timezone_cmd import TimezoneCommand
        await TimezoneCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "Europe/Istanbul" in msg


@pytest.mark.asyncio
async def test_timezone_invalid_tz():
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger):
        from backend.guards.commands.timezone_cmd import TimezoneCommand
        await TimezoneCommand().execute("905001234567", "Not/AValid/TZ", session)

    mock_messenger.send_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_timezone_valid_change():
    mock_messenger = AsyncMock()
    mock_setting = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger",
               return_value=mock_messenger), \
         patch("backend.store.repositories.settings_repo.user_setting_set", mock_setting), \
         patch("backend.features.scheduler.apply_timezone", AsyncMock()):
        from backend.guards.commands.timezone_cmd import TimezoneCommand
        await TimezoneCommand().execute("905001234567", "Europe/Istanbul", session)

    mock_messenger.send_text.assert_awaited_once()
    mock_setting.assert_awaited_once_with("905001234567", "timezone", "Europe/Istanbul")


# ── !tokens komutu ────────────────────────────────────────────────

_SAMPLE_SUMMARY = [
    {"backend": "anthropic", "model_name": "Haiku 4.5", "model_id": "claude-3-5-haiku-20241022",
     "calls": 42, "input_tokens": 1_200_000, "output_tokens": 340_000, "total_tokens": 1_540_000},
    {"backend": "anthropic", "model_name": "Sonnet 4.6", "model_id": "claude-3-5-sonnet-20241022",
     "calls": 18, "input_tokens": 1_000_000, "output_tokens": 280_000, "total_tokens": 1_280_000},
    {"backend": "gemini", "model_name": "Gemini 2.0 Flash", "model_id": "gemini-2.0-flash",
     "calls": 5, "input_tokens": 300_000, "output_tokens": 60_000, "total_tokens": 360_000},
]

_SAMPLE_TOTALS = {
    "calls": 65,
    "input_tokens": 2_500_000,
    "output_tokens": 680_000,
    "total_tokens": 3_180_000,
}


@pytest.mark.asyncio
async def test_tokens_default_span_shows_stats():
    """Veri varken !tokens özet satırları içermeli."""
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger", return_value=mock_messenger), \
         patch("backend.store.repositories.token_stat_repo.get_totals",
               AsyncMock(return_value=_SAMPLE_TOTALS)), \
         patch("backend.store.repositories.token_stat_repo.get_summary",
               AsyncMock(return_value=_SAMPLE_SUMMARY)):
        from backend.guards.commands.tokens_cmd import TokensCommand
        await TokensCommand().execute("905001234567", "", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "24h" in msg
    assert "Haiku 4.5" in msg
    assert "Sonnet 4.6" in msg
    assert "Gemini 2.0 Flash" in msg


@pytest.mark.asyncio
async def test_tokens_shows_totals_line():
    """Toplam token satırı input + output + çağrı sayısı içermeli."""
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger", return_value=mock_messenger), \
         patch("backend.store.repositories.token_stat_repo.get_totals",
               AsyncMock(return_value=_SAMPLE_TOTALS)), \
         patch("backend.store.repositories.token_stat_repo.get_summary",
               AsyncMock(return_value=_SAMPLE_SUMMARY)):
        from backend.guards.commands.tokens_cmd import TokensCommand
        await TokensCommand().execute("905001234567", "24h", session)

    msg = mock_messenger.send_text.call_args[0][1]
    # 2_500_000 → "2.5M", 680_000 → "680.0K"
    assert "2.5M" in msg
    assert "680.0K" in msg
    assert "65" in msg


@pytest.mark.asyncio
async def test_tokens_7d_span():
    """!tokens 7d argümanını kabul etmeli ve başlıkta göstermeli."""
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger", return_value=mock_messenger), \
         patch("backend.store.repositories.token_stat_repo.get_totals",
               AsyncMock(return_value=_SAMPLE_TOTALS)), \
         patch("backend.store.repositories.token_stat_repo.get_summary",
               AsyncMock(return_value=_SAMPLE_SUMMARY)):
        from backend.guards.commands.tokens_cmd import TokensCommand
        await TokensCommand().execute("905001234567", "7d", session)

    msg = mock_messenger.send_text.call_args[0][1]
    assert "7d" in msg


@pytest.mark.asyncio
async def test_tokens_30d_span():
    """!tokens 30d argümanını kabul etmeli."""
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger", return_value=mock_messenger), \
         patch("backend.store.repositories.token_stat_repo.get_totals",
               AsyncMock(return_value=_SAMPLE_TOTALS)), \
         patch("backend.store.repositories.token_stat_repo.get_summary",
               AsyncMock(return_value=_SAMPLE_SUMMARY)):
        from backend.guards.commands.tokens_cmd import TokensCommand
        await TokensCommand().execute("905001234567", "30d", session)

    msg = mock_messenger.send_text.call_args[0][1]
    assert "30d" in msg


@pytest.mark.asyncio
async def test_tokens_invalid_span_shows_error():
    """Geçersiz zaman aralığında hata mesajı gönderilmeli."""
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger", return_value=mock_messenger):
        from backend.guards.commands.tokens_cmd import TokensCommand
        await TokensCommand().execute("905001234567", "5m", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    assert "5m" in msg


@pytest.mark.asyncio
async def test_tokens_empty_db_shows_empty_message():
    """Veri yokken boş mesaj gönderilmeli."""
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger", return_value=mock_messenger), \
         patch("backend.store.repositories.token_stat_repo.get_totals",
               AsyncMock(return_value={"calls": 0, "input_tokens": 0,
                                       "output_tokens": 0, "total_tokens": 0})), \
         patch("backend.store.repositories.token_stat_repo.get_summary",
               AsyncMock(return_value=[])):
        from backend.guards.commands.tokens_cmd import TokensCommand
        await TokensCommand().execute("905001234567", "24h", session)

    mock_messenger.send_text.assert_awaited_once()
    msg = mock_messenger.send_text.call_args[0][1]
    # Boş mesaj locale key'i ile gelir
    assert "24h" in msg


@pytest.mark.asyncio
async def test_tokens_single_backend_no_backend_section():
    """Tek backend varken 'Backend'ler' bölümü gösterilmemeli."""
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}
    single_backend_summary = [_SAMPLE_SUMMARY[0], _SAMPLE_SUMMARY[1]]  # sadece anthropic

    with patch("backend.adapters.messenger.get_messenger", return_value=mock_messenger), \
         patch("backend.store.repositories.token_stat_repo.get_totals",
               AsyncMock(return_value=_SAMPLE_TOTALS)), \
         patch("backend.store.repositories.token_stat_repo.get_summary",
               AsyncMock(return_value=single_backend_summary)):
        from backend.guards.commands.tokens_cmd import TokensCommand
        await TokensCommand().execute("905001234567", "24h", session)

    msg = mock_messenger.send_text.call_args[0][1]
    # Tek backend → backend bölümü gösterilmemeli
    assert "Gemini" not in msg


@pytest.mark.asyncio
async def test_tokens_multiple_backends_shows_backend_section():
    """Birden fazla backend varken backend bölümü görünmeli."""
    mock_messenger = AsyncMock()
    session = {"lang": "tr"}

    with patch("backend.adapters.messenger.get_messenger", return_value=mock_messenger), \
         patch("backend.store.repositories.token_stat_repo.get_totals",
               AsyncMock(return_value=_SAMPLE_TOTALS)), \
         patch("backend.store.repositories.token_stat_repo.get_summary",
               AsyncMock(return_value=_SAMPLE_SUMMARY)):
        from backend.guards.commands.tokens_cmd import TokensCommand
        await TokensCommand().execute("905001234567", "24h", session)

    msg = mock_messenger.send_text.call_args[0][1]
    assert "Anthropic" in msg
    assert "Gemini" in msg


def test_tokens_fmt_millions():
    """_fmt 1M+ değerleri M formatında göstermeli."""
    from backend.guards.commands.tokens_cmd import _fmt
    assert _fmt(1_200_000) == "1.2M"
    assert _fmt(1_000_000) == "1.0M"
    assert _fmt(2_500_000) == "2.5M"


def test_tokens_fmt_thousands():
    """_fmt 1K-999K değerleri K formatında göstermeli."""
    from backend.guards.commands.tokens_cmd import _fmt
    assert _fmt(12_345) == "12.3K"
    assert _fmt(1_000) == "1.0K"
    assert _fmt(999_999) == "1000.0K"


def test_tokens_fmt_small():
    """_fmt 1000 altı değerleri sayı olarak göstermeli."""
    from backend.guards.commands.tokens_cmd import _fmt
    assert _fmt(0) == "0"
    assert _fmt(999) == "999"
    assert _fmt(1) == "1"
