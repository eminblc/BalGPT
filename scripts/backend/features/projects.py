"""Proje yönetimi — geriye dönük uyum shim'i.

Implementasyonlar SRP'ye uygun alt modüllere taşındı:
  project_crud.py     — CRUD, beta modu, context güncellemesi
  project_service.py  — tmux servis başlatma/durdurma
  project_scaffold.py — klasör ve md dosyası oluşturma
"""
from __future__ import annotations

from .project_crud import (  # noqa: F401
    update_active_context_project,
    create_project,
    list_projects,
    get_project,
    start_beta_mode,
    format_project_list,
)
from .project_service import (  # noqa: F401
    _UNSAFE_CMD_RE,
    _WINDOW_NAME_RE,
    _validate_service_cmd,
    _validate_service,
    _tmux_start_service,
    start_project_services,
    stop_project_services,
)
from .project_scaffold import (  # noqa: F401
    _build_md_content,
    _scaffold_project,
)
