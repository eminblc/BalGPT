"""Install wizard — env_writer + state_machine + flow tests (TG-WIZ-1)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from backend.features.install_wizard.env_writer import write_env, delete_keys
from backend.features.install_wizard.state_machine import (
    DEFAULT_CAPS_ENABLED,
    initial_state,
    toggle_capability,
)
from backend.features.install_wizard.flow import (
    _build_env_updates,
    is_wizard_callback,
)


# ── env_writer ────────────────────────────────────────────────────

def test_write_env_creates_file_and_appends(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    write_env(env, {"FOO": "bar", "BAZ": "qux"})
    assert env.read_text().splitlines() == ["FOO=bar", "BAZ=qux"]


def test_write_env_replaces_existing_key_in_place(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("KEY1=old\nKEY2=keep\nKEY1_BIS=other\n")
    write_env(env, {"KEY1": "new"})
    assert env.read_text() == "KEY1=new\nKEY2=keep\nKEY1_BIS=other\n"


def test_write_env_preserves_comments_and_blank_lines(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# header\n\nFOO=1\n# inline\nBAR=2\n")
    write_env(env, {"FOO": "X"})
    assert env.read_text() == "# header\n\nFOO=X\n# inline\nBAR=2\n"


def test_write_env_atomic_no_partial_file_on_failure(tmp_path: Path, monkeypatch) -> None:
    env = tmp_path / ".env"
    env.write_text("FOO=original\n")

    real_replace = __import__("os").replace

    def boom(*a, **kw):
        raise OSError("simulated")

    monkeypatch.setattr("os.replace", boom)
    with pytest.raises(OSError):
        write_env(env, {"FOO": "new"})
    # File should still hold original content
    assert env.read_text() == "FOO=original\n"
    # No leftover .tmp files
    assert not list(tmp_path.glob("*.tmp"))
    # Restore for cleanup
    monkeypatch.setattr("os.replace", real_replace)


def test_delete_keys_removes_only_matching_lines(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("# keep\nA=1\nB=2\nC=3\n")
    delete_keys(env, ["A", "C", "MISSING"])
    assert env.read_text() == "# keep\nB=2\n"


def test_delete_keys_noop_when_file_missing(tmp_path: Path) -> None:
    env = tmp_path / "nope.env"
    delete_keys(env, ["A"])
    assert not env.exists()


# ── state_machine ────────────────────────────────────────────────

def test_initial_state_starts_with_default_caps_and_llm_step() -> None:
    s = initial_state()
    assert s["step"] == "llm"
    assert s["awaiting_text"] is None
    assert set(s["data"]["capabilities"]) == set(DEFAULT_CAPS_ENABLED)


def test_toggle_capability_round_trip() -> None:
    data = {"capabilities": list(DEFAULT_CAPS_ENABLED)}
    # First toggle removes
    toggle_capability(data, "media")
    assert "media" not in data["capabilities"]
    # Second toggle re-adds
    toggle_capability(data, "media")
    assert "media" in data["capabilities"]


def test_toggle_capability_adds_new_one() -> None:
    data = {"capabilities": []}
    toggle_capability(data, "browser")
    assert data["capabilities"] == ["browser"]


# ── flow._build_env_updates ──────────────────────────────────────

def test_build_env_updates_anthropic_apikey_path() -> None:
    data = {
        "llm_backend": "anthropic",
        "anthropic_auth_method": "apikey",
        "anthropic_api_key": "sk-ant-api03-XYZ",
        "capabilities": ["fs", "network"],
        "timezone": "UTC",
    }
    updates, drop = _build_env_updates(data)
    assert updates["LLM_BACKEND"] == "anthropic"
    assert updates["ANTHROPIC_API_KEY"] == "sk-ant-api03-XYZ"
    assert updates["TIMEZONE"] == "UTC"
    assert updates["RESTRICT_FS_OUTSIDE_ROOT"] == "false"
    assert updates["RESTRICT_NETWORK"] == "false"
    assert updates["RESTRICT_SHELL"] == "true"  # not selected
    assert updates["DESKTOP_ENABLED"] == "false"
    assert updates["BROWSER_ENABLED"] == "false"
    assert drop == []


def test_build_env_updates_anthropic_login_drops_key() -> None:
    data = {
        "llm_backend": "anthropic",
        "anthropic_auth_method": "login",
        "capabilities": [],
        "timezone": "Europe/Istanbul",
    }
    updates, drop = _build_env_updates(data)
    assert "ANTHROPIC_API_KEY" not in updates
    assert drop == ["ANTHROPIC_API_KEY"]


def test_build_env_updates_ollama_path() -> None:
    data = {
        "llm_backend": "ollama",
        "ollama_base_url": "http://example:11434",
        "ollama_model": "qwen2.5",
        "capabilities": list(DEFAULT_CAPS_ENABLED),
        "timezone": "Asia/Tokyo",
    }
    updates, _ = _build_env_updates(data)
    assert updates["LLM_BACKEND"] == "ollama"
    assert updates["OLLAMA_BASE_URL"] == "http://example:11434"
    assert updates["OLLAMA_MODEL"] == "qwen2.5"


def test_build_env_updates_gemini_path() -> None:
    data = {
        "llm_backend": "gemini",
        "gemini_api_key": "AIzaSyTEST_KEY_123456",
        "capabilities": ["screenshot", "desktop", "browser"],
        "timezone": "UTC",
    }
    updates, _ = _build_env_updates(data)
    assert updates["GEMINI_API_KEY"] == "AIzaSyTEST_KEY_123456"
    assert updates["DESKTOP_ENABLED"] == "true"
    assert updates["BROWSER_ENABLED"] == "true"
    assert updates["RESTRICT_SCREENSHOT"] == "false"


def test_build_env_updates_caps_all_present() -> None:
    """Every capability defined in keyboards.ALL_CAPS must produce an env key."""
    data = {
        "llm_backend": "anthropic",
        "anthropic_auth_method": "login",
        "capabilities": [],
        "timezone": "UTC",
    }
    updates, _ = _build_env_updates(data)
    expected_restrict_keys = {
        "RESTRICT_FS_OUTSIDE_ROOT", "RESTRICT_NETWORK", "RESTRICT_SHELL",
        "RESTRICT_SERVICE_MGMT", "RESTRICT_MEDIA", "RESTRICT_CALENDAR",
        "RESTRICT_PROJECT_WIZARD", "RESTRICT_SCREENSHOT", "RESTRICT_SCHEDULER",
        "RESTRICT_PDF_IMPORT", "RESTRICT_CONV_HISTORY", "RESTRICT_PLANS",
        "RESTRICT_INTENT_CLASSIFIER", "RESTRICT_WIZARD_LLM_SCAFFOLD",
    }
    assert expected_restrict_keys.issubset(updates.keys())


# ── flow.is_wizard_callback ──────────────────────────────────────

@pytest.mark.parametrize("rid,expected", [
    ("iw:start", True),
    ("iw:llm:anthropic", True),
    ("iw:cap:toggle:browser", True),
    ("perm_a:abc", False),
    ("project:select:1", False),
    ("", False),
])
def test_is_wizard_callback(rid: str, expected: bool) -> None:
    assert is_wizard_callback(rid) is expected
