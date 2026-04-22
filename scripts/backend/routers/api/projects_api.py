"""Proje endpoint'leri — /project, /projects (SRP)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...guards import get_perm_mgr
from ...config import settings
from ._deps import COMMON_DEPS

router = APIRouter(dependencies=COMMON_DEPS)


class ProjectRequest(BaseModel):
    name: str
    description: str = ""
    level: str = "full"  # "full" | "minimal" | "none"


class BetaRequest(BaseModel):
    sender: str  # G4: query param'dan POST body'e taşındı (URL loglarına düşmez)


@router.post("/project")
async def create_project(body: ProjectRequest):
    from ...features.projects import create_project
    return await create_project(body.name, body.description, level=body.level)


@router.get("/projects")
async def list_projects():
    from ...features.projects import list_projects as _list_projects
    return await _list_projects()


@router.post("/project/{project_id}/beta")
async def start_beta(project_id: str, body: BetaRequest):
    if settings.owner_id and not get_perm_mgr().is_owner(body.sender):
        raise HTTPException(status_code=403, detail="Yetkisiz sender")
    from ...features.projects import start_beta_mode
    await start_beta_mode(project_id, body.sender)
    return {"status": "beta_started", "project_id": project_id}
