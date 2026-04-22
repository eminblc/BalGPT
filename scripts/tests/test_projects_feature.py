"""Projects feature — güvenlik regex'i ve _validate_service_cmd testleri.

Bu testler dosya sistemi veya DB'ye erişmez.
"""
import pytest
import re
from backend.features.projects import _UNSAFE_CMD_RE, _WINDOW_NAME_RE


# ── _UNSAFE_CMD_RE — tehlikeli karakter tespiti ───────────────────

@pytest.mark.parametrize("bad_char", [";", "&", "|", "`", "$", "<", ">",
                                       "$(", "\n", "\r", "\x00"])
def test_unsafe_cmd_blocks_dangerous_chars(bad_char):
    """Tehlikeli karakterler içeren komut → regex eşleşmeli."""
    cmd = f"python app.py{bad_char}rm -rf /"
    assert _UNSAFE_CMD_RE.search(cmd), f"'{bad_char}' engellenmedi"


@pytest.mark.parametrize("safe_cmd", [
    "python app.py",
    "uvicorn main:app --host 0.0.0.0 --port 8000",
    "node server.js",
    "gunicorn -w 4 app:app",
    "./start.sh",
    "python -m mymodule",
])
def test_safe_cmd_passes(safe_cmd):
    """Güvenli komutlar regex'e takılmamalı."""
    assert not _UNSAFE_CMD_RE.search(safe_cmd), f"'{safe_cmd}' yanlışlıkla engellendi"


def test_pipe_redirect_blocked():
    """2>&1 tarzı yönlendirme engellenmeli."""
    cmd = "python app.py 2>&1"
    assert _UNSAFE_CMD_RE.search(cmd)


def test_command_substitution_blocked():
    """$() komut substitution engellenmeli."""
    cmd = "echo $(whoami)"
    assert _UNSAFE_CMD_RE.search(cmd)


# ── _WINDOW_NAME_RE — tmux window adı doğrulama ──────────────────

@pytest.mark.parametrize("valid_name", [
    "my-project",
    "project_123",
    "MyProject",
    "a",
    "A" * 50,  # maksimum uzunluk
])
def test_valid_window_names(valid_name):
    assert _WINDOW_NAME_RE.match(valid_name)


@pytest.mark.parametrize("invalid_name", [
    "",
    "my project",          # boşluk yok
    "my.project",          # nokta yok
    "project!",            # özel karakter
    "A" * 51,              # 51 karakter (max 50)
    "proje/adı",           # slash yok
])
def test_invalid_window_names(invalid_name):
    assert not _WINDOW_NAME_RE.match(invalid_name)
