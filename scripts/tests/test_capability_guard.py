"""CapabilityGuard ve CapabilityRule testleri (FEAT-3)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from backend.guards.capability_guard import (
    CapabilityGuard,
    CapabilityRule,
    register_capability_rule,
    _RULES,
    _text,
)
from backend.guards.guard_chain import GuardContext


def _ctx(body: str = "", msg_type: str = "text", sender: str = "905001234567"):
    return GuardContext(
        sender=sender,
        msg_id="msg-001",
        msg_type=msg_type,
        msg={"type": "text", "text": {"body": body}},
    )


def _cfg(**flags):
    """Sadece istenen flag'leri True yapan mock config döndürür."""
    cfg = MagicMock()
    cfg.__class__ = object  # getattr fallback için
    # Tüm bilinen restrict_* flag'lerini False yap, sonra üzerine yaz
    known = [
        "restrict_fs_outside_root", "restrict_network", "restrict_shell",
        "restrict_service_mgmt", "restrict_media", "restrict_calendar",
        "restrict_project_wizard", "restrict_screenshot", "restrict_plans",
        "restrict_pdf_import",
    ]
    for k in known:
        setattr(cfg, k, flags.get(k, False))
    return cfg


# ── _text yardımcısı ──────────────────────────────────────────────

def test_text_extracts_body():
    ctx = _ctx("Merhaba Dünya")
    assert _text(ctx) == "merhaba dünya"


def test_text_empty_msg():
    ctx = GuardContext(sender="x", msg_id="y", msg_type="text", msg={})
    assert _text(ctx) == ""


def test_text_missing_text_key():
    ctx = GuardContext(sender="x", msg_id="y", msg_type="image", msg={"type": "image"})
    assert _text(ctx) == ""


# ── Tüm kısıtlamalar devre dışıyken ──────────────────────────────

@pytest.mark.asyncio
async def test_no_restrictions_passes_all():
    guard = CapabilityGuard(_cfg())
    result = await guard.check(_ctx("systemctl stop nginx"))
    assert result.passed is True


# ── restrict_fs_outside_root ──────────────────────────────────────

@pytest.mark.asyncio
async def test_fs_restriction_blocked():
    guard = CapabilityGuard(_cfg(restrict_fs_outside_root=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("/etc/shadow oku"))
    assert result.passed is False
    assert "filesystem" in result.reason


@pytest.mark.asyncio
async def test_fs_restriction_passes_normal():
    guard = CapabilityGuard(_cfg(restrict_fs_outside_root=True))
    result = await guard.check(_ctx("dosyayı göster"))
    assert result.passed is True


# ── restrict_network ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_network_restriction_blocked_url():
    guard = CapabilityGuard(_cfg(restrict_network=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("https://example.com adresine git"))
    assert result.passed is False
    assert "network" in result.reason


@pytest.mark.asyncio
async def test_network_restriction_blocked_curl():
    guard = CapabilityGuard(_cfg(restrict_network=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("curl https://api.example.com"))
    assert result.passed is False


# ── restrict_shell ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_shell_restriction_blocked():
    guard = CapabilityGuard(_cfg(restrict_shell=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("bash komutu çalıştır"))
    assert result.passed is False
    assert "shell" in result.reason


# ── restrict_service_mgmt ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_service_mgmt_restriction_blocked():
    guard = CapabilityGuard(_cfg(restrict_service_mgmt=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("systemctl restart nginx"))
    assert result.passed is False
    assert "service_mgmt" in result.reason


# ── restrict_media ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_media_restriction_blocks_image():
    guard = CapabilityGuard(_cfg(restrict_media=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("", msg_type="image"))
    assert result.passed is False
    assert "media" in result.reason


@pytest.mark.asyncio
async def test_media_restriction_text_passes():
    guard = CapabilityGuard(_cfg(restrict_media=True))
    result = await guard.check(_ctx("normal mesaj", msg_type="text"))
    assert result.passed is True


# ── restrict_calendar ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_restriction_blocked():
    guard = CapabilityGuard(_cfg(restrict_calendar=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("takvime etkinlik ekle"))
    assert result.passed is False
    assert "calendar" in result.reason


# ── restrict_project_wizard ───────────────────────────────────────

@pytest.mark.asyncio
async def test_wizard_restriction_blocked():
    guard = CapabilityGuard(_cfg(restrict_project_wizard=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("yeni proje oluştur"))
    assert result.passed is False
    assert "project_wizard" in result.reason


# ── restrict_plans ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plans_restriction_blocked():
    guard = CapabilityGuard(_cfg(restrict_plans=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("!plan ekle yeni görev"))
    assert result.passed is False
    assert "plans" in result.reason


# ── Bildirim gönderme hatası sessizce yutulmalı ───────────────────

@pytest.mark.asyncio
async def test_notification_failure_does_not_raise():
    guard = CapabilityGuard(_cfg(restrict_network=True))
    mock_msg = AsyncMock()
    mock_msg.send_text.side_effect = Exception("send failed")
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("https://example.com"))
    assert result.passed is False


# ── register_capability_rule OCP extension point ──────────────────

def test_register_custom_rule():
    import re
    _CUSTOM_RE = re.compile(r"\bcustom_keyword\b")
    rule = CapabilityRule(
        "restrict_custom_test",
        "custom_test",
        lambda ctx: bool(_CUSTOM_RE.search(_text(ctx))),
    )
    before = len(_RULES)
    register_capability_rule(rule)
    assert len(_RULES) == before + 1
    # Temizlik
    _RULES.remove(rule)


# ── log_active_restrictions ───────────────────────────────────────

def test_log_active_restrictions_no_exception():
    guard = CapabilityGuard(_cfg(restrict_network=True, restrict_shell=True))
    guard.log_active_restrictions()  # exception fırlatmamalı


def test_log_active_restrictions_none_active():
    guard = CapabilityGuard(_cfg())
    guard.log_active_restrictions()  # exception fırlatmamalı


# ── restrict_screenshot ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_screenshot_restriction_blocked():
    guard = CapabilityGuard(_cfg(restrict_screenshot=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("ekran görüntüsü al"))
    assert result.passed is False
    assert "screenshot" in result.reason


@pytest.mark.asyncio
async def test_screenshot_restriction_passes_normal():
    guard = CapabilityGuard(_cfg(restrict_screenshot=True))
    result = await guard.check(_ctx("bugünkü görevleri listele"))
    assert result.passed is True


# ── restrict_pdf_import ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_pdf_import_restriction_blocked_by_msgtype():
    """document tipi mesaj → restrict_pdf_import tetiklenmeli."""
    guard = CapabilityGuard(_cfg(restrict_pdf_import=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("", msg_type="document"))
    assert result.passed is False
    assert "pdf_import" in result.reason


@pytest.mark.asyncio
async def test_pdf_import_restriction_blocked_by_text():
    """Mesaj içinde 'pdf import' kelimesi → tetiklenmeli."""
    guard = CapabilityGuard(_cfg(restrict_pdf_import=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("şu PDF'i import et lütfen"))
    assert result.passed is False
    assert "pdf_import" in result.reason


@pytest.mark.asyncio
async def test_pdf_import_restriction_text_message_passes():
    """Sıradan metin mesajı → restrict_pdf_import tetiklenmemeli."""
    guard = CapabilityGuard(_cfg(restrict_pdf_import=True))
    result = await guard.check(_ctx("merhaba nasılsın", msg_type="text"))
    assert result.passed is True


# ── Çoklu kural — ilk eşleşme kazanır ────────────────────────────

@pytest.mark.asyncio
async def test_multiple_rules_first_match_wins():
    """Birden fazla kural aktif olduğunda ilk eşleşen kural engellemeli."""
    # Hem shell hem de network aktif; mesaj shell'i tetikliyor
    guard = CapabilityGuard(_cfg(restrict_shell=True, restrict_network=True))
    mock_msg = AsyncMock()
    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", return_value="restricted"):
        result = await guard.check(_ctx("bash ile çalıştır"))
    assert result.passed is False
    # shell kuralı network'ten önce tanımlı — shell tetiklenmeli
    assert "shell" in result.reason


# ── GuardContext lang alanı ───────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limit_uses_lang_from_context():
    """CapabilityGuard mesaj gönderirken ctx.lang kullanmalı (i18n doğruluğu)."""
    guard = CapabilityGuard(_cfg(restrict_network=True))
    mock_msg = AsyncMock()
    captured_lang = []

    def _fake_t(key, lang, **kwargs):
        captured_lang.append(lang)
        return "restricted"

    with patch("backend.adapters.messenger.messenger_factory.get_messenger",
               return_value=mock_msg), \
         patch("backend.i18n.t", side_effect=_fake_t):
        ctx = GuardContext(
            sender="905001234567",
            msg_id="x",
            msg_type="text",
            msg={"text": {"body": "https://example.com"}},
            lang="en",
        )
        result = await guard.check(ctx)

    assert result.passed is False
    assert "en" in captured_lang  # İngilizce locale kullanıldı
