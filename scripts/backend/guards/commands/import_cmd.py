"""/import komutu — .99rb yedek dosyasını geri yükler.

Akış:
  /import
      ↓
  "Lütfen .99rb yedek dosyasını gönderin"   (session["pending_backup_import"] = True)
      ↓ (kullanıcı dosya gönderir)
  _backup_import_handler → download → ImportService.restore_backup(path, MERGE)
      ↓
  "✅ İçe aktarım tamamlandı: ..."

İptal: /cancel → pending_backup_import temizlenir.

Rapor referansı: §5.2.
"""
from __future__ import annotations

from .registry import registry
from ..permission import Perm


class ImportCommand:
    """Import akışını başlatır — kullanıcıdan .99rb dosyası bekler.

    SRP: Yalnızca session flag'ini set eder ve kullanıcıyı yönlendirir.
         Asıl import mantığı routers/_backup_import_handler.py'dedir.
    """

    cmd_id      = "/import"
    perm        = Perm.OWNER
    label       = "Yedekten Geri Yükle"
    description = "Gönderilen .99rb yedek dosyasını veritabanına geri yükler."
    usage       = "/import"

    async def execute(self, sender: str, arg: str, session: dict) -> None:  # noqa: ARG002
        from ...adapters.messenger import get_messenger
        from ...i18n import t

        lang = session.get("lang", "tr")
        session.set_pending_backup_import()
        await get_messenger().send_text(sender, t("backup.import_prompt", lang))


registry.register(ImportCommand())
