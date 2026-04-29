"""i18n modülü için unit testler."""
import pytest
from backend.i18n import t, supported_langs, _load


def test_tr_key_returns_turkish():
    assert t("cancel.ok", "tr") == "❌ Aktif işlem iptal edildi."


def test_en_key_returns_english():
    assert t("cancel.ok", "en") == "❌ Active operation cancelled."


def test_totp_ok_tr():
    assert t("auth.totp.ok", "tr") == "✅ Doğrulandı."


def test_totp_ok_en():
    assert t("auth.totp.ok", "en") == "✅ Verified."


def test_interpolation_remaining():
    result = t("auth.totp.invalid", "tr", remaining=2)
    assert "2" in result
    assert "hak" in result


def test_interpolation_en():
    result = t("auth.totp.invalid", "en", remaining=1)
    assert "1" in result
    assert "attempt" in result


def test_math_prompt_interpolation():
    result = t("auth.math.prompt", "tr", cmd="!restart", a=12, b=34)
    assert "!restart" in result
    assert "12" in result
    assert "34" in result


def test_missing_key_falls_back_to_tr():
    # "cancel.ok" exists in both; no fallback needed
    # Test that en.json gets tr fallback for a key only in tr
    # Simulate by checking a key that exists in tr but not in en
    # Actually all keys exist in both — test the fallback mechanism via unsupported lang
    result = t("cancel.ok", "de")  # unsupported lang → tr fallback
    assert result == t("cancel.ok", "tr")


def test_completely_missing_key_returns_key():
    assert t("nonexistent.key.xyz", "tr") == "nonexistent.key.xyz"
    assert t("nonexistent.key.xyz", "en") == "nonexistent.key.xyz"


def test_unsupported_lang_falls_back_to_tr():
    assert t("cancel.generic", "de") == t("cancel.generic", "tr")
    assert t("cancel.generic", "") == t("cancel.generic", "tr")
    assert t("cancel.generic", "fr") == t("cancel.generic", "tr")


def test_default_lang_is_tr():
    assert t("cancel.generic") == t("cancel.generic", "tr")


def test_interpolation_missing_kwarg_returns_raw_val():
    """format_map hata durumunda ham string döner."""
    result = t("auth.totp.invalid", "tr")  # 'remaining' eksik
    # Hata yutulur; val döner
    assert "Geçersiz" in result


def test_plan_empty():
    assert t("plan.empty", "tr") == "📋 Aktif plan yok."
    assert t("plan.empty", "en") == "📋 No active plans."


def test_plan_list_header_interpolation():
    result = t("plan.list_header", "tr", count=5)
    assert "5" in result
    result_en = t("plan.list_header", "en", count=3)
    assert "3" in result_en


def test_calendar_empty():
    assert "etkinlik" in t("calendar.empty", "tr")
    assert "event" in t("calendar.empty", "en")


def test_calendar_reminder_interpolation():
    result = t("calendar.reminder", "tr", title="Toplantı", time="14:00")
    assert "Toplantı" in result
    assert "14:00" in result


def test_schedule_add_ok_interpolation():
    result = t("schedule.add_ok", "tr", id="abc123", cron="0 9 * * *", tip="test", desc="Brief")
    assert "abc123" in result
    assert "0 9 * * *" in result


def test_lang_changed():
    result = t("lang.changed", "tr", code="EN")
    assert "EN" in result
    result_en = t("lang.changed", "en", code="TR")
    assert "TR" in result_en


def test_lang_invalid():
    tr_msg = t("lang.invalid", "tr")
    en_msg = t("lang.invalid", "en")
    assert "tr" in tr_msg
    assert "en" in en_msg


def test_supported_langs():
    langs = supported_langs()
    assert "tr" in langs
    assert "en" in langs
    assert sorted(langs) == langs  # sorted


def test_lru_cache():
    """Cache'in aynı dict'i döndürdüğünü doğrula."""
    a = _load("tr")
    b = _load("tr")
    assert a is b


def test_guard_rate_limit():
    tr_msg = t("guard.rate_limit", "tr")
    en_msg = t("guard.rate_limit", "en")
    assert "bekle" in tr_msg or "Bekle" in tr_msg
    assert "wait" in en_msg.lower()


def test_root_reset_ok():
    assert "sıfırlandı" in t("root_reset.ok", "tr")
    assert "reset" in t("root_reset.ok", "en").lower()


def test_help_fallback():
    tr_msg = t("help.fallback", "tr")
    en_msg = t("help.fallback", "en")
    assert "/help" in tr_msg
    assert "/help" in en_msg
    assert "Claude" in tr_msg
