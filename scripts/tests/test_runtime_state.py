"""runtime_state modülü testleri — kilit, aktif model, son durum."""
import time
import pytest


@pytest.fixture(autouse=True)
def reset_state():
    """Her test öncesi runtime_state'i sıfırla."""
    import backend.guards.runtime_state as rs
    rs._locked = True
    rs._active_model = None
    rs._last_status.clear()
    rs._last_cleanup = 0.0
    yield
    rs._locked = True
    rs._active_model = None
    rs._last_status.clear()


# ── Kilit durumu ──────────────────────────────────────────────────

def test_initial_locked():
    from backend.guards.runtime_state import is_locked
    assert is_locked() is True


def test_set_locked_false():
    from backend.guards.runtime_state import set_locked, is_locked
    set_locked(False)
    assert is_locked() is False


def test_set_locked_true_again():
    from backend.guards.runtime_state import set_locked, is_locked
    set_locked(False)
    set_locked(True)
    assert is_locked() is True


# ── Aktif model ───────────────────────────────────────────────────

def test_initial_model_is_none():
    from backend.guards.runtime_state import get_active_model
    assert get_active_model() is None


def test_set_and_get_model():
    from backend.guards.runtime_state import set_active_model, get_active_model
    set_active_model("claude-haiku-4-5-20251001")
    assert get_active_model() == "claude-haiku-4-5-20251001"


def test_reset_model_to_none():
    from backend.guards.runtime_state import set_active_model, get_active_model
    set_active_model("claude-sonnet-4-6")
    set_active_model(None)
    assert get_active_model() is None


# ── record_status + get_last_status ──────────────────────────────

def test_record_status_gear_emoji_saves():
    from backend.guards.runtime_state import record_status, get_last_status
    record_status("905001234567", "⚙️ İşlem devam ediyor...")
    result = get_last_status("905001234567")
    assert result is not None
    assert result["text"] == "⚙️ İşlem devam ediyor..."


def test_record_status_check_emoji_clears():
    from backend.guards.runtime_state import record_status, get_last_status
    record_status("905001234567", "⚙️ İşlem devam ediyor...")
    record_status("905001234567", "✅ Tamamlandı")
    assert get_last_status("905001234567") is None


def test_record_status_cross_emoji_clears():
    from backend.guards.runtime_state import record_status, get_last_status
    record_status("905001234567", "⚙️ İşlem devam ediyor...")
    record_status("905001234567", "❌ Hata oluştu")
    assert get_last_status("905001234567") is None


def test_get_last_status_unknown_number():
    from backend.guards.runtime_state import get_last_status
    assert get_last_status("905009999999") is None


def test_record_status_multiple_senders():
    from backend.guards.runtime_state import record_status, get_last_status
    record_status("111", "⚙️ A")
    record_status("222", "⚙️ B")
    assert get_last_status("111")["text"] == "⚙️ A"
    assert get_last_status("222")["text"] == "⚙️ B"


def test_record_status_non_gear_ignored():
    from backend.guards.runtime_state import record_status, get_last_status
    record_status("905001234567", "normal mesaj")
    assert get_last_status("905001234567") is None


def test_ttl_eviction():
    """TTL süresi geçen kayıtlar temizlenmeli."""
    import backend.guards.runtime_state as rs
    number = "905001234567"
    now = time.time()
    # TTL süresi geçmiş kayıt manuel olarak ekle
    rs._last_status[number] = {"text": "⚙️ eski", "ts": now - rs._STATUS_TTL - 1}
    rs._last_cleanup = 0.0  # temizlik zorla çalışsın

    # Yeni bir kayıt ekle → _maybe_evict tetiklenir
    rs.record_status("905009999999", "⚙️ yeni")
    assert rs.get_last_status(number) is None
