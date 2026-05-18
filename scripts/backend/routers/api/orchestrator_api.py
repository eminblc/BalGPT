"""Multi-Project Orchestrator API — /orchestrator/* endpoints (SRP).

Tüm iş mantığı orchestrator feature modüllerine delege edilir;
bu modül yalnızca HTTP istek/yanıt dönüşümünden sorumludur.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ._deps import COMMON_DEPS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/orchestrator", dependencies=COMMON_DEPS, tags=["orchestrator"])


# ── Request modelleri ─────────────────────────────────────────────


class RegisterProjectRequest(BaseModel):
    project_id: str = Field(
        ...,
        description="Kayıt edilecek proje ID'si (projects tablosunda mevcut olmalı)",
        json_schema_extra={"example": "my-project"},
    )
    bridge_url: str = Field(
        ...,
        description="Projenin Claude Code Bridge endpoint URL'si",
        json_schema_extra={"example": "http://localhost:8014"},
    )
    fastapi_url: str = Field(
        "",
        description="Projenin FastAPI servis endpoint URL'si (opsiyonel)",
        json_schema_extra={"example": "http://localhost:8015"},
    )
    concurrent_agents: int = Field(
        3,
        ge=1,
        le=20,
        description="İzin verilen maksimum eşzamanlı agent sayısı",
        json_schema_extra={"example": 3},
    )


# ── Yardımcı — store + orchestrator nesneleri ─────────────────────


def _get_store():
    """sqlite_store modülünü lazy import et."""
    from ...store import sqlite_store  # noqa: PLC0415
    return sqlite_store


def _get_project_registry():
    """ProjectRegistry singleton'ını lazy import et."""
    from ...features.orchestrator.core import ProjectRegistry  # noqa: PLC0415
    store = _get_store()
    return ProjectRegistry(store)


def _get_registrar():
    """ExternalProjectRegistrar singleton'ını lazy import et."""
    from ...features.orchestrator.registry import ExternalProjectRegistrar  # noqa: PLC0415
    return ExternalProjectRegistrar(_get_project_registry())


def _get_lifecycle_manager():
    """AgentLifecycleManager singleton'ını lazy import et."""
    from ...features.orchestrator.core import AgentLifecycleManager  # noqa: PLC0415
    return AgentLifecycleManager()


# ── Endpoint'ler ──────────────────────────────────────────────────


@router.post(
    "/projects/register",
    summary="Harici projeyi orchestrator'a kaydet",
    response_model=dict,
    responses={
        200: {"description": "Proje başarıyla kaydedildi"},
        400: {"description": "Kayıt başarısız — hata detayı body'de"},
        404: {"description": "Proje DB'de bulunamadı"},
    },
)
async def register_project(body: RegisterProjectRequest):
    """Harici projeyi orchestrator'a kaydeder.

    Proje önceden `projects` tablosunda mevcut olmalıdır.
    Kayıt, projenin metadata alanına `orchestrator_enabled=true` ve
    bridge/fastapi URL bilgilerini ekler.
    """
    registrar = _get_registrar()
    result = await registrar.handle_registration(
        body.project_id,
        body.bridge_url,
        fastapi_url=body.fastapi_url,
        concurrent_agents=body.concurrent_agents,
    )
    if not result.get("ok"):
        error_msg: str = result.get("error", "Kayıt başarısız")
        if "bulunamadı" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    return {"ok": True, "project_id": result["project_id"], "message": "Proje orchestrator'a kaydedildi."}


@router.delete(
    "/projects/{project_id}/unregister",
    summary="Proje orchestrator kaydını kaldır",
    response_model=dict,
    responses={
        200: {"description": "Kayıt kaldırıldı"},
        400: {"description": "Kayıt silme başarısız"},
        404: {"description": "Proje DB'de bulunamadı"},
    },
)
async def unregister_project(project_id: str):
    """Projenin orchestrator kaydını kaldırır (orchestrator_enabled=False).

    Proje DB'den silinmez; yalnızca orchestrator metadata güncellenir.
    """
    registrar = _get_registrar()
    result = await registrar.handle_unregistration(project_id)
    if not result.get("ok"):
        error_msg: str = result.get("error", "Kayıt silme başarısız")
        if "bulunamadı" in error_msg.lower():
            raise HTTPException(status_code=404, detail=error_msg)
        raise HTTPException(status_code=400, detail=error_msg)
    return {"ok": True, "project_id": result["project_id"], "message": "Orchestrator kaydı kaldırıldı."}


@router.get(
    "/projects",
    summary="Orchestrator'a kayıtlı projeleri listele",
    response_model=list,
    responses={
        200: {"description": "orchestrator_enabled=True projelerin listesi"},
    },
)
async def list_orchestrator_projects():
    """orchestrator_enabled=True olan tüm projeleri döndürür.

    Her kayıt proje bilgilerini ve metadata (bridge_url, fastapi_url,
    concurrent_agents, registered_at) içerir.
    """
    registry = _get_project_registry()
    return await registry.list_registered()


@router.get(
    "/projects/{project_id}/status",
    summary="Proje orchestrator durumunu getir",
    response_model=dict,
    responses={
        200: {"description": "Proje durumu ve aktif run istatistikleri"},
        404: {"description": "Proje bulunamadı"},
    },
)
async def get_project_status(project_id: str):
    """Proje durumunu ve aktif agent run sayısını döndürür.

    Dönen alanlar: `project`, `active_runs`, `pending_runs`, `running_runs`.
    """
    store = _get_store()
    project = await store.project_get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Proje bulunamadı: {project_id!r}")

    lifecycle = _get_lifecycle_manager()
    active_runs = await lifecycle.list_active_runs()
    project_active = [r for r in active_runs if r.get("project_id") == project_id]

    return {
        "project": dict(project),
        "active_runs": len(project_active),
        "pending_runs": sum(1 for r in project_active if r.get("status") == "pending"),
        "running_runs": sum(1 for r in project_active if r.get("status") == "running"),
    }


@router.get(
    "/projects/{project_id}/runs",
    summary="Proje agent run'larını listele",
    response_model=list,
    responses={
        200: {"description": "Filtrelenmiş agent run listesi (en yeni önce)"},
        404: {"description": "Proje bulunamadı"},
    },
)
async def list_project_runs(
    project_id: str,
    status: Optional[str] = None,
    limit: int = 50,
):
    """Belirtilen projeye ait agent run'ları döndürür.

    `status` ile filtrele: `pending`, `running`, `completed`, `failed`, `cancelled`.
    `limit` maksimum kayıt sayısını belirler (varsayılan: 50).
    """
    store = _get_store()
    project = await store.project_get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Proje bulunamadı: {project_id!r}")

    lifecycle = _get_lifecycle_manager()
    return await lifecycle.list_runs(project_id=project_id, status=status, limit=limit)


@router.post(
    "/projects/{project_id}/runs/{run_id}/cancel",
    summary="Çalışan agent run'ı iptal et",
    response_model=dict,
    responses={
        200: {"description": "Run iptal edildi"},
        404: {"description": "Run veya proje bulunamadı"},
    },
)
async def cancel_agent_run(project_id: str, run_id: str):
    """Belirtilen agent run'ı iptal eder (status=cancelled).

    Run zaten tamamlanmış veya başarısız olmuşsa işlem etki göstermez;
    DB kaydı cancelled olarak güncellenir.
    """
    store = _get_store()
    project = await store.project_get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Proje bulunamadı: {project_id!r}")

    from ...store.repositories import agent_run_repo  # noqa: PLC0415
    run = await agent_run_repo.agent_run_get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run bulunamadı: {run_id!r}")

    lifecycle = _get_lifecycle_manager()
    await lifecycle.cancel_run(run_id)
    logger.info("orchestrator_api: run=%s project=%s iptal edildi.", run_id, project_id)
    return {"ok": True, "run_id": run_id, "status": "cancelled"}


@router.get(
    "/runs/active",
    summary="Tüm projelerdeki aktif run'ları listele",
    response_model=list,
    responses={
        200: {"description": "pending + running durumundaki tüm agent run'lar (en eski önce)"},
    },
)
async def list_all_active_runs():
    """Tüm projelerdeki pending ve running durumundaki agent run'ları döndürür.

    Sonuçlar en eskiden en yeniye doğru sıralanır.
    """
    lifecycle = _get_lifecycle_manager()
    return await lifecycle.list_active_runs()


@router.get(
    "/runs/{run_id}",
    summary="Tek agent run detayı",
    response_model=dict,
    responses={
        200: {"description": "Agent run detay kaydı"},
        404: {"description": "Run bulunamadı"},
    },
)
async def get_agent_run(run_id: str):
    """Belirtilen run_id'ye ait agent run detayını döndürür.

    Dönen alanlar: `id`, `agent_type`, `session_id`, `project_id`, `status`,
    `prompt`, `output`, `error_msg`, `exit_code`, `created_at`, `started_at`,
    `completed_at`, `duration_ms`.
    """
    from ...store.repositories import agent_run_repo  # noqa: PLC0415
    run = await agent_run_repo.agent_run_get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run bulunamadı: {run_id!r}")
    return run
