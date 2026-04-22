"""Personal Agent API router — /agent/* endpoint'leri (SRP).

Endpoint'ler SRP'ye uygun alt modüllere taşındı:
  api/plans_api.py     — İş planları
  api/calendar_api.py  — Takvim
  api/projects_api.py  — Projeler + Beta modu
  api/scheduler_api.py — Zamanlama
  api/pdf_api.py       — PDF import
"""
from __future__ import annotations

from fastapi import APIRouter

from .api import plans_api, calendar_api, projects_api, scheduler_api, pdf_api

router = APIRouter()
router.include_router(plans_api.router)
router.include_router(calendar_api.router)
router.include_router(projects_api.router)
router.include_router(scheduler_api.router)
router.include_router(pdf_api.router)
