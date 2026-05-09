"""/export komutu — .99rb yedek dosyası oluşturur ve messenger üzerinden gönderir.

Alt komutlar:
  /export              → essential yedek (mesajlar, planlar, takvim, görevler)
  /export full         → tüm veri (medya dahil, sınır yok)
  /export media        → essential + medya dosyaları
  /export env          → essential + ortam konfigürasyonu (token, webhook vb.)

Akış:
  ExportService.create_backup(scope, /tmp/backup_YYYYMMDD.99rb)
      ↓
  MediaMessenger.send_document(path, caption)
      ↓
  os.unlink(tmp_path)

Rapor referansı: §5.2.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .registry import registry
from ..permission import Perm

logger = logging.getLogger(__name__)


class ExportCommand:
    """Yedek oluşturur ve gönderir.

    SRP: Yalnızca export akışını koordine eder.
    DIP: ExportService ve get_messenger() factory üzerinden alınır.
    """

    cmd_id      = "/export"
    perm        = Perm.OWNER
    button_id   = "cmd_export"
    label       = "Yedek Al"
    description = "Veri yedeklerini oluşturur ve dosya olarak gönderir."
    usage       = "/export [full|media]"

    async def execute(self, sender: str, arg: str, session: dict) -> None:
        from ...adapters.messenger import get_messenger, MediaMessenger
        from ...features.backup._scope import ExportScope
        from ...features.export_service import get_export_service
        from ...i18n import t

        lang  = session.get("lang", "tr")
        sub   = arg.strip().lower()
        send  = get_messenger().send_text

        scope = self._resolve_scope(sub)
        if scope is None:
            await send(sender, t("backup.usage", lang))
            return

        await send(sender, t("backup.export_start", lang))

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        tmp_path  = Path(f"/tmp/backup_{timestamp}_{uuid.uuid4().hex[:8]}.99rb")

        try:
            service  = get_export_service()
            manifest = await service.create_backup(scope, tmp_path)
        except Exception as exc:
            logger.exception("Export komutu hatası: %s", exc)
            tmp_path.unlink(missing_ok=True)
            await send(sender, t("backup.export_error", lang, error=str(exc)))
            return

        size_kb  = tmp_path.stat().st_size // 1024
        tables   = len(manifest.table_row_counts)
        files    = manifest.file_count
        caption  = t("backup.export_caption", lang,
                     size=size_kb, tables=tables, files=files)

        messenger = get_messenger()
        if isinstance(messenger, MediaMessenger):
            try:
                await messenger.send_document(sender, str(tmp_path), tmp_path.name, caption)
            except Exception as exc:
                logger.exception("Export dosyası gönderilemedi: %s", exc)
                await send(sender, t("backup.export_send_error", lang, error=str(exc)))
        else:
            # Medya desteği yok — en azından özet gönder
            await send(sender, caption)

        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Geçici export dosyası silinemedi: %s", tmp_path)

    # ------------------------------------------------------------------
    # Özel yardımcılar
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_scope(sub: str):
        """Alt komut adına göre ExportScope döndür; bilinmeyende None."""
        from ...features.backup._scope import ExportScope

        if sub in ("", "essential"):
            return ExportScope.essential()
        if sub == "full":
            return ExportScope.full()
        if sub == "media":
            return ExportScope(include_media=True)
        if sub == "env":
            return ExportScope(include_env_config=True)
        return None


registry.register(ExportCommand())
