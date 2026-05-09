"""Platform-bağımsız backup import yardımcıları — WhatsApp ve Telegram router'larınca kullanılır.

SRP: Yalnızca .99rb dosyası geldiğinde import akışını yönetir.
     Platform-özel indirme (WhatsApp media API, Telegram file API) çağıran tarafça yapılır;
     bu modül indirilen byte'ları alır, /tmp'ye yazar, ImportService'i çağırır ve sonucu gönderir.

OCP: Yeni platform = çağıran tarafça bu modülün fonksiyonu kullanılır; modül değişmez.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_BACKUP_EXT = ".99rb"


def is_backup_pending(session: dict) -> bool:
    """Import akışı bekliyor mu?"""
    return bool(session.get("pending_backup_import"))


async def handle_backup_bytes(
    sender: str,
    filename: str,
    raw_bytes: bytes,
    session: dict,
) -> bool:
    """İndirilen dosya byte'larından import akışını çalıştırır.

    Args:
        sender:    Gönderen kimliği.
        filename:  Orijinal dosya adı (uzantı kontrolü için).
        raw_bytes: İndirilen dosyanın ham içeriği.
        session:   Kullanıcı session dict'i.

    Returns:
        True → işlendi (caller'ın başka işlem yapmasına gerek yok).
        False → .99rb değildi veya pending import flag yoktu.
    """
    from ..adapters.messenger import get_messenger
    from ..features.backup._protocol import ImportMode
    from ..features.import_service import get_import_service
    from ..i18n import t

    lang  = session.get("lang", "tr")
    send  = get_messenger().send_text

    if not is_backup_pending(session):
        return False

    if not filename.lower().endswith(_BACKUP_EXT):
        await send(sender, t("backup.import_bad_file", lang))
        session.clear_backup_import()
        return True

    session.clear_backup_import()

    tmp_path = Path(f"/tmp/import_{uuid.uuid4().hex}.99rb")
    try:
        tmp_path.write_bytes(raw_bytes)
        service = get_import_service()
        result  = await service.restore_backup(tmp_path, ImportMode.MERGE)
    except ValueError as exc:
        logger.warning("Backup import format hatası: %s", exc)
        await send(sender, t("backup.import_error", lang, error=str(exc)))
        return True
    except Exception as exc:
        logger.exception("Backup import beklenmeyen hata: %s", exc)
        await send(sender, t("backup.import_error", lang, error=str(exc)))
        return True
    finally:
        tmp_path.unlink(missing_ok=True)

    rows   = sum(result.rows_inserted.values())
    tables = len(result.tables_processed)
    files  = 0  # FileImporter sonucu ImportResult'ta ayrı değil; ileride eklenebilir

    await send(sender, t("backup.import_ok", lang, rows=rows, tables=tables, files=files))

    # env_config.env yedekte varsa kullanıcıyı bilgilendir
    try:
        from ..config import settings as _settings
        env_config_path = _settings.resolved_data_dir / "env_config.env"
        if env_config_path.exists():
            await send(sender, t("backup.import_env_found", lang))
    except Exception:
        pass  # bildirim opsiyonel — ana akışı etkilemez

    return True
