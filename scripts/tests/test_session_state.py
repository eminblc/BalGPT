"""SessionState — dict alt sınıfı ve auth akışı metotları testleri (OOP-1)."""
import pytest
from backend.app_types import SessionState


@pytest.fixture
def session():
    # SOLID-1: controlled keys (awaiting_totp, pending_command vb.) constructor'dan
    # geçirilmez; başlangıç değerleri start_*/clear_* metotları üzerinden yönetilir.
    return SessionState(
        active_context="main",
        menu_page=0,
    )


# ── dict uyumluluğu ────────────────────────────────────────────────

def test_is_dict_subclass(session):
    assert isinstance(session, dict)


def test_constructor_kwargs(session):
    assert session["active_context"] == "main"
    assert session["menu_page"] == 0


def test_get_missing_key_returns_default(session):
    assert session.get("nonexistent_key", "fallback") == "fallback"


def test_pop_missing_key_returns_none(session):
    assert session.pop("nonexistent_key", None) is None


def test_direct_key_assignment(session):
    session["custom_key"] = "custom_value"
    assert session["custom_key"] == "custom_value"


# ── start_totp / clear_totp ────────────────────────────────────────

def test_start_totp_sets_keys(session):
    session.start_totp("!restart arg")
    assert session["awaiting_totp"] is True
    assert session["pending_command"] == "!restart arg"


def test_clear_totp_unsets_keys(session):
    session.start_totp("!restart")
    session.clear_totp()
    assert session["awaiting_totp"] is False
    assert session.get("pending_command") is None


def test_clear_totp_without_start_is_safe(session):
    """clear_totp daha önce start_totp çağrılmamışsa hata fırlatmamalı."""
    session.clear_totp()  # KeyError yok
    assert session.get("pending_command") is None


# ── start_math_challenge / clear_math_challenge ───────────────────

def test_start_math_challenge_sets_three_keys(session):
    session.start_math_challenge(answer=42, cmd="!shutdown arg")
    assert session["awaiting_math_challenge"] is True
    assert session["math_challenge_answer"] == 42
    assert session["math_challenge_command"] == "!shutdown arg"


def test_clear_math_challenge_removes_all_keys(session):
    session.start_math_challenge(answer=99, cmd="!restart")
    session["math_fail_count"] = 2
    session.clear_math_challenge()
    assert session["awaiting_math_challenge"] is False
    assert session.get("math_challenge_answer") is None
    assert session.get("math_challenge_command") is None
    assert session.get("math_fail_count") is None


def test_clear_math_challenge_without_start_is_safe(session):
    session.clear_math_challenge()  # KeyError yok


# ── start_guardrail / clear_guardrail ────────────────────────────

def test_start_guardrail_sets_keys(session):
    session.start_guardrail("tehlikeli eylem")
    assert session["awaiting_guardrail_confirm"] is True
    assert session["pending_guardrail_action"] == "tehlikeli eylem"


def test_clear_guardrail_unsets_keys(session):
    session.start_guardrail("tehlikeli eylem")
    session.clear_guardrail()
    assert session["awaiting_guardrail_confirm"] is False
    assert session.get("pending_guardrail_action") is None


def test_clear_guardrail_without_start_is_safe(session):
    session.clear_guardrail()  # KeyError yok


# ── Birden fazla auth akışı art arda ─────────────────────────────

def test_math_then_owner_totp_transition(session):
    """Math challenge tamamlanınca owner TOTP başlatılabilmeli."""
    session.start_math_challenge(answer=15, cmd="!shutdown")
    cmd = session.get("math_challenge_command", "")
    session.clear_math_challenge()
    session.start_totp(cmd=cmd)

    assert session["awaiting_math_challenge"] is False
    assert session.get("math_challenge_answer") is None
    assert session["awaiting_totp"] is True
    assert session["pending_command"] == "!shutdown"


def test_guardrail_then_owner_totp_transition(session):
    """Guardrail onaylanınca owner TOTP başlatılabilmeli."""
    session.start_guardrail("rm -rf /tmp")
    action = session.pop("pending_guardrail_action", "")
    session.clear_guardrail()
    dict.__setitem__(session, "pending_bridge_message", action)
    session.start_totp(cmd="")

    assert session["awaiting_guardrail_confirm"] is False
    assert session["awaiting_totp"] is True
    assert session["pending_bridge_message"] == "rm -rf /tmp"
