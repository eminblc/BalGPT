"""
/internal/desktop — PC otomasyon endpoint'i (yalnızca localhost).

Bridge'den Claude Code CLI çağrısıyla kullanılır; API key gerekmez.
Yalnızca 127.0.0.1 veya ::1'den erişilebilir — diğer IP'ler 403 döner.

Kabul edilen aksiyonlar:
    open         → Dosya/klasörü varsayılan uygulamayla aç (xdg-open)
    run          → Kurulum dosyasını çalıştır (.deb, .exe, .msi, .sh, .AppImage, .rpm)
    screenshot   → Ekran görüntüsü al; ocr=true ise OCR metni de döner
    ocr          → Ekran görüntüsü + OCR (yalnızca metin döner)
    type         → Aktif pencereye metin yaz (xdotool type)
    key          → Tuş/kombinasyon gönder (xdotool key) — ör. "ctrl+c", "Return"
    click        → Koordinata tıkla (xdotool mousemove + click)
    move         → Fareyi koordinata taşı (xdotool mousemove)
    scroll       → Scroll yap (xdotool click button 4/5/6/7)
    vision_query → Ekran görüntüsü + Claude Vision API ile serbest soru
    get_windows      → Açık pencereleri listele (wmctrl / xdotool)
    focus_window     → Pencereyi öne getir ve odakla (window_id veya window_name ile)
    get_desktop_tree → AT-SPI accessibility tree (Vision API gerekmez)
    find_element     → AT-SPI tree'de role/name ile element ara
    activate_element → AT-SPI element bul ve aktive et (tıkla/tetikle)
    watch_popup      → X11 MapNotify izleyici başlat; WM_CLASS eşleşen pencereyi kapat
    stop_watch_popup → Çalışan izleyiciyi durdur (watcher_id ile)
    list_watch_popup → Aktif izleyicileri listele

İstek gövdesi:
    {
        "action": "open"|"run"|"screenshot"|"ocr"|"type"|"key"|"click"|"move"|"scroll",

        # open / run:
        "target": "/yol/dosya",
        "timeout": 120,

        # screenshot / vision_query:
        "ocr": false,
        "output_path": "/tmp/...",
        "region": [x, y, w, h],   # isteğe bağlı — yalnızca bu bölgeyi yakala

        # type:
        "text": "yazılacak metin",
        "delay_ms": 12,

        # key:
        "key": "ctrl+c",

        # click / move:
        "x": 500,
        "y": 300,
        "button": 1,          # 1=sol, 2=orta, 3=sağ (click için)

        # scroll:
        "direction": "down",  # up | down | left | right
        "amount": 3,          # 1-20

        # vision_query:
        "question": "Ekranda ne yazıyor?",
        "vision_model": "claude-haiku-4-5-20251001",

        # focus_window:
        "window_id": "0x05000003",   # hex pencere ID (wmctrl -l'den alınır)
        "window_name": "Firefox"     # başlık (kısmi eşleşme)
    }

Başarılı yanıt:
    {"ok": true, "message": "...", "text": "..."}   # text: OCR ve vision_query aksiyonlarında
    {"ok": true, "message": "...", "path": "..."}   # path yalnızca screenshot'ta

Hata yanıtı:
    {"ok": false, "message": "Hata açıklaması"}
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from ..config import settings
from ..constants import DESKTOP_BATCH_MAX_ACTIONS
from ._localhost_guard import is_localhost
from ._desktop_totp_gate import enforce_totp, request_desktop_totp
from . import _desktop_validation as _dv
from . import _desktop_vision as _vision
from . import _desktop_capture as _capture

logger = logging.getLogger(__name__)
router = APIRouter()

_ALLOWED_ACTIONS = _dv.ALLOWED_ACTIONS


# ── Request modeli ─────────────────────────────────────────────────

class DesktopRequest(BaseModel):
    action: str

    # open / run
    target: Optional[str] = None
    timeout: int = 120

    # screenshot / vision_query
    ocr: bool = False
    output_path: Optional[str] = None
    region: Optional[list[int]] = None  # [x, y, w, h] — yalnızca bu bölgeyi yakala

    # type
    text: Optional[str] = None
    delay_ms: int = 12

    # key
    key: Optional[str] = None

    # click / move
    x: Optional[int] = None
    y: Optional[int] = None
    button: int = 1          # 1=sol, 2=orta, 3=sağ

    # scroll
    direction: Optional[str] = None
    amount: int = 3

    # vision_query
    question: Optional[str] = None
    vision_model: str = "claude-haiku-4-5-20251001"
    use_cache: bool = True  # OPT-3: aynı pencerede 60s içinde aynı soru → cache'den döner
    session_id: Optional[str] = None  # vision rate limit scope (None → "default")

    # focus_window
    window_id: Optional[str] = None
    window_name: Optional[str] = None

    # sudo_exec
    sudo_cmd: Optional[list[str]] = None  # ör. ["apt", "install", "-y", "scrot"]

    # record_screen (FEAT-DESK-REC-1)
    duration: int = 10  # kayıt süresi saniye (1–300)

    # AT-SPI (FEAT-17) — get_desktop_tree / find_element / activate_element
    atspi_role: Optional[str] = None     # ör. "push button", "entry", "label"
    atspi_name: Optional[str] = None     # element adı (kısmi eşleşme)
    atspi_max_depth: int = 4             # get_desktop_tree derinliği (1–6)

    # DESK-OPT-8 — watch_popup / stop_watch_popup / list_watch_popup
    wm_class: Optional[list[str]] = None  # WM_CLASS kalıpları (büyük-küçük harf duyarsız)
    watcher_id: Optional[str] = None      # izleyici ID (başlatma/durdurma için)

    # Admin TOTP gate — ilk çağrıda zorunlu; TTL boyunca sonraki çağrılarda boş geçilebilir
    code: Optional[str] = None

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        return _dv.validate_action(v)

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        return _dv.validate_timeout(v)

    @field_validator("region")
    @classmethod
    def validate_region(cls, v: Optional[list[int]]) -> Optional[list[int]]:
        return _dv.validate_region(v)

    @field_validator("delay_ms")
    @classmethod
    def validate_delay_ms(cls, v: int) -> int:
        return _dv.validate_delay_ms(v)

    @field_validator("duration")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        return _dv.validate_duration(v)

    @field_validator("output_path")
    @classmethod
    def validate_output_path(cls, v: Optional[str]) -> Optional[str]:
        return _dv.validate_output_path(v)

    @field_validator("vision_model")
    @classmethod
    def validate_vision_model(cls, v: str) -> str:
        return _dv.validate_vision_model(v)


# ── Aksiyon handler'ları ───────────────────────────────────────────

async def _handle_open(body: DesktopRequest) -> dict:
    if not body.target:
        return {"ok": False, "message": "open aksiyonu için 'target' (dosya/klasör yolu) gerekli."}
    from ..features.desktop import open_path
    result = await open_path(body.target)
    ok = result.startswith("✅")
    logger.info("desktop/open: %s → %s", body.target, "ok" if ok else "hata")
    return {"ok": ok, "message": result}


async def _handle_run(body: DesktopRequest) -> dict:
    if not body.target:
        return {"ok": False, "message": "run aksiyonu için 'target' (kurulum dosyası yolu) gerekli."}
    from ..features.desktop import run_installer
    result = await run_installer(body.target, timeout=body.timeout)
    ok = result.startswith("✅")
    logger.info("desktop/run: %s → %s", body.target, "ok" if ok else "hata")
    return {"ok": ok, "message": result}



async def _handle_type(body: DesktopRequest) -> dict:
    if not body.text:
        return {"ok": False, "message": "type aksiyonu için 'text' gerekli."}
    from ..features.desktop import xdotool_type
    result = await xdotool_type(body.text, delay_ms=body.delay_ms, window_id=body.window_id)
    ok = result.startswith("✅")
    logger.info("desktop/type: %d karakter → %s", len(body.text), "ok" if ok else "hata")
    return {"ok": ok, "message": result}


async def _handle_key(body: DesktopRequest) -> dict:
    if not body.key:
        return {"ok": False, "message": "key aksiyonu için 'key' alanı gerekli (ör. 'ctrl+c')."}
    from ..features.desktop import xdotool_key
    result = await xdotool_key(body.key)
    ok = result.startswith("✅")
    logger.info("desktop/key: %s → %s", body.key, "ok" if ok else "hata")
    return {"ok": ok, "message": result}


async def _handle_click(body: DesktopRequest) -> dict:
    if body.x is None or body.y is None:
        return {"ok": False, "message": "click aksiyonu için 'x' ve 'y' koordinatları gerekli."}
    from ..features.desktop import xdotool_click
    result = await xdotool_click(body.x, body.y, button=body.button)
    ok = result.startswith("✅")
    logger.info("desktop/click: (%d,%d) button=%d → %s", body.x, body.y, body.button, "ok" if ok else "hata")
    return {"ok": ok, "message": result}


async def _handle_move(body: DesktopRequest) -> dict:
    if body.x is None or body.y is None:
        return {"ok": False, "message": "move aksiyonu için 'x' ve 'y' koordinatları gerekli."}
    from ..features.desktop import xdotool_move
    result = await xdotool_move(body.x, body.y)
    ok = result.startswith("✅")
    logger.info("desktop/move: (%d,%d) → %s", body.x, body.y, "ok" if ok else "hata")
    return {"ok": ok, "message": result}


async def _handle_scroll(body: DesktopRequest) -> dict:
    if not body.direction:
        return {"ok": False, "message": "scroll aksiyonu için 'direction' gerekli (up/down/left/right)."}
    from ..features.desktop import xdotool_scroll
    result = await xdotool_scroll(body.direction, amount=body.amount)
    ok = result.startswith("✅")
    logger.info("desktop/scroll: %s × %d → %s", body.direction, body.amount, "ok" if ok else "hata")
    return {"ok": ok, "message": result}



async def _handle_get_windows(body: DesktopRequest) -> dict:
    from ..features.desktop import get_windows
    text = await get_windows()
    ok = not text.startswith("❌")
    logger.info("desktop/get_windows: %s", "ok" if ok else "hata")
    return {"ok": ok, "message": text, "text": text}


async def _handle_focus_window(body: DesktopRequest) -> dict:
    if not body.window_id and not body.window_name:
        return {
            "ok": False,
            "message": "focus_window aksiyonu için 'window_id' (ör. '0x05000003') veya 'window_name' gerekli.",
        }
    from ..features.desktop import focus_window
    result = await focus_window(
        window_name=body.window_name,
        window_id=body.window_id,
    )
    ok = result.startswith("✅")
    logger.info(
        "desktop/focus_window: id=%s name=%r → %s",
        body.window_id, body.window_name, "ok" if ok else "hata",
    )
    return {"ok": ok, "message": result}


async def _handle_unlock_screen(body: DesktopRequest) -> dict:
    from ..features.desktop import unlock_screen
    result = await unlock_screen()
    ok = result.startswith("✅")
    logger.info("desktop/unlock_screen: %s", "ok" if ok else "hata")
    return {"ok": ok, "message": result}


async def _handle_is_locked(body: DesktopRequest) -> dict:
    """DESK-LOGIN-2: Ekran kilit durumunu boolean olarak döner."""
    from ..features.desktop import is_screen_locked
    locked = await is_screen_locked()
    logger.info("desktop/is_locked: %s", locked)
    return {"ok": True, "locked": locked, "message": f"Ekran {'kilitli' if locked else 'açık'}."}


async def _handle_sudo_exec(body: DesktopRequest) -> dict:
    if not body.sudo_cmd:
        return {"ok": False, "message": "sudo_exec aksiyonu için 'sudo_cmd' (komut listesi) gerekli."}
    from ..features.desktop import sudo_exec
    code, output = await sudo_exec(body.sudo_cmd, timeout=body.timeout)
    ok = code == 0
    logger.info("desktop/sudo_exec: cmd=%s returncode=%d", body.sudo_cmd[:3], code)
    return {"ok": ok, "message": output, "returncode": code}



async def _handle_get_desktop_tree(body: DesktopRequest) -> dict:
    if not (1 <= body.atspi_max_depth <= 6):
        return {"ok": False, "message": "atspi_max_depth 1–6 arasında olmalı."}
    from ..features.desktop import atspi_get_desktop_tree
    tree = await atspi_get_desktop_tree(max_depth=body.atspi_max_depth)
    ok = "error" not in tree
    logger.info("desktop/get_desktop_tree: depth=%d ok=%s", body.atspi_max_depth, ok)
    return {"ok": ok, "message": "AT-SPI tree alındı." if ok else tree.get("error", "?"), "tree": tree}


async def _handle_find_element(body: DesktopRequest) -> dict:
    if not body.atspi_role and not body.atspi_name:
        return {"ok": False, "message": "find_element için 'atspi_role' veya 'atspi_name' gerekli."}
    from ..features.desktop import atspi_find_element
    results = await atspi_find_element(
        role=body.atspi_role or "",
        name=body.atspi_name or "",
    )
    has_error = results and "error" in results[0]
    ok = not has_error
    count = len(results) if ok else 0
    logger.info(
        "desktop/find_element: role=%r name=%r → %d sonuç",
        body.atspi_role, body.atspi_name, count,
    )
    return {
        "ok": ok,
        "message": f"{count} element bulundu." if ok else results[0].get("error", "?"),
        "elements": results,
    }


async def _handle_activate_element(body: DesktopRequest) -> dict:
    if not body.atspi_role and not body.atspi_name:
        return {"ok": False, "message": "activate_element için 'atspi_role' veya 'atspi_name' gerekli."}
    from ..features.desktop import atspi_activate_element
    result = await atspi_activate_element(
        role=body.atspi_role or "",
        name=body.atspi_name or "",
    )
    ok = result.startswith("✅")
    logger.info(
        "desktop/activate_element: role=%r name=%r → %s",
        body.atspi_role, body.atspi_name, "ok" if ok else "hata",
    )
    return {"ok": ok, "message": result}


# ── DESK-OPT-8: Popup yönetimi — X11 MapNotify izleyicileri ─────────────

async def _handle_watch_popup(body: DesktopRequest) -> dict:
    """X11 MapNotify izleyiciyi başlatır; WM_CLASS eşleşmesinde pencereyi kapatır."""
    if not body.wm_class:
        return {
            "ok": False,
            "message": "watch_popup için 'wm_class' listesi gerekli (en az bir kalıp).",
        }
    from ..features.desktop import start_watch_popup
    ok, msg, wid = await start_watch_popup(
        wm_class_patterns=body.wm_class,
        timeout_s=float(body.timeout),
        watcher_id=body.watcher_id or None,
    )
    result = {"ok": ok, "message": msg}
    if ok:
        result["watcher_id"] = wid
    return result


async def _handle_stop_watch_popup(body: DesktopRequest) -> dict:
    """Çalışan popup izleyiciyi ID ile durdurur."""
    if not body.watcher_id:
        return {"ok": False, "message": "stop_watch_popup için 'watcher_id' gerekli."}
    from ..features.desktop import stop_watch_popup
    ok, msg = await stop_watch_popup(body.watcher_id)
    return {"ok": ok, "message": msg}


async def _handle_list_watch_popup(_body: DesktopRequest) -> dict:
    """Aktif popup izleyicileri listeler."""
    from ..features.desktop import list_watch_popups
    watchers = list_watch_popups()
    count = len(watchers)
    return {
        "ok": True,
        "message": f"{count} aktif izleyici." if count else "Aktif izleyici yok.",
        "watchers": watchers,
    }


# ── BUG-DESK-LOCK-1: Ekran kilitli iken klavye/fare girişi engelleme ──────
# xdotool type/key/click/move/scroll ekranın kilit durumundan habersiz çalışır;
# kilit açıksa lock screen şifre alanına yazabilir.

_INPUT_ACTIONS: frozenset[str] = frozenset({
    "type", "key", "click", "move", "scroll", "activate_element",
})


async def _check_screen_lock(action: str) -> dict | None:
    """
    Ekran kilitliyse input aksiyonları engeller.
    Engellenmesi gerekmiyorsa None döner, engel varsa hata dict'i döner.
    """
    if action not in _INPUT_ACTIONS:
        return None
    from ..features.desktop import is_screen_locked
    if await is_screen_locked():
        logger.warning(
            "desktop_router: ekran kilitli — '%s' aksiyonu engellendi (BUG-DESK-LOCK-1)",
            action,
        )
        return {
            "ok": False,
            "message": (
                f"❌ Ekran kilitli — '{action}' aksiyonu engellendi.\n"
                "Önce `unlock_screen` ile kilidi aç."
            ),
        }
    return None


# ── Dispatch tablosu — yeni aksiyon = yeni _handle_* + bir satır burada ──

_HANDLERS: dict[str, Callable[[DesktopRequest], Awaitable[dict]]] = {
    "open":              _handle_open,
    "run":               _handle_run,
    "type":              _handle_type,
    "key":               _handle_key,
    "click":             _handle_click,
    "move":              _handle_move,
    "scroll":            _handle_scroll,
    "get_windows":       _handle_get_windows,
    "focus_window":      _handle_focus_window,
    "unlock_screen":     _handle_unlock_screen,
    "is_locked":         _handle_is_locked,
    "sudo_exec":         _handle_sudo_exec,
    "get_desktop_tree":  _handle_get_desktop_tree,
    "find_element":      _handle_find_element,
    "activate_element":  _handle_activate_element,
    # DESK-OPT-8
    "watch_popup":       _handle_watch_popup,
    "stop_watch_popup":  _handle_stop_watch_popup,
    "list_watch_popup":  _handle_list_watch_popup,
    # SOLID-v2-6: vision + capture sub-modüllerinden
    **_vision.HANDLERS,
    **_capture.HANDLERS,
}


# ── LOG-DESK-1 yardımcıları ───────────────────────────────────────

async def _get_active_window() -> str:
    """
    Aktif (odaklı) pencerenin başlığını döner.
    xdotool kurulu değilse veya X11 oturumu yoksa boş string döner.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "getactivewindow", "getwindowname",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
        return stdout.decode().strip() if stdout else ""
    except Exception:
        return ""


# ── Parametre çıkarıcı registry — OCP-V1 ─────────────────────────
# Yeni aksiyon = yeni lambda girişi; _extract_params fonksiyonuna dokunma.

_PARAM_EXTRACTORS: dict[str, Callable[[DesktopRequest], dict]] = {
    "click":            lambda b: {"x": b.x, "y": b.y, "button": b.button},
    "move":             lambda b: {"x": b.x, "y": b.y, "button": None},
    "scroll":           lambda b: {"direction": b.direction, "amount": b.amount},
    "type":             lambda b: {
        "text_len": len(b.text or ""),
        "text_preview": (b.text or "")[:80],
        "delay_ms": b.delay_ms,
    },
    "key":              lambda b: {"key": b.key},
    "open":             lambda b: {"target": b.target, "timeout": b.timeout},
    "run":              lambda b: {"target": b.target, "timeout": b.timeout},
    "focus_window":     lambda b: {"window_id": b.window_id, "window_name": b.window_name},
    "sudo_exec":        lambda b: {"sudo_cmd": (b.sudo_cmd or [])[:3]},  # ilk 3 token
    "get_desktop_tree": lambda b: {"atspi_max_depth": b.atspi_max_depth},
    "find_element":     lambda b: {"atspi_role": b.atspi_role, "atspi_name": b.atspi_name},
    "activate_element": lambda b: {"atspi_role": b.atspi_role, "atspi_name": b.atspi_name},
    # DESK-OPT-8
    "watch_popup":      lambda b: {"wm_class": b.wm_class, "timeout": b.timeout, "watcher_id": b.watcher_id},
    "stop_watch_popup": lambda b: {"watcher_id": b.watcher_id},
    "list_watch_popup": lambda _b: {},
    # SOLID-v2-6: vision + capture sub-modüllerinden
    **_vision.PARAM_EXTRACTORS,
    **_capture.PARAM_EXTRACTORS,
}


def _extract_params(body: DesktopRequest) -> dict:
    """Aksiyon tipine göre loga yazılacak parametreleri döner."""
    extractor = _PARAM_EXTRACTORS.get(body.action)
    return extractor(body) if extractor else {}


# ── Endpoint ──────────────────────────────────────────────────────

@router.post("/internal/desktop")
async def desktop_action(body: DesktopRequest, request: Request):
    """
    PC otomasyon aksiyonu çalıştır.
    Yalnızca localhost'tan erişilebilir.
    """
    if not is_localhost(request):
        logger.warning(
            "desktop_action: yetkisiz IP reddedildi (host=%s)",
            request.client.host if request.client else "?",
        )
        return JSONResponse(status_code=403, content={"detail": "Yalnızca localhost erişimi"})

    if not settings.desktop_enabled:
        return {"ok": False, "message": "Desktop özelliği devre dışı (DESKTOP_ENABLED=false)."}

    # Admin TOTP gate — endpoint tetiklendiğinde ilk iş: oturum unlock kontrolü.
    # Gate açıksa None döner; kapalıysa sunucu WA üzerinden TOTP ister (DESK-TOTP-2).
    totp_err = await enforce_totp(body.code)
    if totp_err is not None:
        if totp_err.get("requires_totp"):
            # Sunucu tarafında TOTP iste: WA mesajı + session state (LLM değil, sunucu yönetir)
            await request_desktop_totp(settings.owner_id)
        logger.warning(
            "desktop_action: TOTP gate reddetti action=%s requires_totp=%s",
            body.action, totp_err.get("requires_totp"),
        )
        return totp_err

    handler = _HANDLERS.get(body.action)
    if handler is None:
        # _ALLOWED_ACTIONS validator'ı bu durumu önler; savunma amaçlı
        return {"ok": False, "message": f"Bilinmeyen aksiyon: {body.action}"}

    # BUG-DESK-LOCK-1 — ekran kilitliyse input aksiyonları engelle
    lock_err = await _check_screen_lock(body.action)
    if lock_err is not None:
        return lock_err

    # LOG-DESK-1 — aksiyon öncesi bağlam
    ts_start = time.monotonic()
    dt_start = datetime.now(timezone.utc).isoformat()
    active_window = await _get_active_window()
    params = _extract_params(body)

    result: dict = {}
    exc_info = None
    try:
        result = await handler(body)
    except Exception as exc:  # noqa: BLE001
        exc_info = exc
        result = {"ok": False, "message": f"❌ Beklenmeyen hata: {exc}"}

    duration_ms = round((time.monotonic() - ts_start) * 1000)
    dt_end = datetime.now(timezone.utc).isoformat()

    ok: bool = bool(result.get("ok", False))
    msg: str = result.get("message", "")

    logger.info(
        "desktop action: action=%s ok=%s duration_ms=%d active_window=%r",
        body.action, ok, duration_ms, active_window,
        extra={
            "desktop_action": body.action,
            "desktop_params": params,
            "desktop_active_window": active_window,
            "desktop_ok": ok,
            "desktop_result_summary": msg[:200] if msg else "",
            "desktop_error": str(exc_info) if exc_info else None,
            "desktop_ts_start": dt_start,
            "desktop_ts_end": dt_end,
            "desktop_duration_ms": duration_ms,
        },
    )

    if exc_info is not None:
        logger.exception(
            "desktop action exception: action=%s", body.action,
            exc_info=exc_info,
        )

    return result


# ── Batch endpoint ────────────────────────────────────────────────

class DesktopBatchRequest(BaseModel):
    """Birden fazla desktop aksiyonunu tek HTTP isteğinde zincirleme çalıştırır.

    execution_mode:
        "sequential" (varsayılan) — aksiyonlar sırayla çalışır;
                                    stop_on_error=True ise ilk hatayla durur.
        "parallel"               — aksiyonlar eş zamanlı çalışır;
                                    dikkat: X11 girişleri eş zamanlı gönderilir.
    stop_on_error:
        True (varsayılan) — sequential modda ilk başarısız aksiyon zinciri keser.
        False             — tüm aksiyonlar denenir, hatalar sonuç listesinde gösterilir.
    """
    actions: list[DesktopRequest]
    execution_mode: str = "sequential"
    stop_on_error: bool = True
    code: Optional[str] = None  # Admin TOTP — batch için tek seferlik; TTL boyunca tekrar istenmez

    @field_validator("actions")
    @classmethod
    def validate_actions(cls, v: list) -> list:
        if not v:
            raise ValueError("actions listesi boş olamaz.")
        if len(v) > DESKTOP_BATCH_MAX_ACTIONS:
            raise ValueError(
                f"Batch başına en fazla {DESKTOP_BATCH_MAX_ACTIONS} aksiyon desteklenir."
            )
        return v

    @field_validator("execution_mode")
    @classmethod
    def validate_execution_mode(cls, v: str) -> str:
        if v not in ("sequential", "parallel"):
            raise ValueError("execution_mode 'sequential' veya 'parallel' olmalı.")
        return v


async def _run_single(i: int, action_req: DesktopRequest) -> dict:
    """Tek aksiyonu çalıştırır; lock kontrolü dahil; hatayı yakalayıp dict döner."""
    lock_err = await _check_screen_lock(action_req.action)
    if lock_err is not None:
        return {"index": i, "action": action_req.action, **lock_err}

    handler = _HANDLERS.get(action_req.action)
    if handler is None:
        return {
            "index": i,
            "action": action_req.action,
            "ok": False,
            "message": f"Bilinmeyen aksiyon: {action_req.action}",
        }

    try:
        res = await handler(action_req)
    except Exception as exc:  # noqa: BLE001
        res = {"ok": False, "message": f"❌ Beklenmeyen hata: {exc}"}

    return {"index": i, "action": action_req.action, **res}


@router.post("/internal/desktop/batch")
async def desktop_batch(body: DesktopBatchRequest, request: Request):
    """Birden fazla desktop aksiyonunu tek HTTP isteğinde çalıştırır.

    Yalnızca localhost'tan erişilebilir.

    İstek gövdesi::

        {
            "actions": [
                {"action": "focus_window", "window_name": "Firefox"},
                {"action": "type", "text": "merhaba"},
                {"action": "key", "key": "Return"}
            ],
            "execution_mode": "sequential",
            "stop_on_error": true
        }

    Yanıt::

        {
            "ok": true,
            "results": [
                {"index": 0, "action": "focus_window", "ok": true, "message": "..."},
                {"index": 1, "action": "type",         "ok": true, "message": "..."},
                {"index": 2, "action": "key",          "ok": true, "message": "..."}
            ],
            "total": 3,
            "completed": 3,
            "duration_ms": 87
        }
    """
    if not is_localhost(request):
        logger.warning(
            "desktop_batch: yetkisiz IP reddedildi (host=%s)",
            request.client.host if request.client else "?",
        )
        return JSONResponse(status_code=403, content={"detail": "Yalnızca localhost erişimi"})

    if not settings.desktop_enabled:
        return {"ok": False, "message": "Desktop özelliği devre dışı (DESKTOP_ENABLED=false)."}

    # Admin TOTP gate — batch toplu bir oturum açar; tek TOTP ile tüm aksiyonlar geçer
    totp_err = await enforce_totp(body.code)
    if totp_err is not None:
        if totp_err.get("requires_totp"):
            await request_desktop_totp(settings.owner_id)
        logger.warning(
            "desktop_batch: TOTP gate reddetti total=%d requires_totp=%s",
            len(body.actions), totp_err.get("requires_totp"),
        )
        return totp_err

    ts_batch_start = time.monotonic()
    results: list[dict] = []

    if body.execution_mode == "sequential":
        for i, action_req in enumerate(body.actions):
            res = await _run_single(i, action_req)
            results.append(res)
            if not res.get("ok") and body.stop_on_error:
                break
    else:
        # parallel — asyncio.gather ile eş zamanlı
        gathered = await asyncio.gather(
            *[_run_single(i, a) for i, a in enumerate(body.actions)]
        )
        results = list(gathered)

    duration_ms = round((time.monotonic() - ts_batch_start) * 1000)
    all_ok = all(r.get("ok", False) for r in results)

    logger.info(
        "desktop/batch: mode=%s total=%d completed=%d ok=%s duration_ms=%d",
        body.execution_mode, len(body.actions), len(results), all_ok, duration_ms,
    )

    return {
        "ok": all_ok,
        "results": results,
        "total": len(body.actions),
        "completed": len(results),
        "duration_ms": duration_ms,
    }
