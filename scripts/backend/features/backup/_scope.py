"""ExportScope — dışa aktarım kapsamını tanımlar.

SRP: Sadece "ne dışa aktarılacak" sorusunu yanıtlar.
Orchestration veya serileştirme mantığı içermez.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ExportScope:
    """Hangi veri kümelerinin dışa aktarılacağını tanımlar.

    Tüm flag'ler bağımsızdır; factory metotları sık kullanılan kombinasyonları sağlar.
    """

    # --- Veritabanı tabloları ---
    include_messages: bool = True
    """messages + session_summaries tablolarını içerir."""

    include_plans: bool = True
    """work_plans tablosunu içerir."""

    include_calendar: bool = True
    """calendar_events tablosunu içerir."""

    include_tasks: bool = True
    """scheduled_tasks tablosunu içerir."""

    include_settings: bool = True
    """user_settings tablosunu içerir."""

    include_bridge_calls: bool = False
    """bridge_calls audit log tablosunu içerir (opsiyonel — büyük olabilir)."""

    include_token_usage: bool = False
    """token_usage analitik tablosunu içerir (opsiyonel)."""

    # --- Dosya sistemi ---
    include_conv_history: bool = True
    """data/conv_history/ dizinindeki JSON dosyalarını içerir."""

    include_project_files: bool = True
    """data/projects/ dizinini içerir (CLAUDE.md, BACKLOG.md, kaynak kod)."""

    include_browser_sessions: bool = True
    """data/browser_sessions/ dizinini içerir — Playwright cookie/oturum dosyaları."""

    include_media: bool = False
    """data/media/ dizinini içerir — büyük, varsayılan kapalı."""

    include_env_config: bool = False
    """Ortam konfigürasyonunu (API token, webhook, messenger ayarları) arşive ekler.

    Dikkat: Bu flag, hassas secret değerleri (token, şifre vb.) yedek dosyasına yazar.
    Şifreleme etkinse (BACKUP_ENCRYPTION_KEY) değerler AES-256-GCM ile korunur.
    Şifreleme yoksa plain-text yer alır — dikkatli kullanın.

    Import sonrası değerler data/env_config.env dosyasına yazılır;
    scripts/backend/.env dosyasına manuel olarak birleştirilmesi gerekir.
    """

    # --- Sınırlamalar ---
    messages_limit: int = 10_000
    """Dışa aktarılacak maksimum mesaj sayısı (ORDER BY ts DESC). 0 = tümü."""

    # ---------------------------------------------------------------------------
    # Factory metotları
    # ---------------------------------------------------------------------------

    @classmethod
    def full(cls) -> "ExportScope":
        """Tüm tabloları ve dosyaları kapsar; mesaj sınırı yok."""
        return cls(
            include_bridge_calls=True,
            include_token_usage=True,
            include_media=True,
            messages_limit=0,
        )

    @classmethod
    def essential(cls) -> "ExportScope":
        """Yalnızca kritik ve iş verisi — analitik log ve medya hariç.

        Günlük yedekleme ve makine geçişi için önerilen kapsam.
        """
        return cls(
            include_bridge_calls=False,
            include_token_usage=False,
            include_media=False,
        )

    # ---------------------------------------------------------------------------
    # Yardımcılar
    # ---------------------------------------------------------------------------

    def to_flags_dict(self) -> dict[str, bool | int]:
        """Manifest'e kaydedilmek üzere flag sözlüğü döndürür."""
        return {
            "include_messages": self.include_messages,
            "include_plans": self.include_plans,
            "include_calendar": self.include_calendar,
            "include_tasks": self.include_tasks,
            "include_settings": self.include_settings,
            "include_bridge_calls": self.include_bridge_calls,
            "include_token_usage": self.include_token_usage,
            "include_conv_history": self.include_conv_history,
            "include_project_files": self.include_project_files,
            "include_browser_sessions": self.include_browser_sessions,
            "include_media": self.include_media,
            "include_env_config": self.include_env_config,
            "messages_limit": self.messages_limit,
        }
