"""Backup REST endpoint'leri — /agent/export, /agent/import (SRP).

Endpoint'ler:
    POST /agent/export
        Body: ExportRequest JSON
        → 200 application/octet-stream  (sync mod, varsayılan)
        → 202 {"task_id": "...", "status": "running"}  (async_mode=true)

    POST /agent/import
        Body: multipart/form-data  (file: .99rb, mode: "merge"|"replace"|"skip")
        → 200 ImportResult JSON
        → 400 Checksum / format hatası

    GET /agent/export/status/{task_id}
        → 200 {"status": ..., "manifest": {...}, "download_url": "..."}
        → 404 Görev bulunamadı

    GET /agent/export/download/{task_id}
        → 200 application/octet-stream  (tamamlanmış görev dosyası)
        → 404 Görev bulunamadı
        → 409 Görev henüz tamamlanmadı

Auth: Tüm endpoint'ler X-Api-Key gerektirir (COMMON_DEPS).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from ...features.backup._export_task_registry import ExportTask, ExportTaskRegistry
from ...features.backup._protocol import ImportMode
from ...features.backup._scope import ExportScope
from ...features.export_service import get_export_service
from ...features.import_service import get_import_service
from ._deps import COMMON_DEPS

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=COMMON_DEPS)


# ---------------------------------------------------------------------------
# Request modelleri
# ---------------------------------------------------------------------------


class ExportRequest(BaseModel):
    """POST /agent/export istek gövdesi."""

    scope: str = "essential"
    """Önceden tanımlı kapsam: "essential" | "full" | "custom"."""

    # custom scope flag'leri — scope="custom" olduğunda kullanılır
    include_messages: bool = True
    include_plans: bool = True
    include_calendar: bool = True
    include_tasks: bool = True
    include_settings: bool = True
    include_bridge_calls: bool = False
    include_token_usage: bool = False
    include_conv_history: bool = True
    include_project_files: bool = True
    include_media: bool = False
    messages_limit: int = 10_000

    async_mode: bool = False
    """True → 202 + task_id döndürür; False (varsayılan) → dosyayı doğrudan akıtır."""


# ---------------------------------------------------------------------------
# POST /agent/export
# ---------------------------------------------------------------------------


@router.post("/export")
async def export_backup(
    body: ExportRequest,
    background_tasks: BackgroundTasks,
):
    """Veritabanı ve dosya sistemini .99rb formatında dışa aktarır.

    sync mod (varsayılan): dosya doğrudan yanıtta döner.
    async mod (async_mode=true): task_id ile 202 döner; durum GET /export/status ile sorgulanır.
    """
    scope = _scope_from_request(body)

    if body.async_mode:
        return await _export_async(scope)

    return await _export_sync(scope, background_tasks)


# ---------------------------------------------------------------------------
# POST /agent/import
# ---------------------------------------------------------------------------


@router.post("/import")
async def import_backup(
    file: UploadFile,
    mode: str = Form(default="merge"),
):
    """Yüklenen .99rb yedek dosyasından DB ve dosya sistemini geri yükler.

    Args:
        file: .99rb binary yedek dosyası (multipart).
        mode: "merge" | "replace" | "skip" — çakışma çözüm stratejisi.
    """
    import_mode = _parse_import_mode(mode)

    raw = await file.read()
    tmp_path = Path(f"/tmp/import_{uuid.uuid4().hex}.99rb")
    try:
        tmp_path.write_bytes(raw)
        service = get_import_service()
        result = await service.restore_backup(tmp_path, import_mode)
    except ValueError as exc:
        logger.warning("Import format hatası: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Import beklenmeyen hata: %s", exc)
        raise HTTPException(status_code=500, detail=f"İçe aktarım hatası: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return {
        "tables_processed": result.tables_processed,
        "rows_inserted": result.rows_inserted,
        "rows_skipped": result.rows_skipped,
        "errors": result.errors,
    }


# ---------------------------------------------------------------------------
# GET /agent/export/status/{task_id}
# ---------------------------------------------------------------------------


@router.get("/export/status/{task_id}")
async def export_status(task_id: str):
    """Async export görevinin durumunu sorgular.

    Returns:
        JSON: status, manifest (done ise), download_url (done ise), error (error ise).
    """
    task = ExportTaskRegistry.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Görev bulunamadı: {task_id}")

    response: dict = {"task_id": task.task_id, "status": task.status}

    if task.status == "done" and task.manifest is not None:
        response["manifest"] = task.manifest.to_dict()
        response["download_url"] = f"/agent/export/download/{task_id}"

    if task.status == "error":
        response["error"] = task.error

    return response


# ---------------------------------------------------------------------------
# GET /agent/export/download/{task_id}
# ---------------------------------------------------------------------------


@router.get("/export/download/{task_id}")
async def export_download(task_id: str, background_tasks: BackgroundTasks):
    """Tamamlanmış async export görevinin .99rb dosyasını indirir.

    Dosya, istemciye iletildikten sonra /tmp'den silinir.
    """
    task = ExportTaskRegistry.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Görev bulunamadı: {task_id}")

    if task.status == "running":
        raise HTTPException(
            status_code=409,
            detail="Export henüz tamamlanmadı. GET /agent/export/status ile durumu kontrol et.",
        )

    if task.status == "error":
        raise HTTPException(
            status_code=400,
            detail=f"Export başarısız: {task.error}",
        )

    if task.output_path is None or not task.output_path.exists():
        raise HTTPException(status_code=404, detail="Export dosyası bulunamadı.")

    background_tasks.add_task(task.output_path.unlink, True)
    return FileResponse(
        path=str(task.output_path),
        media_type="application/octet-stream",
        filename=task.output_path.name,
        headers={
            "Content-Disposition": f'attachment; filename="{task.output_path.name}"',
        },
    )


# ---------------------------------------------------------------------------
# Özel yardımcı fonksiyonlar
# ---------------------------------------------------------------------------


def _scope_from_request(body: ExportRequest) -> ExportScope:
    """ExportRequest'ten ExportScope oluşturur."""
    if body.scope == "essential":
        return ExportScope.essential()
    if body.scope == "full":
        return ExportScope.full()
    # "custom" veya bilinmeyen değer → bireysel flag'leri kullan
    return ExportScope(
        include_messages=body.include_messages,
        include_plans=body.include_plans,
        include_calendar=body.include_calendar,
        include_tasks=body.include_tasks,
        include_settings=body.include_settings,
        include_bridge_calls=body.include_bridge_calls,
        include_token_usage=body.include_token_usage,
        include_conv_history=body.include_conv_history,
        include_project_files=body.include_project_files,
        include_media=body.include_media,
        messages_limit=body.messages_limit,
    )


def _parse_import_mode(mode: str) -> ImportMode:
    """Mode string'ini ImportMode enum'una dönüştürür."""
    try:
        return ImportMode(mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz mod: '{mode}'. Geçerli değerler: merge, replace, skip",
        )


async def _export_sync(
    scope: ExportScope,
    background_tasks: BackgroundTasks,
) -> FileResponse:
    """Sync export: dosyayı yazar ve FileResponse olarak döndürür."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tmp_path = Path(f"/tmp/backup_{timestamp}_{uuid.uuid4().hex[:8]}.99rb")

    try:
        service = get_export_service()
        await service.create_backup(scope, tmp_path)
    except Exception as exc:
        tmp_path.unlink(missing_ok=True)
        logger.exception("Sync export hatası: %s", exc)
        raise HTTPException(status_code=500, detail=f"Export hatası: {exc}") from exc

    background_tasks.add_task(tmp_path.unlink, True)
    return FileResponse(
        path=str(tmp_path),
        media_type="application/octet-stream",
        filename=tmp_path.name,
        headers={
            "Content-Disposition": f'attachment; filename="{tmp_path.name}"',
        },
    )


async def _export_async(scope: ExportScope) -> JSONResponse:
    """Async export: arka planda başlatır, task_id ile 202 döndürür."""
    task = ExportTask.new()
    ExportTaskRegistry.register(task)
    asyncio.create_task(_run_export_task(task.task_id, scope))
    return JSONResponse(
        {"task_id": task.task_id, "status": "running"},
        status_code=202,
    )


async def _run_export_task(task_id: str, scope: ExportScope) -> None:
    """Arka planda export işlemini yürütür ve kayıt defterini günceller."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tmp_path = Path(f"/tmp/backup_{timestamp}_{task_id[:8]}.99rb")

    try:
        service = get_export_service()
        manifest = await service.create_backup(scope, tmp_path)
        ExportTaskRegistry.mark_done(task_id, manifest, tmp_path)
        logger.info("Async export tamamlandı: task_id=%s path=%s", task_id, tmp_path)
    except Exception as exc:
        logger.exception("Async export başarısız: task_id=%s hata=%s", task_id, exc)
        ExportTaskRegistry.mark_error(task_id, str(exc))
        tmp_path.unlink(missing_ok=True)
