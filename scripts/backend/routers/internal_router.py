"""Internal router — yalnızca localhost (127.0.0.1 / ::1) erişimine açık endpoint'ler.

Dış ağdan erişilemez; API key gerektirmez.
Kullanım: Claude Code Bridge veya Claude Code CLI'nın admin TOTP doğrulaması için.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional

from ..guards import get_perm_mgr, get_session_mgr
from ..config import settings
from ..adapters.messenger.messenger_factory import get_messenger
from ..i18n import t
from ._localhost_guard import is_localhost

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/internal", tags=["internal"])

# SEC-SCAN2-R10: per-IP rate limiter — /verify-admin-totp endpoint'i için.
# OCP: mevcut TOTP lockout mekanizmasına dokunulmadı; bu bağımsız bir katman.
_IP_RATE_WINDOW_SECONDS: int = 60   # kayan pencere süresi
_IP_RATE_MAX_ATTEMPTS: int = 10     # pencere içinde izin verilen max deneme

# {ip: [(timestamp, ...), ...]} — her IP için timestamp listesi (kayan pencere)
_ip_attempt_times: dict[str, list[float]] = defaultdict(list)


def _check_ip_rate_limit(ip: str) -> None:
    """Aynı IP'den belirli sürede çok fazla deneme geliyorsa HTTP 429 fırlatır.

    Kayan pencere (sliding window) algoritması: eski zaman damgaları temizlenir,
    kalan sayı limite ulaşmışsa 429 döner.

    Args:
        ip: İstek yapan istemci IP adresi.

    Raises:
        HTTPException: 429 Too Many Requests — rate limit aşıldı.
    """
    now = time.monotonic()
    window_start = now - _IP_RATE_WINDOW_SECONDS

    # Eski girişleri temizle (kayan pencere)
    _ip_attempt_times[ip] = [ts for ts in _ip_attempt_times[ip] if ts > window_start]

    if len(_ip_attempt_times[ip]) >= _IP_RATE_MAX_ATTEMPTS:
        logger.warning(
            "internal verify-admin-totp: IP rate limit aşıldı ip=%s attempts=%d",
            ip, len(_ip_attempt_times[ip]),
        )
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit aşıldı. {_IP_RATE_WINDOW_SECONDS} saniye sonra tekrar deneyin.",
        )

    _ip_attempt_times[ip].append(now)


def _require_localhost(request: Request) -> None:
    if not is_localhost(request):
        host = request.client.host if request.client else "?"
        logger.warning("internal_router: localhost dışı erişim engellendi host=%s", host)
        raise HTTPException(status_code=403, detail="Localhost only")


class _VerifyRequest(BaseModel):
    code: str


class _PermissionPromptRequest(BaseModel):
    session_id: str
    request_id: str   # = tool_use_id (Bridge'den gelen ham ID)
    tool_name:  str
    tool_detail: str  # Bridge'de summarizeToolInput() ile hazırlanmış özet


@router.post(
    "/send_permission_prompt",
    summary="Araç onay isteğini kullanıcıya ilet",
    response_model=dict,
    responses={
        200: {"description": "Buton mesajı gönderildi", "content": {"application/json": {"example": {"ok": True}}}},
        403: {"description": "Localhost dışı erişim engellendi"},
    },
)
async def send_permission_prompt(request: Request, body: _PermissionPromptRequest):
    """Bridge'den gelen araç onayı isteğini kullanıcıya buton olarak iletir.

    Claude Code CLI bir araç çalıştırmadan önce izin istediğinde, Bridge bu endpoint'i
    çağırır. Kullanıcıya "İzin ver / Reddet" butonları gönderilir.

    **Yalnızca localhost** erişimine açıktır; API key gerekmez.
    """
    _require_localhost(request)
    messenger = get_messenger()
    owner     = settings.owner_id
    lang      = get_session_mgr().get(owner).get("lang", "tr")

    await messenger.send_buttons(
        owner,
        t("permission.prompt_body", lang, tool_name=body.tool_name, detail=body.tool_detail),
        [
            {"id": f"perm_a:{body.request_id}", "title": t("permission.allow_btn", lang)},
            {"id": f"perm_d:{body.request_id}", "title": t("permission.deny_btn", lang)},
        ],
    )
    logger.info(
        "permission_prompt gönderildi: session=%s req=%s tool=%s",
        body.session_id, body.request_id, body.tool_name,
    )
    return {"ok": True}


class _SendMessageRequest(BaseModel):
    to: str
    text: str


class _SendMediaRequest(BaseModel):
    """Yerel medya dosyasını owner'a gönderme isteği.

    path  — tek dosya (screenshot, video vb.)
    paths — çoklu dosya listesi (çok monitörlü screenshot/video)
    to    — hedef; belirtilmezse settings.owner_id kullanılır
    caption — isteğe bağlı açıklama
    """
    path: Optional[str] = None
    paths: Optional[list[str]] = None
    caption: str = ""
    to: Optional[str] = None


@router.post(
    "/send_media",
    summary="Yerel medya dosyasını kullanıcıya gönder",
    response_model=dict,
    responses={
        200: {"description": "Gönderim sonuçları", "content": {"application/json": {"example": {"ok": True, "results": [{"path": "/tmp/screen.png", "ok": True}]}}}},
        400: {"description": "path veya paths alanı eksik"},
        403: {"description": "Localhost dışı erişim engellendi"},
    },
)
async def internal_send_media(request: Request, body: _SendMediaRequest):
    """Yerel medya dosyasını (görsel/video/belge) owner'a gönder.

    Yalnızca localhost erişimine açıktır; API key gerekmez.
    Bridge veya Claude Code CLI, screenshot/video sonrası bu endpoint'i çağırır.

    MIME tipine göre otomatik dispatch:
      image/* → send_image
      video/* → send_video
      diğer   → send_document
    """
    import mimetypes
    from pathlib import Path

    _require_localhost(request)

    # Gönderilecek yolları topla (path XOR paths)
    all_paths: list[str] = []
    if body.paths:
        all_paths = body.paths
    elif body.path:
        all_paths = [body.path]

    if not all_paths:
        raise HTTPException(status_code=400, detail="path veya paths alanı gerekli")

    messenger = get_messenger()
    owner = body.to or settings.owner_id

    from ..adapters.messenger import MediaMessenger

    results: list[dict] = []
    for file_path in all_paths:
        p = Path(file_path)
        if not p.exists():
            logger.warning("send_media: dosya bulunamadı: %s", file_path)
            results.append({"path": file_path, "ok": False, "error": "dosya bulunamadı"})
            continue

        mime_type, _ = mimetypes.guess_type(file_path)
        mt = mime_type or ""

        if not isinstance(messenger, MediaMessenger):
            # Medya desteklemeyen messenger → yol bilgisini metin olarak ilet
            await messenger.send_text(owner, f"📁 {p.name}: {file_path}")
            results.append({"path": file_path, "ok": True, "fallback": "text"})
            logger.info(
                "send_media: medya desteği yok, metin fallback. path=%s messenger=%s",
                file_path, type(messenger).__name__,
            )
            continue

        try:
            if mt.startswith("image/"):
                await messenger.send_image(owner, file_path, caption=body.caption)
            elif mt.startswith("video/"):
                await messenger.send_video(owner, file_path, caption=body.caption)
            else:
                await messenger.send_document(
                    owner, file_path, filename=p.name, caption=body.caption
                )
            results.append({"path": file_path, "ok": True})
            logger.info(
                "send_media: gönderildi path=%s mime=%s to=%s",
                file_path, mt, owner[:6] + "…",
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("send_media: gönderim hatası path=%s: %s", file_path, exc)
            results.append({"path": file_path, "ok": False, "error": str(exc)})

    all_ok = all(r["ok"] for r in results)
    return {"ok": all_ok, "results": results}


@router.post(
    "/send_message",
    summary="Kullanıcıya mesaj gönder (proje servisleri için)",
    response_model=dict,
    responses={
        200: {"description": "Mesaj gönderildi", "content": {"application/json": {"example": {"ok": True}}}},
        403: {"description": "Localhost dışı erişim engellendi"},
    },
)
async def internal_send_message(request: Request, body: _SendMessageRequest):
    """Localhost'taki proje servislerinin kullanıcıya mesaj göndermesi için.

    Yalnızca localhost erişimine açıktır; API key gerekmez.
    Proje FastAPI'leri (bengisu vb.) bu endpoint'i çağırarak WhatsApp/Telegram'a
    mesaj gönderir — 99-root API key'i bilmeden mesaj iletimi sağlar.
    """
    _require_localhost(request)
    messenger = get_messenger()
    await messenger.send_text(body.to, body.text)
    logger.info("internal send_message: to=%s len=%d", body.to[:6] + "…", len(body.text))
    return {"ok": True}


@router.post(
    "/verify-admin-totp",
    summary="Owner TOTP doğrula (CLI guardrail override)",
    response_model=dict,
    responses={
        200: {
            "description": "Doğrulama sonucu",
            "content": {"application/json": {"example": {"valid": True}}},
        },
        403: {"description": "Localhost dışı erişim engellendi"},
    },
)
async def verify_totp_internal(request: Request, body: _VerifyRequest):
    """Owner TOTP doğrulaması — Claude Code CLI guardrail override için.

    Endpoint adı geriye dönük uyumluluk için korundu (bridge bu URL'yi kullanır).
    Dönüş: {"valid": true/false}
    SEC-H1: Brute-force koruması — 3 başarısız deneme → 15 dk kilit.
    Kilit "internal_cli" sender key'i ile totp_lockouts tablosuna yazılır;
    WhatsApp TOTP lockout'undan bağımsızdır.
    """
    import time as _time
    from ..store.sqlite_store import totp_get_lockout, totp_record_failure, totp_reset_lockout

    _require_localhost(request)

    # SEC-SCAN2-R10: per-IP rate limit — mevcut TOTP lockout'undan bağımsız ek katman
    client_ip = request.client.host if request.client else "unknown"
    _check_ip_rate_limit(client_ip)

    _SENDER = "internal_cli"
    _, lockout_until = await totp_get_lockout(_SENDER, "owner")
    if lockout_until and _time.time() < lockout_until:
        remaining = int(lockout_until - _time.time())
        logger.warning("internal verify-admin-totp: kilit aktif, %d sn kaldı", remaining)
        return {"valid": False}

    valid = get_perm_mgr().verify_totp(body.code)

    if valid:
        await totp_reset_lockout(_SENDER, "owner")
        logger.info("internal verify-admin-totp: başarılı doğrulama")
    else:
        fail_count, locked_until = await totp_record_failure(_SENDER, "owner")
        if locked_until:
            logger.warning(
                "internal verify-admin-totp: brute-force kilidi uygulandı fail_count=%d",
                fail_count,
            )
        else:
            logger.warning(
                "internal verify-admin-totp: başarısız deneme fail_count=%d", fail_count
            )

    return {"valid": valid}


# Zamanlama endpoint'leri _schedule_router.py'e taşındı (SOLID-SRP-1).


# ── Scan trigger ──────────────────────────────────────────────────


class ScanTriggerRequest(BaseModel):
    scan_type: str
    project_id: str
    dry_run: bool = False


class ScannerTriggerRequest(BaseModel):
    scan_type: str
    project_id: str
    auto_review: bool = True
    dry_run: bool = False
    parallel: int = Field(default=3, ge=1, le=10)
    include_third_party: bool = False


class ReviewerTriggerRequest(BaseModel):
    run_id: str
    dry_run: bool = False


class BacklogExecuteRequest(BaseModel):
    project_id: str
    prefix: str = ""
    max_items: int = Field(default=0, ge=0, le=100)  # 0 = tüm pending item'lar
    parallel: int = Field(default=2, ge=1, le=10)
    dry_run: bool = False


@router.post(
    "/scan/trigger",
    summary="Scan pipeline'ı arka planda başlat",
    response_model=dict,
    responses={
        200: {
            "description": "Tarama kuyruğa alındı",
            "content": {"application/json": {"example": {"run_id": "queued", "status": "queued", "scan_type": "security", "project_id": "petekv5"}}},
        },
        400: {"description": "Geçersiz scan_type"},
        403: {"description": "Localhost dışı erişim engellendi"},
    },
)
async def trigger_scan(
    request: Request,
    body: ScanTriggerRequest,
    background_tasks: BackgroundTasks,
):
    """Belirtilen proje için arka planda scan pipeline başlatır.

    Yalnızca localhost erişimine açıktır; API key gerekmez.
    Tarama BackgroundTasks ile asenkron çalışır — yanıt hemen döner.

    Geçerli scan_type değerleri: data/scan_configs/ dizinindeki JSON dosyaları.
    """
    from ..features.scan_pipeline.config_loader import ScanConfigLoader
    from ..features.scan_pipeline.runner import ScanRunner

    _require_localhost(request)

    # scan_type doğrulama
    available = ScanConfigLoader().list_available()
    if body.scan_type not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Geçersiz scan_type: {body.scan_type!r}. Geçerli tipler: {available}",
        )

    runner = ScanRunner()
    background_tasks.add_task(runner.run, body.scan_type, body.project_id, body.dry_run)

    logger.info(
        "scan/trigger: kuyruğa alındı scan_type=%s project_id=%s dry_run=%s",
        body.scan_type, body.project_id, body.dry_run,
    )
    return {
        "run_id": "queued",
        "status": "queued",
        "scan_type": body.scan_type,
        "project_id": body.project_id,
    }


# ── Scanner agent trigger ──────────────────────────────────────────


@router.post(
    "/scanner/trigger",
    summary="ScannerAgent'ı arka planda başlat (auto_review destekli)",
    response_model=dict,
    responses={
        200: {
            "description": "Tarama kuyruğa alındı",
            "content": {"application/json": {"example": {"status": "queued", "scan_type": "security", "project_id": "petekv5", "auto_review": True}}},
        },
        400: {"description": "Geçersiz scan_type"},
        403: {"description": "Localhost dışı erişim engellendi"},
    },
)
async def trigger_scanner(
    request: Request,
    body: ScannerTriggerRequest,
    background_tasks: BackgroundTasks,
):
    """ScannerAgent'ı arka planda başlatır; auto_review=True ise ReviewerAgent da zincirlenir.

    Yalnızca localhost erişimine açıktır; API key gerekmez.
    Tarama BackgroundTasks ile asenkron çalışır — yanıt hemen döner.
    """
    from ..features.scan_pipeline.config_loader import ScanConfigLoader

    _require_localhost(request)

    available = ScanConfigLoader().list_available()
    if body.scan_type not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Bilinmeyen scan tipi: {body.scan_type}. Mevcut: {available}",
        )

    from ..features.scan_pipeline.scanner_agent import ScannerAgent  # lazy import

    background_tasks.add_task(
        ScannerAgent().run,
        body.scan_type, body.project_id, body.auto_review, body.dry_run, body.parallel,
        body.include_third_party,
    )
    logger.info(
        "scanner/trigger: kuyruğa alındı scan_type=%s project_id=%s auto_review=%s dry_run=%s",
        body.scan_type, body.project_id, body.auto_review, body.dry_run,
    )
    return {
        "status": "queued",
        "scan_type": body.scan_type,
        "project_id": body.project_id,
        "auto_review": body.auto_review,
    }


# ── All scans trigger ──────────────────────────────────────────────


class AllScansTriggerRequest(BaseModel):
    project_id: str
    parallel: int = Field(default=3, ge=1, le=10)
    dry_run: bool = False
    include_third_party: bool = False


@router.post(
    "/scanner/trigger-all",
    summary="Tüm scan tiplerini sırayla başlat",
    response_model=dict,
)
async def trigger_all_scans(
    request: Request,
    body: AllScansTriggerRequest,
    background_tasks: BackgroundTasks,
):
    """Tüm konfigüre edilmiş scan tiplerini sırayla çalıştırır.

    Her scan tamamlandıktan sonra reviewer otomatik devreye girer.
    Tümü bitince özet bildirim owner'a gönderilir.
    Yalnızca localhost erişimine açıktır.
    """
    _require_localhost(request)

    from ..features.scan_pipeline.all_scans_runner import AllScansRunner

    background_tasks.add_task(
        AllScansRunner().run, body.project_id, body.parallel, body.dry_run, body.include_third_party
    )
    logger.info(
        "scanner/trigger-all: kuyruğa alındı project_id=%s parallel=%d dry_run=%s",
        body.project_id, body.parallel, body.dry_run,
    )
    return {"status": "queued", "project_id": body.project_id, "parallel": body.parallel}


# ── Reviewer agent trigger ─────────────────────────────────────────


@router.post(
    "/reviewer/trigger",
    summary="ReviewerAgent'ı arka planda başlat",
    response_model=dict,
    responses={
        200: {
            "description": "Review kuyruğa alındı",
            "content": {"application/json": {"example": {"status": "queued", "run_id": "abc123"}}},
        },
        403: {"description": "Localhost dışı erişim engellendi"},
    },
)
async def trigger_reviewer(
    request: Request,
    body: ReviewerTriggerRequest,
    background_tasks: BackgroundTasks,
):
    """ReviewerAgent'ı arka planda başlatır; verilen run_id'deki scan bulgularını gözden geçirir.

    Yalnızca localhost erişimine açıktır; API key gerekmez.
    Review BackgroundTasks ile asenkron çalışır — yanıt hemen döner.
    """
    _require_localhost(request)

    from ..features.scan_pipeline.reviewer_agent import ReviewerAgent  # lazy import

    background_tasks.add_task(ReviewerAgent().run, body.run_id, body.dry_run)
    logger.info(
        "reviewer/trigger: kuyruğa alındı run_id=%s dry_run=%s",
        body.run_id, body.dry_run,
    )
    return {"status": "queued", "run_id": body.run_id}


# ── Backlog executor trigger ───────────────────────────────────────


@router.post(
    "/backlog/execute",
    summary="BacklogExecutorAgent'ı arka planda başlat",
    response_model=dict,
    responses={
        200: {
            "description": "Executor kuyruğa alındı",
            "content": {"application/json": {"example": {"status": "queued", "project_id": "petekv5", "prefix": "", "max_items": 3}}},
        },
        403: {"description": "Localhost dışı erişim engellendi"},
    },
)
async def execute_backlog(
    request: Request,
    body: BacklogExecuteRequest,
    background_tasks: BackgroundTasks,
):
    """BacklogExecutorAgent'ı arka planda başlatır; BACKLOG.md öğelerini sırayla işler.

    Yalnızca localhost erişimine açıktır; API key gerekmez.
    Executor BackgroundTasks ile asenkron çalışır — yanıt hemen döner.
    """
    _require_localhost(request)

    from ..features.backlog_executor.runner import BacklogExecutorAgent  # lazy import

    background_tasks.add_task(
        BacklogExecutorAgent().run,
        body.project_id, body.prefix, body.max_items, body.parallel, body.dry_run,
    )
    logger.info(
        "backlog/execute: kuyruğa alındı project_id=%s prefix=%r max_items=%d parallel=%d dry_run=%s",
        body.project_id, body.prefix, body.max_items, body.parallel, body.dry_run,
    )
    return {
        "status": "queued",
        "project_id": body.project_id,
        "prefix": body.prefix,
        "max_items": body.max_items,
    }


# ── Scanner cancel / status ────────────────────────────────────────


@router.post(
    "/scanner/cancel",
    summary="Aktif scan'i iptal et",
    response_model=dict,
    responses={
        200: {
            "description": "İptal flag'i set edildi",
            "content": {"application/json": {"example": {"status": "cancel_requested"}}},
        },
        403: {"description": "Localhost dışı erişim engellendi"},
    },
)
async def cancel_scanner(request: Request):
    """Devam eden scan pipeline'ının iptalini talep eder.

    Flag set edilir; bir sonraki chunk döngüsü kontrolünde tarama durur.
    Yalnızca localhost erişimine açıktır; API key gerekmez.
    """
    _require_localhost(request)
    from ..guards.runtime_state import request_scan_cancel
    request_scan_cancel()
    logger.info("scanner/cancel: iptal flag'i set edildi")
    return {"status": "cancel_requested"}


@router.get(
    "/scanner/status",
    summary="Aktif scan durumunu göster",
    response_model=dict,
    responses={
        200: {
            "description": "Scan durum bilgisi",
            "content": {
                "application/json": {
                    "example": {
                        "cancel_requested": False,
                        "running_agent_run": None,
                        "last_run_dir": None,
                        "findings_count": 0,
                    }
                }
            },
        },
        403: {"description": "Localhost dışı erişim engellendi"},
    },
)
async def scanner_status(request: Request):
    """Aktif scan hakkında durum bilgisi döndürür.

    cancel_requested: İptal flag'inin set edilip edilmediği.
    running_agent_run: DB'deki en son 'running' durumundaki scanner agent_run kaydı.
    last_run_dir: data/scan_runs/ altındaki en yeni klasörün adı (run_id).
    findings_count: En yeni run dizinindeki findings/*.jsonl dosya sayısı.

    Yalnızca localhost erişimine açıktır; API key gerekmez.
    """
    from pathlib import Path
    from ..guards.runtime_state import is_scan_cancel_requested

    _require_localhost(request)

    cancel_requested = is_scan_cancel_requested()

    # En son çalışan agent_run kaydını oku
    running_agent_run: dict | None = None
    try:
        from ..store.sqlite_store import SqliteStore
        store = SqliteStore()
        rows = await store.fetchall(
            "SELECT id, session_id, project_id, started_at, status FROM agent_runs "
            "WHERE agent_type = 'scanner' AND status = 'running' "
            "ORDER BY started_at DESC LIMIT 1"
        )
        if rows:
            row = rows[0]
            running_agent_run = {
                "id":         row["id"],
                "session_id": row["session_id"],
                "project_id": row["project_id"],
                "started_at": row["started_at"],
                "status":     row["status"],
            }
    except Exception as _err:  # noqa: BLE001
        logger.debug("scanner_status: agent_runs sorgusu başarısız: %s", _err)

    # scan_runs dizinindeki en yeni run_id'yi bul
    runs_dir = Path(__file__).parent.parent.parent.parent / "data" / "scan_runs"
    last_run_dir: str | None = None
    findings_count: int = 0
    try:
        if runs_dir.exists():
            subdirs = sorted(
                (d for d in runs_dir.iterdir() if d.is_dir()),
                key=lambda d: d.stat().st_mtime,
            )
            if subdirs:
                newest = subdirs[-1]
                last_run_dir = newest.name
                findings_dir = newest / "findings"
                if findings_dir.exists():
                    findings_count = sum(1 for f in findings_dir.iterdir() if f.suffix == ".jsonl")
    except Exception as _err:  # noqa: BLE001
        logger.debug("scanner_status: scan_runs dizini okunamadı: %s", _err)

    return {
        "cancel_requested":  cancel_requested,
        "running_agent_run": running_agent_run,
        "last_run_dir":      last_run_dir,
        "findings_count":    findings_count,
    }
