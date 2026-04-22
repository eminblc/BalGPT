"""Uygulama geneli statik sabitler.

Deployment'tan bağımsız, ortam değişkeninden okunmaz.
Yalnızca platform spec'leri, API limitleri ve uygulama politikası sabitleri buraya girer.
Konfigüre edilebilir değerler → config.py (Settings).
"""

# ── WhatsApp Cloud API limitleri ──────────────────────────────────────────────
# Meta tarafından tanımlı; değiştirilemez.
WA_MAX_LEN            = 4096          # send_text: otomatik bölme eşiği (karakter)
WA_OUTBOUND_TTL       = 3600.0        # saniye — outbound dedup girişi TTL'i
WA_IBTN_BODY_MAX      = 1024          # interactive button body.text max karakter
WA_LIST_BODY_MAX      = 4096          # interactive list body.text max karakter
WA_LIST_BTN_MAX       = 20            # send_list action.button label max karakter
WA_BTN_TITLE_MAX      = 20            # send_buttons reply button title max karakter
WA_SECTION_TITLE_MAX  = 24            # section title max karakter
WA_ROW_TITLE_MAX      = 24            # row title max karakter
WA_ROW_DESC_MAX       = 72            # row description max karakter
WA_MAX_MEDIA_BYTES    = 50 * 1024 * 1024  # 50 MB — medya indirme bellek koruması

# ── Telegram Bot API limitleri ────────────────────────────────────────────────
# Telegram tarafından tanımlı; değiştirilemez.
TG_MAX_LEN = 4096   # sendMessage: otomatik bölme eşiği (karakter)

# ── Uygulama çıktı limitleri ──────────────────────────────────────────────────
TERMINAL_MAX_OUTPUT_CHARS = 3500   # terminal: kullanıcıya iletilen çıktı üst sınırı
PDF_MAX_PAGES             = 30     # pdf_importer: işlenen maksimum sayfa sayısı
LLM_MAX_TOKENS_DEFAULT    = 4096   # anthropic_provider: varsayılan maksimum çıktı token sayısı

# ── Kimlik doğrulama güvenlik limitleri ───────────────────────────────────────
TOTP_MAX_ATTEMPTS = 3   # art arda başarısız TOTP denemesi → kilit
MATH_MAX_ATTEMPTS = 3   # art arda başarısız matematik sorusu denemesi → iptal

# ── Bridge izleme parametreleri ───────────────────────────────────────────────
BRIDGE_CHECK_INTERVAL_SEC  = 60    # saniye — sağlık kontrolü aralığı
BRIDGE_AUTO_RESTART_AFTER  = 3     # art arda başarısızlık eşiği → otomatik restart
BRIDGE_RESTART_TIMEOUT_SEC = 15    # systemctl restart maksimum bekleme süresi (saniye)

# ── Desktop otomasyonu ────────────────────────────────────────────────────────
DESKTOP_BATCH_MAX_ACTIONS = 20   # tek batch isteğinde maksimum aksiyon sayısı
