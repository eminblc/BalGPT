"""BackupManifest — yedek dosyası meta verisi.

SRP: Yalnızca meta veriyi taşır; okuma/yazma mantığı içermez.
BackupWriter ve BackupReader (BACKUP-2) tarafından kullanılır.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class BackupManifest:
    """`.99rb` yedek dosyasının başlık meta verisi.

    Alanlar:
        version: Backup format versiyonu (şu an 1).
        created_at: ISO-8601 UTC timestamp.
        hostname: Yedeğin oluşturulduğu makine adı.
        app_version: Uygulama versiyonu etiketi.
        scope_flags: ExportScope.to_flags_dict() çıktısı.
        table_row_counts: Her tablo için dışa aktarılan satır sayısı.
        file_count: Dışa aktarılan dosya sayısı (conv_history + project_files).
        checksum: Sıkıştırılmış data bloğunun SHA-256 hex digest'i.
    """

    version: int = 1
    created_at: str = ""
    hostname: str = ""
    app_version: str = "99-root"
    scope_flags: dict = field(default_factory=dict)
    table_row_counts: dict[str, int] = field(default_factory=dict)
    file_count: int = 0
    checksum: str = ""

    # ---------------------------------------------------------------------------
    # Factory
    # ---------------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        scope_flags: dict,
        table_row_counts: dict[str, int] | None = None,
        file_count: int = 0,
        checksum: str = "",
    ) -> "BackupManifest":
        """Geçerli makine/zaman bilgisiyle yeni bir manifest oluşturur."""
        return cls(
            version=1,
            created_at=datetime.now(timezone.utc).isoformat(),
            hostname=_get_hostname(),
            app_version="99-root",
            scope_flags=scope_flags,
            table_row_counts=table_row_counts or {},
            file_count=file_count,
            checksum=checksum,
        )

    # ---------------------------------------------------------------------------
    # Serileştirme yardımcıları
    # ---------------------------------------------------------------------------

    def to_dict(self) -> dict:
        """msgpack ile serileştirilebilir sözlük döndürür."""
        return {
            "version": self.version,
            "created_at": self.created_at,
            "hostname": self.hostname,
            "app_version": self.app_version,
            "scope_flags": self.scope_flags,
            "table_row_counts": self.table_row_counts,
            "file_count": self.file_count,
            "checksum": self.checksum,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BackupManifest":
        """Sözlükten BackupManifest örneği oluşturur."""
        return cls(
            version=data.get("version", 1),
            created_at=data.get("created_at", ""),
            hostname=data.get("hostname", ""),
            app_version=data.get("app_version", "99-root"),
            scope_flags=data.get("scope_flags", {}),
            table_row_counts=data.get("table_row_counts", {}),
            file_count=data.get("file_count", 0),
            checksum=data.get("checksum", ""),
        )


# ---------------------------------------------------------------------------
# Özel yardımcı
# ---------------------------------------------------------------------------


def _get_hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"
