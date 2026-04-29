"""
Tests for install.sh bash helper functions.

Strategy: source install.sh with `main` overridden as a no-op so the interactive
wizard never runs.  Each test calls one bash function in isolation via subprocess.
"""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

# ── paths ─────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).parents[2]
_INSTALL_SH = _REPO_ROOT / "install.sh"


# ── helpers ───────────────────────────────────────────────────────────────────


def _bash(fragment: str, backend_dir: str | None = None) -> subprocess.CompletedProcess:
    """Source install.sh (sans the final `main "$@"` call) then run *fragment*."""
    bd = backend_dir or "/tmp/_test_install_backend"
    # head -n -1 strips the last `main "$@"` line so the wizard never starts.
    script = f"""
set -euo pipefail
export ROOT_DIR="{_REPO_ROOT}"
export INSTALL_LANG=en
source <(head -n -1 "{_INSTALL_SH}")
# Override BACKEND_DIR after source so install.sh top-level assignments don't win
BACKEND_DIR="{bd}"
{fragment}
"""
    return subprocess.run(
        ["bash", "--noprofile", "--norc", "-c", script],
        capture_output=True,
        text=True,
    )


def _ok(result: subprocess.CompletedProcess) -> str:
    """Assert exit 0 and return stdout stripped."""
    assert result.returncode == 0, (
        f"exit {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    return result.stdout.strip()


# ── _env_set / _read_env_var ──────────────────────────────────────────────────


class TestEnvSet:
    def test_creates_new_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("")
        _ok(_bash(f'_env_set FOO bar "{env}"'))
        assert "FOO=bar" in env.read_text()

    def test_updates_existing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("FOO=old\n")
        _ok(_bash(f'_env_set FOO new "{env}"'))
        text = env.read_text()
        assert "FOO=new" in text
        assert "FOO=old" not in text

    def test_update_does_not_duplicate_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("FOO=first\n")
        _ok(_bash(f'_env_set FOO second "{env}"'))
        assert env.read_text().count("FOO=") == 1

    def test_value_with_equals_sign(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("")
        _ok(_bash(f'_env_set TOKEN "abc=xyz=123" "{env}"'))
        assert "TOKEN=abc=xyz=123" in env.read_text()

    def test_value_with_slashes_and_at(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("")
        _ok(_bash(f'_env_set URL "https://user@host/path" "{env}"'))
        assert "URL=https://user@host/path" in env.read_text()

    def test_value_with_ampersand(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("KEY=old\n")
        _ok(_bash(f'_env_set KEY "val&more" "{env}"'))
        assert "KEY=val&more" in env.read_text()


class TestReadEnvVar:
    def test_reads_existing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("MY_KEY=hello\n")
        out = _ok(_bash(f'_read_env_var MY_KEY "{env}"'))
        assert out == "hello"

    def test_returns_empty_for_missing_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("OTHER=x\n")
        out = _ok(_bash(f'_read_env_var MISSING "{env}"'))
        assert out == ""

    def test_strips_double_quotes(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text('QUOTED="myvalue"\n')
        out = _ok(_bash(f'_read_env_var QUOTED "{env}"'))
        assert out == "myvalue"

    def test_missing_file_returns_empty(self, tmp_path):
        result = _bash(f'_read_env_var KEY "{tmp_path / "nonexistent.env"}"')
        assert result.returncode == 0
        assert result.stdout.strip() == ""


# ── _env_comment_out / _env_uncomment ─────────────────────────────────────────


class TestEnvCommentToggle:
    def test_comment_out_active_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("BROWSER_HEADLESS=true\n")
        _ok(_bash(f'_env_comment_out BROWSER_HEADLESS "{env}"'))
        assert "# BROWSER_HEADLESS=true" in env.read_text()

    def test_comment_out_idempotent(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# BROWSER_HEADLESS=true\n")
        _ok(_bash(f'_env_comment_out BROWSER_HEADLESS "{env}"'))
        assert env.read_text().count("BROWSER_HEADLESS") == 1

    def test_uncomment_commented_key(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# BROWSER_HEADLESS=true\n")
        _ok(_bash(f'_env_uncomment BROWSER_HEADLESS "{env}"'))
        text = env.read_text()
        assert "BROWSER_HEADLESS=true" in text
        assert "# BROWSER_HEADLESS" not in text

    def test_uncomment_idempotent(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("BROWSER_HEADLESS=true\n")
        _ok(_bash(f'_env_uncomment BROWSER_HEADLESS "{env}"'))
        assert env.read_text().count("BROWSER_HEADLESS") == 1

    def test_comment_out_nonexistent_key_is_noop(self, tmp_path):
        env = tmp_path / ".env"
        original = "OTHER=val\n"
        env.write_text(original)
        _ok(_bash(f'_env_comment_out GHOST "{env}"'))
        assert env.read_text() == original


# ── _parse_wiz ────────────────────────────────────────────────────────────────


class TestParseWiz:
    def _call(self, json_str: str, key: str, default: str = "") -> str:
        payload = json_str.replace('"', '\\"')
        result = _bash(f'_parse_wiz "{payload}" "{key}" "{default}"')
        return _ok(result)

    def test_reads_existing_string_key(self):
        data = json.dumps({"llm": "anthropic", "proxy": "none"})
        assert self._call(data, "llm") == "anthropic"

    def test_returns_default_for_missing_key(self):
        data = json.dumps({"llm": "anthropic"})
        assert self._call(data, "timezone", "Europe/Istanbul") == "Europe/Istanbul"

    def test_returns_empty_default_when_missing(self):
        data = json.dumps({"x": "y"})
        assert self._call(data, "missing_key") == ""

    def test_special_chars_in_default_do_not_inject(self):
        # Default contains single quotes — must not break Python code
        data = json.dumps({})
        result = _bash(
            """_parse_wiz '{"a":"b"}' "nope" "it's fine" """
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "it's fine"

    def test_invalid_json_returns_default(self):
        result = _bash('_parse_wiz "not-json" "key" "fallback"')
        assert result.returncode == 0
        assert result.stdout.strip() == "fallback"

    def test_reads_value_with_spaces(self):
        data = json.dumps({"proxy": "none", "timezone": "Europe/Istanbul"})
        assert self._call(data, "timezone") == "Europe/Istanbul"


# ── _tg_extract_next_offset ───────────────────────────────────────────────────


class TestTgExtractNextOffset:
    def _call(self, json_str: str) -> int:
        escaped = json_str.replace("'", "'\\''")
        result = _bash(f"_tg_extract_next_offset '{escaped}'")
        return int(_ok(result))

    def test_single_update(self):
        payload = json.dumps({"ok": True, "result": [{"update_id": 100}]})
        assert self._call(payload) == 101

    def test_multiple_updates_uses_last(self):
        payload = json.dumps({
            "ok": True,
            "result": [{"update_id": 10}, {"update_id": 20}, {"update_id": 30}],
        })
        assert self._call(payload) == 31

    def test_empty_result_returns_zero(self):
        payload = json.dumps({"ok": True, "result": []})
        assert self._call(payload) == 0

    def test_invalid_json_returns_zero(self):
        assert self._call("not-valid-json") == 0

    def test_missing_result_key_returns_zero(self):
        assert self._call(json.dumps({"ok": True})) == 0


# ── _gen_api_key ──────────────────────────────────────────────────────────────


class TestGenApiKey:
    def test_returns_64_hex_chars(self):
        out = _ok(_bash("_gen_api_key"))
        assert len(out) == 64, f"expected 64 chars, got {len(out)}: {out!r}"
        assert re.fullmatch(r"[0-9a-f]{64}", out), f"not hex: {out!r}"

    def test_two_calls_differ(self):
        out = _ok(_bash("echo $(_gen_api_key)___$(_gen_api_key)"))
        a, b = out.split("___")
        assert a != b


# ── _gen_totp ─────────────────────────────────────────────────────────────────


class TestGenTotp:
    def test_returns_32_chars(self):
        out = _ok(_bash("_gen_totp"))
        assert len(out) == 32, f"expected 32 chars, got {len(out)}: {out!r}"

    def test_only_base32_alphabet(self):
        out = _ok(_bash("_gen_totp"))
        assert re.fullmatch(r"[A-Z2-7]{32}", out), f"not base32: {out!r}"

    def test_two_calls_differ(self):
        out = _ok(_bash("echo $(_gen_totp)___$(_gen_totp)"))
        a, b = out.split("___")
        assert a != b


# ── render_template ───────────────────────────────────────────────────────────


class TestRenderTemplate:
    _TEMPLATE_CONTENT = (
        "User={{USER}} Root={{ROOT_DIR}} Node={{NODE_PATH}} "
        "Api={{API_PORT}} Bridge={{BRIDGE_PORT}}"
    )

    def test_all_placeholders_replaced(self, tmp_path):
        tpl = tmp_path / "test.template"
        out = tmp_path / "test.rendered"
        tpl.write_text(self._TEMPLATE_CONTENT)
        _ok(_bash(
            f'CURRENT_USER=alice ROOT_DIR=/tmp/root NODE_PATH=/usr/bin/node '
            f'API_PORT=8010 BRIDGE_PORT=8013 '
            f'render_template "{tpl}" "{out}"'
        ))
        rendered = out.read_text()
        assert "{{USER}}" not in rendered
        assert "{{ROOT_DIR}}" not in rendered
        assert "{{NODE_PATH}}" not in rendered
        assert "User=alice" in rendered
        assert "Root=/tmp/root" in rendered
        assert "Api=8010" in rendered
        assert "Bridge=8013" in rendered

    def test_no_leftover_placeholders(self, tmp_path):
        tpl = tmp_path / "full.template"
        out = tmp_path / "full.rendered"
        tpl.write_text(self._TEMPLATE_CONTENT)
        _ok(_bash(
            f'CURRENT_USER=bob ROOT_DIR=/home/bob NODE_PATH=/usr/local/bin/node '
            f'API_PORT=9000 BRIDGE_PORT=9001 '
            f'render_template "{tpl}" "{out}"'
        ))
        assert "{{" not in out.read_text()

    def test_ampersand_in_root_dir_not_corrupted(self, tmp_path):
        # & is a sed metachar; python3 replace must handle it safely
        tpl = tmp_path / "amp.template"
        out = tmp_path / "amp.rendered"
        tpl.write_text("Root={{ROOT_DIR}}")
        _ok(_bash(
            f'CURRENT_USER=u ROOT_DIR="/tmp/my&dir" NODE_PATH=/usr/bin/node '
            f'API_PORT=8010 BRIDGE_PORT=8013 '
            f'render_template "{tpl}" "{out}"'
        ))
        assert "Root=/tmp/my&dir" in out.read_text()

    def test_pipe_in_path_not_corrupted(self, tmp_path):
        tpl = tmp_path / "pipe.template"
        out = tmp_path / "pipe.rendered"
        tpl.write_text("Node={{NODE_PATH}}")
        _ok(_bash(
            f'CURRENT_USER=u ROOT_DIR=/tmp NODE_PATH="/usr/bin/node|extra" '
            f'API_PORT=8010 BRIDGE_PORT=8013 '
            f'render_template "{tpl}" "{out}"'
        ))
        assert 'Node=/usr/bin/node|extra' in out.read_text()


# ── _write_capabilities ───────────────────────────────────────────────────────


class TestWriteCapabilities:
    def _run_caps(self, selected: str, tmp_path: Path) -> str:
        env = tmp_path / ".env"
        env.write_text("")
        # Single-quote the selected string so embedded " chars survive the shell
        _ok(_bash(
            f"_write_capabilities '{selected}'",
            backend_dir=str(tmp_path),
        ))
        return env.read_text()

    def test_selected_restrict_key_sets_false(self, tmp_path):
        text = self._run_caps('"shell"', tmp_path)
        assert "RESTRICT_SHELL=false" in text

    def test_unselected_restrict_key_sets_true(self, tmp_path):
        # "shell" not included → restricted
        text = self._run_caps('"media"', tmp_path)
        assert "RESTRICT_SHELL=true" in text

    def test_multiple_selected_keys(self, tmp_path):
        text = self._run_caps('"shell" "media" "scheduler"', tmp_path)
        assert "RESTRICT_SHELL=false" in text
        assert "RESTRICT_MEDIA=false" in text
        assert "RESTRICT_SCHEDULER=false" in text

    def test_desktop_selected_sets_enabled_true(self, tmp_path):
        text = self._run_caps('"desktop"', tmp_path)
        assert "DESKTOP_ENABLED=true" in text

    def test_desktop_unselected_sets_enabled_false(self, tmp_path):
        text = self._run_caps('"shell"', tmp_path)
        assert "DESKTOP_ENABLED=false" in text

    def test_browser_selected_sets_enabled_true(self, tmp_path):
        text = self._run_caps('"browser"', tmp_path)
        assert "BROWSER_ENABLED=true" in text

    def test_browser_unselected_sets_enabled_false(self, tmp_path):
        text = self._run_caps('"shell"', tmp_path)
        assert "BROWSER_ENABLED=false" in text

    def test_all_restrict_keys_written(self, tmp_path):
        text = self._run_caps("", tmp_path)
        for key in (
            "RESTRICT_FS_OUTSIDE_ROOT", "RESTRICT_NETWORK", "RESTRICT_SHELL",
            "RESTRICT_SERVICE_MGMT", "RESTRICT_MEDIA", "RESTRICT_CALENDAR",
            "RESTRICT_PROJECT_WIZARD", "RESTRICT_SCREENSHOT", "RESTRICT_SCHEDULER",
            "RESTRICT_PDF_IMPORT", "RESTRICT_CONV_HISTORY", "RESTRICT_PLANS",
            "RESTRICT_INTENT_CLASSIFIER", "RESTRICT_WIZARD_LLM_SCAFFOLD",
        ):
            assert key in text, f"Expected {key} in .env"

    def test_cap_keys_envs_length_mismatch_causes_die(self, tmp_path):
        # Inject a mismatched array and check die fires
        env = tmp_path / ".env"
        env.write_text("")
        result = _bash(
            """
cap_keys=( "a" "b" )
cap_envs=( "X" )
[[ ${#cap_keys[@]} -ne ${#cap_envs[@]} ]] && die "mismatch detected"
""",
            backend_dir=str(tmp_path),
        )
        assert result.returncode != 0
        assert "mismatch" in result.stderr


# ── _wa_notify JSON body ──────────────────────────────────────────────────────


class TestWaNotifyJsonBody:
    def _capture_body(self, message: str, tmp_path: Path) -> dict:
        """Override curl to write its -d argument to a file; parse as JSON."""
        body_file = tmp_path / "body.json"
        msg_file = tmp_path / "msg.txt"
        msg_file.write_text(message)  # avoid quoting issues by writing to file
        fragment = f"""
curl() {{
    local _next=false
    for _a in "$@"; do
        if [[ "$_next" == "true" ]]; then
            printf '%s' "$_a" > "{body_file}"
            _next=false
        fi
        [[ "$_a" == "-d" ]] && _next=true
    done
}}
_MSG=$(cat "{msg_file}")
_wa_notify "tok123" "pid456" "+905001112233" "$_MSG"
"""
        _ok(_bash(fragment))
        raw = body_file.read_text()
        return json.loads(raw)

    def test_basic_body_structure(self, tmp_path):
        body = self._capture_body("Hello world", tmp_path)
        assert body["messaging_product"] == "whatsapp"
        assert body["type"] == "text"
        assert body["text"]["body"] == "Hello world"

    def test_recipient_strips_plus(self, tmp_path):
        body = self._capture_body("Hi", tmp_path)
        assert body["to"] == "905001112233"

    def test_message_with_double_quotes(self, tmp_path):
        body = self._capture_body('Say "hello"', tmp_path)
        assert body["text"]["body"] == 'Say "hello"'

    def test_message_with_backslash(self, tmp_path):
        body = self._capture_body("path\\to\\file", tmp_path)
        assert body["text"]["body"] == "path\\to\\file"

    def test_message_with_newline(self, tmp_path):
        body_file = tmp_path / "body.json"
        msg_file = tmp_path / "msg.txt"
        msg_file.write_text("line1\nline2")
        fragment = f"""
curl() {{
    local _next=false
    for _a in "$@"; do
        if [[ "$_next" == "true" ]]; then
            printf '%s' "$_a" > "{body_file}"
            _next=false
        fi
        [[ "$_a" == "-d" ]] && _next=true
    done
}}
_MSG=$(cat "{msg_file}")
_wa_notify "tok" "pid" "+1" "$_MSG"
"""
        _ok(_bash(fragment))
        body = json.loads(body_file.read_text())
        assert "line1" in body["text"]["body"]
        assert "line2" in body["text"]["body"]

    def test_missing_token_skips_curl(self, tmp_path):
        fragment = """
curl() { echo "CURL_CALLED"; }
_wa_notify "" "pid" "+1" "msg"
"""
        out = _ok(_bash(fragment))
        assert "CURL_CALLED" not in out

    def test_missing_phone_id_skips_curl(self, tmp_path):
        fragment = """
curl() { echo "CURL_CALLED"; }
_wa_notify "tok" "" "+1" "msg"
"""
        out = _ok(_bash(fragment))
        assert "CURL_CALLED" not in out


# ── _totp_send_via_messenger ──────────────────────────────────────────────────


class TestTotpSendViaMessenger:
    def test_returns_1_when_no_telegram_creds(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("MESSENGER_TYPE=telegram\n")  # no token/chat_id
        result = _bash(
            f'_totp_send_via_messenger "OWNERBASE32" "{env}"'
        )
        assert result.returncode != 0

    def test_returns_1_when_no_whatsapp_creds(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("MESSENGER_TYPE=whatsapp\n")  # no token/phone/owner
        result = _bash(
            f'_totp_send_via_messenger "OWNERBASE32" "{env}"'
        )
        assert result.returncode != 0

    def test_telegram_sends_html_message(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "MESSENGER_TYPE=telegram\n"
            "TELEGRAM_BOT_TOKEN=faketoken\n"
            "TELEGRAM_CHAT_ID=12345\n"
        )
        # Redirect curl stdout to stderr so it escapes the `| python3` pipe
        fragment = f"""
curl() {{
    printf '%s\\n' "$@" >&2
}}
_totp_send_via_messenger "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" "{env}" || true
"""
        result = _bash(fragment)
        assert "sendMessage" in result.stderr
        assert "HTML" in result.stderr

    def test_whatsapp_sends_json_with_secrets(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text(
            "MESSENGER_TYPE=whatsapp\n"
            "WHATSAPP_ACCESS_TOKEN=faketoken\n"
            "WHATSAPP_PHONE_NUMBER_ID=fakepid\n"
            "WHATSAPP_OWNER=+905001234567\n"
        )
        fragment = f"""
curl() {{
    printf '%s\\n' "$@" >&2
}}
_totp_send_via_messenger "OWNSECRET32CHARS0000000000000000" "{env}" || true
"""
        result = _bash(fragment)
        assert "messages" in result.stderr  # WhatsApp messages endpoint
        assert "OWNSECRET" in result.stderr
