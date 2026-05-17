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


# ── SEC-SCAN2-S2 — Concurrent singleton (get_messenger) ──────────

def test_get_messenger_concurrent_same_instance():
    """10 thread aynı anda get_messenger() çağırırsa hepsi aynı instance'ı döndürmeli (SEC-SCAN2-S2)."""
    import threading

    import backend.adapters.messenger.messenger_factory as mf
    mf._instance = None  # fixture autouse sıfırladı ama ek güvence

    mock_settings = MagicMock()
    mock_settings.messenger_type = "cli"
    mock_settings.environment = "test"

    results: list = []
    errors: list = []

    def _call():
        try:
            with patch("backend.adapters.messenger.messenger_factory.settings", mock_settings):
                from backend.adapters.messenger.messenger_factory import get_messenger
                results.append(get_messenger())
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_call) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread'lerden hata geldi: {errors}"
    assert len(results) == 10, "Tüm thread'ler sonuç döndürmeli"
    # Hepsi aynı instance olmalı
    first = results[0]
    for instance in results[1:]:
        assert instance is first, "Singleton ihlali: farklı instance'lar döndü"


def test_get_messenger_singleton_reset_then_recreate():
    """_instance=None sonrası get_messenger() yeni instance oluşturmalı (SEC-SCAN2-S2)."""
    import backend.adapters.messenger.messenger_factory as mf

    mock_settings = MagicMock()
    mock_settings.messenger_type = "cli"
    mock_settings.environment = "test"

    with patch("backend.adapters.messenger.messenger_factory.settings", mock_settings):
        from backend.adapters.messenger.messenger_factory import get_messenger
        first = get_messenger()

    # Singleton sıfırla
    mf._instance = None

    with patch("backend.adapters.messenger.messenger_factory.settings", mock_settings):
        from backend.adapters.messenger.messenger_factory import get_messenger
        second = get_messenger()

    # Yeniden oluşturuldu — aynı tip ama farklı nesne olabilir
    from backend.adapters.messenger.cli_messenger import CLIMessenger
    assert isinstance(second, CLIMessenger)


# ── SEC-SCAN2-S3 — Concurrent singleton (get_media_downloader) ───

def test_get_media_downloader_concurrent_same_instance():
    """5 thread aynı anda get_media_downloader() çağırırsa hepsi aynı instance döndürmeli (SEC-SCAN2-S3)."""
    import threading

    import backend.adapters.media.media_factory as mf_media
    # Önce downloaders'ın kayıtlı olduğundan emin ol
    import backend.adapters.media  # noqa: F401 — register_downloader side-effects için
    mf_media._instance = None

    mock_settings = MagicMock()
    mock_settings.messenger_type = "whatsapp"

    results: list = []
    errors: list = []

    def _call():
        try:
            with patch("backend.config.settings", mock_settings):
                from backend.adapters.media.media_factory import get_media_downloader
                results.append(get_media_downloader())
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_call) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Cleanup
    mf_media._instance = None

    assert not errors, f"Thread'lerden hata geldi: {errors}"
    assert len(results) == 5, "Tüm thread'ler sonuç döndürmeli"
    first = results[0]
    for instance in results[1:]:
        assert instance is first, "MediaDownloader singleton ihlali: farklı instance'lar döndü"


def test_get_media_downloader_singleton_reset_then_recreate():
    """_instance=None sonrası get_media_downloader() yeni instance oluşturmalı (SEC-SCAN2-S3)."""
    import backend.adapters.media.media_factory as mf_media
    import backend.adapters.media  # noqa: F401 — register_downloader side-effects
    mf_media._instance = None

    mock_settings = MagicMock()
    mock_settings.messenger_type = "whatsapp"

    with patch("backend.config.settings", mock_settings):
        from backend.adapters.media.media_factory import get_media_downloader
        first = get_media_downloader()

    mf_media._instance = None

    with patch("backend.config.settings", mock_settings):
        second = get_media_downloader()

    from backend.adapters.media.whatsapp_downloader import WhatsAppMediaDownloader
    assert isinstance(second, WhatsAppMediaDownloader)

    # Cleanup
    mf_media._instance = None
