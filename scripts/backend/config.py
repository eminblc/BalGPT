"""Uygulama konfigürasyonu — tüm ayarlar tek yerden (SRP).

.env dosyasından okunur. Başka modüller doğrudan os.environ'a erişmez.
"""
from __future__ import annotations

import os
from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── WhatsApp Cloud API ────────────────────────────────────────
    whatsapp_phone_id: str = ""
    whatsapp_token: SecretStr = SecretStr("")
    whatsapp_verify_token: str = ""
    whatsapp_app_secret: SecretStr = SecretStr("")
    whatsapp_owner: str = ""          # Tek kullanıcı numarası (E.164 format)
    whatsapp_api_version: str = "v19.0"

    # ── API güvenliği ─────────────────────────────────────────────
    api_key: SecretStr = SecretStr("")           # X-Api-Key header
    totp_secret: SecretStr = SecretStr("")       # Owner TOTP doğrulaması için (tüm komutlar)

    # ── Claude Code Bridge ────────────────────────────────────────
    claude_bridge_url: str = "http://127.0.0.1:8013"
    claude_code_permissions: str = "bypassPermissions"
    bridge_client_timeout: int = 1800  # saniye — uzun işlemler için (varsayılan 30 dk)

    # ── LLM ──────────────────────────────────────────────────────
    anthropic_api_key: SecretStr = SecretStr("")
    default_model: str = "claude-sonnet-4-6"
    intent_classifier_model: str = "claude-haiku-4-5-20251001"  # Niyet sınıflandırma için hız/maliyet optimizasyonu
    wizard_llm_model: str = "claude-haiku-4-5-20251001"         # Wizard scaffold mimari önizlemesi için (WIZ-LLM-2)

    # LLM adaptör seçimi
    llm_backend: str = "anthropic"          # "anthropic" | "ollama" | "gemini"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3"

    # Google Gemini
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = "gemini-2.0-flash"

    # ── Depolama ─────────────────────────────────────────────────
    # Not: db_path, scheduler_db_path, sessions_dir, conv_history_dir,
    # active_context_path, media_dir alanları şu an kod tarafından okunmuyor
    # (yollar sqlite_store.py ve server.js içinde doğrudan tanımlı).
    # İleride merkezi yol yönetimi için bu alanlar aktif hale getirilecek (K6).
    projects_dir: str = ""   # Boş bırakılırsa DEFAULT_PROJECTS_DIR (33-projects/) kullanılır
    pdf_tmp_dir: str = "/tmp/personal-agent-pdf"  # PDF indirme geçici dizini

    @property
    def resolved_projects_dir(self) -> Path:
        """Proje kök dizini — PROJECTS_DIR env var'ı veya varsayılan 33-projects/."""
        if self.projects_dir:
            return Path(self.projects_dir)
        from .app_types import DEFAULT_PROJECTS_DIR
        return DEFAULT_PROJECTS_DIR

    # ── Oturum ───────────────────────────────────────────────────
    session_ttl_hours: int = 24       # Oturum inaktivite süresi

    # ── Servis ───────────────────────────────────────────────────
    port: int = 8010
    log_level: str = "INFO"
    environment: str = "development"   # "production" | "development"
    cors_origins: str = "http://localhost:5678"  # Virgülle ayrılmış origin listesi

    # ── Webhook Proxy ─────────────────────────────────────────────
    webhook_proxy: str = "none"        # ngrok | cloudflared | external | none
    public_url: str = ""               # WEBHOOK_PROXY=external ise zorunlu (https://...)
    ngrok_authtoken: str = ""          # NGROK_AUTHTOKEN — ngrok auth token (opsiyonel)
    ngrok_domain: str = ""             # NGROK_DOMAIN — static domain (e.g. yourname.ngrok-free.app)

    # ── Messenger adaptörü ───────────────────────────────────────
    messenger_type: str = "whatsapp"   # "whatsapp" | "telegram"

    # ── Lokalizasyon ─────────────────────────────────────────────
    default_language: str = "tr"       # "tr" | "en" — varsayılan arayüz dili
    timezone: str = "Europe/Istanbul"  # APScheduler ve cron ifadeleri için saat dilimi (IANA)

    # ── Telegram Bot API ──────────────────────────────────────────
    telegram_bot_token: SecretStr = SecretStr("")         # BotFather token (ör. 123456:ABC-DEF...)
    telegram_chat_id: str = ""                            # Varsayılan hedef chat_id (owner)
    telegram_webhook_secret: SecretStr = SecretStr("")    # setWebhook secret_token (X-Telegram-Bot-Api-Secret-Token)

    # ── Yetenek kısıtlamaları — FEAT-3 ──────────────────────────────
    # Pattern A — restrict_* (ters mantık): False = aktif (varsayılan), True = kısıtlı.
    # Mesaj düzeyinde capability guard tarafından uygulanır. Mevcut flagler — geriye uyumlu,
    # değiştirilmez. Yeni capability kuralı eklemek için bu listeye yeni restrict_* field ekle
    # + capability_guard.register_capability_rule().
    restrict_fs_outside_root:   bool = False   # Proje kökü dışı dosya yolu erişimi
    restrict_network:           bool = False   # Dış ağ / HTTP istekleri
    restrict_shell:             bool = False   # Kabuk komutu çalıştırma
    restrict_service_mgmt:      bool = False   # Systemd/tmux servis yönetimi
    restrict_media:             bool = False   # Medya mesajları (image/video/document/audio)
    restrict_calendar:          bool = False   # Takvim ve zamanlanmış görevler
    restrict_project_wizard:    bool = False   # Proje oluşturma wizard'ı
    restrict_screenshot:        bool = False   # Headless browser / ekran görüntüsü
    restrict_scheduler:         bool = False   # APScheduler alt sistemi — bkz. scheduler_enabled property
    restrict_pdf_import:        bool = False   # PDF içe aktarma ve proje dönüştürme hattı
    restrict_conv_history:      bool = False   # Konuşma geçmişi SQLite kaydı (gizlilik)
    restrict_plans:             bool = False   # İş planı oluşturma ve yönetimi (/plan komutları)
    restrict_intent_classifier: bool = False   # LLM tabanlı niyet tespiti (mesaj başına API çağrısı)
    restrict_wizard_llm_scaffold: bool = False # Wizard LLM scaffold (otomatik mimari önizlemesi)

    # ── Feature Toggle'ları ───────────────────────────────────────────
    # Pattern B — <feature>_enabled (düz mantık): True = aktif (varsayılan), False = devre dışı.
    # Startup veya router düzeyinde kontrol edilir. YENİ feature toggle'ları bu pattern'i kullanır.

    # ── Desktop Otomasyon ────────────────────────────────────────
    desktop_enabled:  bool = True   # False → tüm /internal/desktop aksiyonları devre dışı
    system_psswrd: SecretStr = SecretStr("")  # sudo -S ve ekran kilidi açma için (loglara yazılmaz)
    desktop_recording: bool = False     # True → record_screen aksiyonu etkin (FEAT-DESK-REC-1)
    desktop_recording_max_mb: int = 16  # WhatsApp video boyut limiti MB; büyükse yalnızca path döner
    desktop_screenshot_max_width: int = 1280  # Screenshot'lar bu genişliğe resize edilir (0 = kapalı)
    desktop_vision_max_per_session: int = 15  # 5 dk sliding window içinde max vision_query
    desktop_totp_ttl_seconds: int = 900  # Desktop TOTP unlock TTL (saniye); süre dolunca tekrar TOTP istenir

    # ── Tarayıcı Otomasyonu (FEAT-13 / FEAT-15) ─────────────────
    browser_enabled:  bool = True   # False → tüm /internal/browser aksiyonları devre dışı
    browser_headless: bool = True  # True → Chromium headless modda çalışır
    browser_sessions_dir: str = "data/browser_sessions"  # Disk kalıcı storage state dosyaları
    browser_max_sessions: int = 5  # Eş zamanlı açık browser session limiti

    # ── Site-özel credential store (FEAT-16) ─────────────────────
    # Format: CREDENTIAL_<SITE_SLUG>_USER / CREDENTIAL_<SITE_SLUG>_PASS
    # Örnek: CREDENTIAL_MERCEK_ITU_USER=emin  CREDENTIAL_MERCEK_ITU_PASS=sifre
    # Erişim: settings.get_site_credential("mercek_itu", "user")

    def get_site_credential(self, site_slug: str, field: str) -> str | None:
        """
        CREDENTIAL_<SITE_SLUG>_<FIELD> env var değerini döndürür.
        Bulunamazsa None. site_slug ve field büyük/küçük harf duyarsız.
        """
        key = f"CREDENTIAL_{site_slug.upper()}_{field.upper()}"
        val = os.environ.get(key, "")
        return val if val else None

    def list_site_credentials(self) -> list[str]:
        """
        Tanımlı credential slug'larını küçük harfle döndürür.
        Örn: ["mercek_itu", "github"]
        """
        slugs: set[str] = set()
        prefix = "CREDENTIAL_"
        for key in os.environ:
            if key.startswith(prefix):
                rest = key[len(prefix):]        # ör. "MERCEK_ITU_USER"
                parts = rest.rsplit("_", 1)      # ["MERCEK_ITU", "USER"]
                if len(parts) == 2:
                    slugs.add(parts[0].lower())  # "mercek_itu"
        return sorted(slugs)

    # ── Feature Toggle property'leri (MOD-9) ─────────────────────
    # Pattern-B alias'ları: restrict_* (Pattern-A) env var'ları geriye uyumlu korunur.
    # Router/feature kod içinde bu property'leri kullan — `restrict_*` alanlarına doğrudan
    # erişme. Capability guard (mesaj düzeyi) hâlâ `restrict_*` alanlarını doğrudan okur.
    @property
    def scheduler_enabled(self) -> bool:
        """APScheduler alt sistemi etkin mi? Env: RESTRICT_SCHEDULER=true → False."""
        return not self.restrict_scheduler

    @property
    def conv_history_enabled(self) -> bool:
        """Konuşma geçmişi SQLite kaydı etkin mi? Env: RESTRICT_CONV_HISTORY=true → False."""
        return not self.restrict_conv_history

    @property
    def intent_classifier_enabled(self) -> bool:
        """LLM niyet tespiti etkin mi? Env: RESTRICT_INTENT_CLASSIFIER=true → False."""
        return not self.restrict_intent_classifier

    @property
    def pdf_import_enabled(self) -> bool:
        """PDF içe aktarma hattı etkin mi? Env: RESTRICT_PDF_IMPORT=true → False."""
        return not self.restrict_pdf_import

    @property
    def plans_enabled(self) -> bool:
        """İş planı yönetimi etkin mi? Env: RESTRICT_PLANS=true → False."""
        return not self.restrict_plans

    # ── Güvenlik doğrulaması (SRP: startup mantığı config'e ait) ─────────────
    def validate_for_environment(self) -> None:
        """Ortama göre güvenlik gereksinimlerini doğrular.

        Production: eksik kritik değerler RuntimeError fırlatır — servis başlamaz.
        Development: yalnızca uyarı loglanır.

        Raises:
            RuntimeError: Production'da kritik güvenlik değeri eksikse.
        """
        import logging as _logging
        _logger = _logging.getLogger(__name__)
        is_prod = self.environment == "production"
        errors: list[str] = []

        # API Key — /agent/* endpoint'leri
        if not self.api_key.get_secret_value():
            msg = "api_key tanımlı değil — /agent/* endpoint'leri korumasız!"
            if is_prod:
                errors.append(msg)
            else:
                _logger.warning("GÜVENLIK: %s", msg)

        # TOTP secret — rutin komutlar
        if not self.totp_secret.get_secret_value():
            _logger.warning("GÜVENLIK: totp_secret tanımlı değil — TOTP koruması devre dışı!")

        # WhatsApp HMAC
        if not self.whatsapp_app_secret.get_secret_value():
            msg = "whatsapp_app_secret tanımlı değil — HMAC doğrulaması atlanıyor!"
            if is_prod:
                errors.append(msg)
            else:
                _logger.warning("GÜVENLIK: %s", msg)

        # Telegram webhook secret
        if self.messenger_type == "telegram" and not self.telegram_webhook_secret.get_secret_value():
            msg = "telegram_webhook_secret tanımlı değil — Telegram webhook korumasız!"
            if is_prod:
                errors.append(msg)
            else:
                _logger.warning("GÜVENLIK: %s", msg)

        # CORS origins
        _parsed_cors = [o.strip() for o in self.cors_origins.split(",") if o.strip()]
        if not _parsed_cors:
            msg = "cors_origins boş — CORS yalnızca http://localhost:5678 için etkin!"
            if is_prod:
                errors.append(msg)
            else:
                _logger.warning("GÜVENLIK: %s", msg)

        if errors:
            raise RuntimeError(
                "GÜVENLIK: Production ortamında kritik değerler eksik — servis başlatılmadı.\n"
                + "\n".join(f"  • {e}" for e in errors)
            )

    # ── Compat aliases (cloud_api.py uyumu) ──────────────────────
    @property
    def whatsapp_phone_number_id(self) -> str:
        return self.whatsapp_phone_id

    @property
    def whatsapp_access_token(self) -> str:
        return self.whatsapp_token.get_secret_value()

    @property
    def owner_id(self) -> str:
        """Aktif messenger'a göre owner kimliği (WhatsApp numarası veya Telegram chat_id)."""
        if self.messenger_type == "telegram":
            return self.telegram_chat_id
        return self.whatsapp_owner


settings = Settings()


def get_settings() -> Settings:
    """DIP-V2: Feature modülleri settings singleton'ına doğrudan değil bu accessor üzerinden erişir.

    Singleton döndürür — `settings` ile aynı nesne; test ortamında monkeypatching ile
    kolayca değiştirilebilir.
    """
    return settings
