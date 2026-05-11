"""Proje endpoint'leri — /project, /projects (SRP)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...guards import get_perm_mgr
from ...config import settings
from ._deps import COMMON_DEPS

router = APIRouter(dependencies=COMMON_DEPS, tags=["projects"])


class ProjectRequest(BaseModel):
    name: str = Field(..., description="Proje slug adı (benzersiz)", json_schema_extra={"example": "my-project"})
    description: str = Field("", description="Opsiyonel açıklama", json_schema_extra={"example": "REST API geliştirme projesi"})
    level: str = Field(
        "full",
        description="Scaffold seviyesi: 'full' (CLAUDE.md + scripts + README), 'minimal' (sadece CLAUDE.md), 'none' (boş dizin)",
        json_schema_extra={"example": "full"},
    )


class BetaRequest(BaseModel):
    sender: str = Field(..., description="WhatsApp numarası veya Telegram chat_id — yetki kontrolü için", json_schema_extra={"example": "905301083815"})


@router.post(
    "/project",
    summary="Yeni proje oluştur",
    response_model=dict,
    responses={
        200: {"description": "Oluşturulan proje kaydı"},
    },
)
async def create_project(body: ProjectRequest):
    """Yeni bir proje oluşturur ve isteğe bağlı dosya iskeletini hazırlar.

    `level` ile scaffold derinliğini seçin:
    - `full` — CLAUDE.md, scripts/, README.md, ecosystem.config.js
    - `minimal` — yalnızca CLAUDE.md
    - `none` — boş proje dizini

    Oluşturulan proje `data/projects/{name}/` altına yerleştirilir.
    """
    from ...features.projects import create_project
    return await create_project(body.name, body.description, level=body.level)


@router.get(
    "/projects",
    summary="Projeleri listele",
    response_model=list,
    responses={
        200: {"description": "Tüm proje kayıtları"},
    },
)
async def list_projects():
    """Veritabanındaki tüm projeleri döndürür.

    Her proje kaydı: `id`, `name`, `description`, `status`, `metadata` alanlarını içerir.
    """
    from ...features.projects import list_projects as _list_projects
    return await _list_projects()


@router.post(
    "/project/{project_id}/beta",
    summary="Proje beta modunu başlat",
    response_model=dict,
    responses={
        200: {
            "description": "Beta modu başlatıldı",
            "content": {"application/json": {"example": {"status": "beta_started", "project_id": "my-project"}}},
        },
        403: {"description": "Yetkisiz sender — yalnızca owner kullanabilir"},
    },
)
async def start_beta(project_id: str, body: BetaRequest):
    """Belirtilen proje için beta modunu etkinleştirir.

    Beta modunda, `sender` kullanıcısından gelen mesajlar 99-root Bridge yerine
    projenin kendi FastAPI servisine yönlendirilir (`http://localhost:{port}/whatsapp/internal/message`).

    Yalnızca `owner` yetkisine sahip gönderenler beta modunu başlatabilir.
    Beta modunu sonlandırmak için `/beta` komutunu kullanın.
    """
    if settings.owner_id and not get_perm_mgr().is_owner(body.sender):
        raise HTTPException(status_code=403, detail="Yetkisiz sender")
    from ...features.projects import start_beta_mode
    await start_beta_mode(project_id, body.sender)
    return {"status": "beta_started", "project_id": project_id}
