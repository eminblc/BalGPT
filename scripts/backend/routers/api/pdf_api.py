"""PDF import endpoint'i — /pdf-import (SRP)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ._deps import COMMON_DEPS
from ...config import settings

router = APIRouter(dependencies=COMMON_DEPS)

_PDF_DISABLED = HTTPException(
    status_code=503,
    detail="PDF import is disabled (RESTRICT_PDF_IMPORT=true).",
)


class PdfImportRequest(BaseModel):
    media_id: str
    sender: str


@router.post("/pdf-import")
async def pdf_import(body: PdfImportRequest):
    if not settings.pdf_import_enabled:
        raise _PDF_DISABLED
    from ...features.pdf_importer import import_from_whatsapp_media
    return await import_from_whatsapp_media(body.media_id, body.sender)
