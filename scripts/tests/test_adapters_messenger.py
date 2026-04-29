"""Messenger factory ve singleton davranışı testleri."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture(autouse=True)
def reset_messenger_singleton():
    """Her test öncesi singleton'ı sıfırla."""
    import backend.adapters.messenger.messenger_factory as mf
    mf._instance = None
    yield
    mf._instance = None


# ── get_messenger factory ─────────────────────────────────────────

def test_get_messenger_whatsapp():
    mock_settings = MagicMock()
    mock_settings.messenger_type = "whatsapp"
    mock_settings.environment = "test"

    with patch("backend.adapters.messenger.messenger_factory.settings", mock_settings):
        from backend.adapters.messenger.messenger_factory import get_messenger
        from backend.adapters.messenger.whatsapp_messenger import WhatsAppMessenger
        m = get_messenger()
    assert isinstance(m, WhatsAppMessenger)


def test_get_messenger_telegram():
    mock_settings = MagicMock()
    mock_settings.messenger_type = "telegram"
    mock_settings.environment = "test"

    with patch("backend.adapters.messenger.messenger_factory.settings", mock_settings):
        from backend.adapters.messenger.messenger_factory import get_messenger
        from backend.adapters.messenger.telegram_messenger import TelegramMessenger
        m = get_messenger()
    assert isinstance(m, TelegramMessenger)


def test_get_messenger_cli():
    mock_settings = MagicMock()
    mock_settings.messenger_type = "cli"
    mock_settings.environment = "test"

    with patch("backend.adapters.messenger.messenger_factory.settings", mock_settings):
        from backend.adapters.messenger.messenger_factory import get_messenger
        from backend.adapters.messenger.cli_messenger import CLIMessenger
        m = get_messenger()
    assert isinstance(m, CLIMessenger)


def test_get_messenger_singleton():
    """İki kez çağrıldığında aynı örnek dönmeli."""
    mock_settings = MagicMock()
    mock_settings.messenger_type = "cli"
    mock_settings.environment = "test"

    with patch("backend.adapters.messenger.messenger_factory.settings", mock_settings):
        from backend.adapters.messenger.messenger_factory import get_messenger
        m1 = get_messenger()
        m2 = get_messenger()
    assert m1 is m2


def test_get_messenger_unknown_non_production_fallback():
    """Bilinmeyen type + non-production → WhatsApp fallback."""
    mock_settings = MagicMock()
    mock_settings.messenger_type = "unknown_platform"
    mock_settings.environment = "test"

    with patch("backend.adapters.messenger.messenger_factory.settings", mock_settings):
        from backend.adapters.messenger.messenger_factory import get_messenger
        from backend.adapters.messenger.whatsapp_messenger import WhatsAppMessenger
        m = get_messenger()
    assert isinstance(m, WhatsAppMessenger)


def test_get_messenger_unknown_production_raises():
    """Bilinmeyen type + production → ValueError fırlatmalı."""
    mock_settings = MagicMock()
    mock_settings.messenger_type = "unknown_platform"
    mock_settings.environment = "production"

    with patch("backend.adapters.messenger.messenger_factory.settings", mock_settings):
        from backend.adapters.messenger.messenger_factory import get_messenger
        with pytest.raises(ValueError, match="unknown_platform"):
            get_messenger()


# ── register_messenger OCP extension ─────────────────────────────

def test_register_messenger_custom():
    from backend.adapters.messenger.messenger_factory import register_messenger, _MESSENGERS

    class _FakeMessenger:
        async def send_text(self, to, text): pass
        async def send_buttons(self, to, text, buttons): pass
        async def send_list(self, to, text, sections): pass

    register_messenger("fake_platform", _FakeMessenger)
    assert "fake_platform" in _MESSENGERS
    # Temizlik
    del _MESSENGERS["fake_platform"]


# ── CLIMessenger temel davranış ───────────────────────────────────

@pytest.mark.asyncio
async def test_cli_messenger_send_text_no_error():
    from backend.adapters.messenger.cli_messenger import CLIMessenger
    m = CLIMessenger()
    # Çıktıyı stdout'a yazmalı, exception fırlatmamalı
    await m.send_text("905001234567", "Merhaba")


@pytest.mark.asyncio
async def test_cli_messenger_send_buttons_no_error():
    from backend.adapters.messenger.cli_messenger import CLIMessenger
    m = CLIMessenger()
    await m.send_buttons("905001234567", "Seç", [{"id": "a", "title": "A"}])


@pytest.mark.asyncio
async def test_cli_messenger_send_list_no_error():
    from backend.adapters.messenger.cli_messenger import CLIMessenger
    m = CLIMessenger()
    await m.send_list("905001234567", "Liste", [{"title": "S1", "rows": []}])


@pytest.mark.asyncio
async def test_cli_messenger_send_image_no_error():
    from backend.adapters.messenger.cli_messenger import CLIMessenger
    m = CLIMessenger()
    await m.send_image("905001234567", "/tmp/test.png", caption="Ekran görüntüsü")


@pytest.mark.asyncio
async def test_cli_messenger_send_video_no_error():
    from backend.adapters.messenger.cli_messenger import CLIMessenger
    m = CLIMessenger()
    await m.send_video("905001234567", "/tmp/test.mp4", caption="Video")


@pytest.mark.asyncio
async def test_cli_messenger_send_document_no_error():
    from backend.adapters.messenger.cli_messenger import CLIMessenger
    m = CLIMessenger()
    await m.send_document("905001234567", "/tmp/test.pdf", filename="rapor.pdf", caption="PDF")


@pytest.mark.asyncio
async def test_cli_messenger_send_list_with_rows():
    """send_list, section row'larını hatasız işlemeli."""
    from backend.adapters.messenger.cli_messenger import CLIMessenger
    m = CLIMessenger()
    sections = [
        {
            "title": "Bölüm 1",
            "rows": [
                {"id": "r1", "title": "Satır 1", "description": "Açıklama"},
                {"id": "r2", "title": "Satır 2"},
            ],
        }
    ]
    await m.send_list("905001234567", "Başlık", sections)


def test_cli_messenger_supports_interactive_buttons():
    """CLIMessenger interaktif buton desteğini bildirmeli."""
    from backend.adapters.messenger.cli_messenger import CLIMessenger
    assert CLIMessenger.supports_interactive_buttons is True


def test_cli_messenger_supports_media():
    """CLIMessenger medya desteğini bildirmeli."""
    from backend.adapters.messenger.cli_messenger import CLIMessenger
    assert CLIMessenger.supports_media is True
