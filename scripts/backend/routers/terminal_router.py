"""
/internal/terminal — Shell komutu çalıştırma endpoint'i (yalnızca localhost, FEAT-12e).

Bridge'den Claude Code CLI çağrısıyla kullanılır; API key gerekmez.
Yalnızca 127.0.0.1 veya ::1'den erişilebilir — diğer IP'ler 403 döner.

Kullanım:
    POST /internal/terminal
    {"cmd": "ls -la", "timeout": 30, "cwd": null}

Yanıt (başarılı):
    {"ok": true, "stdout": "...", "returncode": 0, "timed_out": false, "dangerous": false}

Yanıt (hata):
    {"ok": false, "stdout": "❌ ...", "returncode": -1, "timed_out": false, "dangerous": false}

Güvenlik notu:
    Tehlikeli komutlar (is_dangerous → true) BLOKLANMAZ; iç çağrı güvenilir kabul edilir.
    "dangerous" alanı true döner ve WARNING seviyesinde loglanır.
    WhatsApp /terminal komutu ise ayrıca admin TOTP gerektirmektedir.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from ..config import settings
from ._localhost_guard import is_localhost

_TERMINAL_DISABLED = HTTPException(
    status_code=503,
    detail="Terminal devre dışı (RESTRICT_SHELL=true).",
)

logger = logging.getLogger(__name__)
router = APIRouter()


class TerminalRequest(BaseModel):
    cmd: str
    timeout: int = 30
    cwd: Optional[str] = None

    @field_validator("cmd")
    @classmethod
    def validate_cmd(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("cmd boş olamaz.")
        return v

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if not (1 <= v <= 300):
            raise ValueError("timeout 1–300 saniye arasında olmalı.")
        return v


@router.post("/internal/terminal")
async def terminal_run(body: TerminalRequest, request: Request):
    """
    Shell komutu çalıştır ve sonucu döndür.
    Yalnızca localhost'tan erişilebilir.
    """
    if settings.restrict_shell:
        raise _TERMINAL_DISABLED

    if not is_localhost(request):
        logger.warning(
            "terminal_router: yetkisiz IP reddedildi (host=%s)",
            request.client.host if request.client else "?",
        )
        return JSONResponse(
            status_code=403,
            content={"detail": "Yalnızca localhost erişimi"},
        )

    from ..features.terminal import execute_command, is_dangerous

    # BUG-DESK-LOCK-2: xdotool girdi komutları ekran kilitliyken engellenir
    # xdotool type/key/click/move aktif pencereye yazar — kilit ekranı varsa şifre alanına yazar.
    _XDO_INPUT_RE = __import__("re").compile(
        r"\bxdotool\s+(type|key|click|mousemove|mousedown|mouseup)\b", __import__("re").IGNORECASE
    )
    if _XDO_INPUT_RE.search(body.cmd):
        from ..features.desktop import is_screen_locked
        if await is_screen_locked():
            logger.warning(
                "terminal_router: ekran kilitli — xdotool girdi komutu engellendi (BUG-DESK-LOCK-2) cmd=%r",
                body.cmd[:120],
            )
            return JSONResponse(
                status_code=403,
                content={
                    "ok": False,
                    "stdout": "❌ Ekran kilitli — xdotool girdi komutu engellendi. Önce unlock_screen çağır.",
                    "returncode": -1,
                    "timed_out": False,
                    "dangerous": True,
                },
            )

    dangerous = is_dangerous(body.cmd)
    if dangerous:
        logger.warning(
            "terminal_router: tehlikeli komut çalıştırılıyor (internal) — cmd=%r",
            body.cmd[:120],
        )
    else:
        logger.info("terminal_router: cmd=%r timeout=%d", body.cmd[:120], body.timeout)

    result = await execute_command(
        body.cmd,
        timeout=body.timeout,
        cwd=body.cwd,
    )

    ok = not result.timed_out and result.returncode == 0
    return {
        "ok": ok,
        "stdout": result.stdout,
        "returncode": result.returncode,
        "timed_out": result.timed_out,
        "dangerous": dangerous,
    }
