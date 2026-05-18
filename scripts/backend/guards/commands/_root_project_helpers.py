"""99-root projesi için paylaşılan yardımcı fonksiyonlar (SRP).

scan_cmd ve backlog_cmd tarafından kullanılır; başka hiçbir modüle bağımlılık yoktur.
"""
from __future__ import annotations

from pathlib import Path

# 99-root proje kök dizini — bu dosyanın konumundan türetilir
_ROOT_DIR = Path(__file__).parent.parent.parent.parent.parent.resolve()
_ROOT_PROJECT_ID = "99-root"
_ROOT_PROJECT_NAME = "99-root"


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
