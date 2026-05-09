"""EnvExporter — ortam konfigürasyonu dışa aktarım implementasyonu.

SRP: Yalnızca settings nesnesinden env_config.env byte'ları üretme sorumluluğu taşır.
     Orchestration → ExportService; binary format → BackupWriter.

Davranış:
  - settings nesnesi üzerinden tüm alanları okur (.env dosyasına doğrudan erişilmez).
  - SecretStr alanlar .get_secret_value() ile açılır.
  - CREDENTIAL_* site credential'ları da dahil edilir.
  - scope.include_env_config=False ise boş dict döndürür — işlem yapılmaz.

Güvenlik:
  - Şifreleme etkin değilse WARNING loglanır (plain-text arşiv).
  - Üretilen dosya yalnızca ExportService aracılığıyla arşive eklenir.
  - Import sonrası dosya data/env_config.env yolunda yer alır — .env DEĞİL.

Çıktı formatı:
  Shell-kaynak uyumlu KEY=VALUE satırları (yorum satırları # ile başlar).
  Kullanıcı bu dosyayı gözden geçirip scripts/backend/.env'e manuel birleştirmelidir.

OCP: Yeni settings alanı → settings.model_fields otomatik olarak yakalar;
     bu modül değiştirilmez.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ._scope import ExportScope

logger = logging.getLogger(__name__)

ENV_FILE_KEY = "env_config.env"
"""file_data içindeki anahtar — LocalFileImporter bu yolu data/ altına yazar."""


class EnvExporter:
    """settings nesnesinden env_config.env bytes üretir.

    FileExporter protokolünü (kısmen) uygular — DIP uyumlu.
    Bağımlılık: settings nesnesi (constructor enjeksiyonu; None → lazy import).

    OOP notu: Tüm alan yineleme mantığı _collect_lines() özel metodundadır (SRP).
    """

    def __init__(self, settings=None) -> None:
        """
        Args:
            settings: Settings nesnesi. None ise ilk çağrıda lazy import ile alınır.
        """
        self._settings = settings

    # ------------------------------------------------------------------
    # FileExporter Protokolü (kısmi)
    # ------------------------------------------------------------------

    async def export(self, scope: "ExportScope") -> dict[str, bytes]:
        """Kapsama göre env_config.env üretir.

        Args:
            scope: include_env_config=False ise boş dict döndürür.

        Returns:
            {ENV_FILE_KEY: bytes} veya boş dict.
        """
        if not scope.include_env_config:
            return {}
        return await asyncio.to_thread(self._sync_export)

    # ------------------------------------------------------------------
    # Özel yardımcılar
    # ------------------------------------------------------------------

    def _sync_export(self) -> dict[str, bytes]:
        from ..config import settings as default_settings

        s = self._settings or default_settings
        self._warn_if_unencrypted(s)

        lines = self._collect_lines(s)
        content = "\n".join(lines) + "\n"

        logger.info(
            "EnvExporter: env_config.env üretildi — %d satır (%d B)",
            len(lines),
            len(content),
        )
        return {ENV_FILE_KEY: content.encode("utf-8")}

    def _warn_if_unencrypted(self, s) -> None:
        """Şifreleme yoksa uyarı loglar."""
        try:
            enc_key = s.backup_encryption_key.get_secret_value()
        except Exception:
            enc_key = ""
        if not enc_key:
            logger.warning(
                "EnvExporter: include_env_config=True ancak şifreleme devre dışı. "
                "Hassas tokenlar plain-text arşivde yer alacak. "
                "BACKUP_ENCRYPTION_KEY ayarlamanız önerilir."
            )

    def _collect_lines(self, s) -> list[str]:
        """Settings nesnesinden KEY=VALUE satır listesi oluşturur."""
        from pydantic import SecretStr

        lines: list[str] = [
            f"# 99-root env config — exported {datetime.now(tz=timezone.utc).isoformat()}",
            "# UYARI / WARNING: Bu dosya hassas token/secret değerler içerir.",
            "# Bu dosyayı gözden geçirip scripts/backend/.env dosyanıza birleştirin.",
            "# Do NOT commit or share this file.",
            "#",
        ]

        # settings model alanları — pydantic model_fields (properties hariç)
        for field_name in s.model_fields:
            value = getattr(s, field_name, None)
            if isinstance(value, SecretStr):
                raw = value.get_secret_value()
            elif isinstance(value, bool):
                raw = "true" if value else "false"
            elif value is None:
                raw = ""
            else:
                raw = str(value)

            if raw:  # boş değerleri atla — .env.example'dan gelir zaten
                env_key = field_name.upper()
                lines.append(f"{env_key}={raw}")

        # Site credential'ları (CREDENTIAL_* — model_fields dışında os.environ'da)
        try:
            for slug in s.list_site_credentials():
                user = s.get_site_credential(slug, "user") or ""
                passwd = s.get_site_credential(slug, "pass") or ""
                if user:
                    lines.append(f"CREDENTIAL_{slug.upper()}_USER={user}")
                if passwd:
                    lines.append(f"CREDENTIAL_{slug.upper()}_PASS={passwd}")
        except Exception as exc:
            logger.warning("EnvExporter: site credential'lar okunamadı — %s", exc)

        return lines
