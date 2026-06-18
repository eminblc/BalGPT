"""99-root projesi için paylaşılan yardımcı fonksiyonlar (SRP).

scan_cmd ve backlog_cmd tarafından kullanılır; başka hiçbir modüle bağımlılık yoktur.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from ...app_types import ACTIVE_CONTEXT_PATH as _ACTIVE_CONTEXT_PATH

_logger = logging.getLogger(__name__)

# 99-root proje kök dizini — bu dosyanın konumundan türetilir
_ROOT_DIR = Path(__file__).parent.parent.parent.parent.parent.resolve()
_ROOT_PROJECT_ID = "99-root"
_ROOT_PROJECT_NAME = "99-root"


def get_active_root_project() -> dict | None:
    """active_context.json'dan aktif proje bilgisini cascading lookup ile döndür.

    Tek doğruluk kaynağı (single source of truth): /backlog, /scan, /dashboard
    ve bridge tarafından kullanılır. Lookup sırası:
      1. active_root_project  → /root-project ile set edilen
      2. active_project       → proje wizard / focus ile set edilen (fallback)
      3. None                 → ikisi de yoksa

    Bu cascade sayesinde kullanıcı sadece projeyi seçmiş olsa bile
    (örn. wizard üzerinden), /backlog ve /scan komutları o projeyi
    otomatik olarak hedef alır; ayrıca /root-project çağırması gerekmez.
    """
    try:
        if not _ACTIVE_CONTEXT_PATH.exists():
            return None
        ctx = json.loads(_ACTIVE_CONTEXT_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        _logger.warning("active_context.json okunamadı: %s", exc)
        return None

    rp = ctx.get("active_root_project")
    if rp and rp.get("id"):
        return rp

    ap = ctx.get("active_project")
    if ap and ap.get("id"):
        return ap

    return None


async def ensure_99root_in_db() -> dict:
    """99-root projesini DB'de bulur; yoksa oluşturur. Proje dict'ini döndürür.

    Önce ID ile, sonra path ile arar. İkisi de yoksa yeni kayıt açar.
    """
    from ...store.repositories.project_repo import (
        project_get,
        project_list,
        project_create,
    )

    # 1. ID ile ara
    project = await project_get(_ROOT_PROJECT_ID)
    if project:
        return project

    # 2. Path ile ara (başka bir ID altında kayıtlı olabilir)
    projects = await project_list()
    for p in projects:
        try:
            if Path(p.get("path", "")).resolve() == _ROOT_DIR:
                return p
        except Exception:  # noqa: BLE001
            pass

    # 3. Bulunamadı — oluştur
    return await project_create(
        name=_ROOT_PROJECT_NAME,
        description="99-root ana ajan projesi",
        path=str(_ROOT_DIR),
    )
