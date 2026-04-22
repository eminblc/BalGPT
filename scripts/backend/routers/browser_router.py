"""
/internal/browser — Playwright tabanlı tarayıcı otomasyon endpoint'i (FEAT-13 / FEAT-15).

Yalnızca localhost (127.0.0.1 / ::1) erişimine açıktır; API key gerekmez.
Bridge'den Claude Code CLI çağrısıyla kullanılır.

Kabul edilen aksiyonlar:
    goto                 → URL'ye git
    fill                 → Input alanını doldur (selector + value)
    click                → Elemente tıkla (selector)
    cdp_click            → CDP ile hızlı tıklama; actionability atlanır (DESK-OPT-5)
    screenshot           → Sayfa ekran görüntüsü (base64 PNG)
    get_text             → Element metin içeriği
    get_content          → Tüm sayfa HTML
    wait_for             → Element durumu bekle
    eval                 → JavaScript çalıştır
    close                → Session'ı kapat
    close_all            → Tüm session'ları kapat
    list_sessions        → Açık session'ları listele
    save_session         → Cookies+localStorage'ı diske kaydet (FEAT-15)
    delete_saved_session → Kaydedilmiş disk state'ini sil (FEAT-15)
    list_saved_sessions  → Diskteki kayıtlı session'ları listele (FEAT-15)
    session_info         → Session hakkında detaylı bilgi (FEAT-15)
    get_credential       → CREDENTIAL_<SITE>_<FIELD> env var'ını oku (FEAT-16)
    list_credentials     → Tanımlı credential site slug'larını listele (FEAT-16)

İstek gövdesi:
    {
        "action": "goto",
        "url": "https://example.com",
        "session_id": "default",          # isteğe bağlı — varsayılan: "default"
        "headless": true,                 # isteğe bağlı — varsayılan: true
        "timeout": 30000,                 # ms, isteğe bağlı

        # fill:
        "selector": "input[name='user']",
        "value": "kullanıcı adı",

        # click / cdp_click / get_text / wait_for:
        "selector": "button.submit",

        # cdp_click:
        "fallback": true,                # isteğe bağlı — CDP başarısızsa loc.click()'e düş

        # wait_for:
        "state": "visible",              # attached | detached | visible | hidden

        # eval:
        "script": "document.title",

        # screenshot:
        "full_page": false,              # isteğe bağlı

        # close:
        "session_id": "default",

        # get_credential:
        "site_slug": "mercek_itu",
        "field": "user"    # "user" | "pass" | herhangi bir alan
    }

Başarılı yanıt:
    {"ok": true, "message": "✅ ...", "text": "..."}
    {"ok": true, "message": "✅ ...", "image": "<base64>"}   # screenshot
    {"ok": true, "message": "✅ ...", "sessions": [...]}     # list_sessions

Hata yanıtı:
    {"ok": false, "message": "❌ hata açıklaması"}
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from ..config import settings
from ._localhost_guard import is_localhost

logger = logging.getLogger(__name__)
router = APIRouter()

_ALLOWED_ACTIONS = frozenset({
    "goto", "fill", "click", "cdp_click", "screenshot", "get_text",
    "get_content", "wait_for", "eval", "close", "close_all", "list_sessions",
    # FEAT-15 — disk kalıcılığı
    "save_session", "delete_saved_session", "list_saved_sessions", "session_info",
    # FEAT-16 — credential store
    "get_credential", "list_credentials",
    # BROWSER-1 — DOM-first genişletme
    "select_option", "check", "type", "press", "hover",
    "get_attribute", "scroll", "get_url",
})

_WAIT_STATES = frozenset({"attached", "detached", "visible", "hidden"})


# ── Request modeli ────────────────────────────────────────────────

class BrowserRequest(BaseModel):
    action: str

    # Genel
    session_id: str = "default"
    headless: bool = True
    timeout: int = 30_000   # ms

    # goto
    url: Optional[str] = None
    wait_until: str = "domcontentloaded"   # load | domcontentloaded | networkidle | commit

    # fill
    selector: Optional[str] = None
    value: Optional[str] = None

    # wait_for
    state: str = "visible"

    # eval
    script: Optional[str] = None

    # screenshot
    full_page: bool = False

    # cdp_click (DESK-OPT-5)
    fallback: bool = True             # CDP başarısızsa loc.click()'e düş

    # FEAT-16 — credential store
    site_slug: Optional[str] = None   # get_credential
    field: Optional[str] = None       # get_credential

    # BROWSER-1 — DOM-first genişletme
    label: Optional[str] = None       # select_option (label ile seçim)
    index: Optional[int] = None       # select_option (index ile seçim)
    checked: bool = True              # check (True=işaretle, False=kaldır)
    delay: int = 0                    # type (tuşlar arası ms bekleme)
    key: Optional[str] = None         # press (klavye tuşu)
    attribute: Optional[str] = None   # get_attribute
    direction: str = "down"           # scroll (up/down/left/right)
    amount: int = 500                 # scroll (piksel)

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        if v not in _ALLOWED_ACTIONS:
            raise ValueError(
                f"Geçersiz aksiyon: {v!r}. "
                f"Geçerliler: {', '.join(sorted(_ALLOWED_ACTIONS))}"
            )
        return v

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if not (1_000 <= v <= 120_000):
            raise ValueError("timeout 1000–120000 ms arasında olmalı.")
        return v

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        if v not in _WAIT_STATES:
            raise ValueError(
                f"Geçersiz state: {v!r}. "
                f"Geçerliler: {', '.join(sorted(_WAIT_STATES))}"
            )
        return v


# ── Aksiyon handler'ları ───────────────────────────────────────────

async def _handle_goto(body: BrowserRequest) -> dict:
    if not body.url:
        return {"ok": False, "message": "goto aksiyonu için 'url' gerekli."}
    from ..features.browser import browser_goto
    ok, msg = await browser_goto(
        body.url,
        session_id=body.session_id,
        headless=body.headless,
        timeout=body.timeout,
        wait_until=body.wait_until,
    )
    logger.info("browser/goto: %s → %s", body.url, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_fill(body: BrowserRequest) -> dict:
    if not body.selector:
        return {"ok": False, "message": "fill aksiyonu için 'selector' gerekli."}
    if body.value is None:
        return {"ok": False, "message": "fill aksiyonu için 'value' gerekli."}
    from ..features.browser import browser_fill
    ok, msg = await browser_fill(
        body.selector,
        body.value,
        session_id=body.session_id,
        headless=body.headless,
        timeout=body.timeout,
    )
    logger.info("browser/fill: selector=%r → %s", body.selector, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_click(body: BrowserRequest) -> dict:
    if not body.selector:
        return {"ok": False, "message": "click aksiyonu için 'selector' gerekli."}
    from ..features.browser import browser_click
    ok, msg = await browser_click(
        body.selector,
        session_id=body.session_id,
        headless=body.headless,
        timeout=body.timeout,
    )
    logger.info("browser/click: selector=%r → %s", body.selector, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_cdp_click(body: BrowserRequest) -> dict:
    if not body.selector:
        return {"ok": False, "message": "cdp_click aksiyonu için 'selector' gerekli."}
    from ..features.browser import browser_cdp_click
    ok, msg = await browser_cdp_click(
        body.selector,
        session_id=body.session_id,
        headless=body.headless,
        fallback=body.fallback,
    )
    logger.info("browser/cdp_click: selector=%r → %s", body.selector, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_screenshot(body: BrowserRequest) -> dict:
    from ..features.browser import browser_screenshot
    ok, msg, b64 = await browser_screenshot(
        session_id=body.session_id,
        headless=body.headless,
        full_page=body.full_page,
    )
    logger.info("browser/screenshot: session=%r → %s", body.session_id, "ok" if ok else "hata")
    result: dict = {"ok": ok, "message": msg}
    if b64:
        result["image"] = b64
    return result


async def _handle_get_text(body: BrowserRequest) -> dict:
    from ..features.browser import browser_get_text
    sel = body.selector or ""
    ok, msg, text = await browser_get_text(
        sel,
        session_id=body.session_id,
        headless=body.headless,
        timeout=body.timeout,
    )
    logger.info(
        "browser/get_text: selector=%r → %s (%d karakter)",
        sel, "ok" if ok else "hata", len(text) if text else 0,
    )
    return {"ok": ok, "message": msg, "text": text}


async def _handle_get_content(body: BrowserRequest) -> dict:
    from ..features.browser import browser_get_content
    ok, msg, html = await browser_get_content(
        session_id=body.session_id,
        headless=body.headless,
    )
    logger.info(
        "browser/get_content: session=%r → %s (%d bytes)",
        body.session_id, "ok" if ok else "hata", len(html) if html else 0,
    )
    return {"ok": ok, "message": msg, "text": html}


async def _handle_wait_for(body: BrowserRequest) -> dict:
    if not body.selector:
        return {"ok": False, "message": "wait_for aksiyonu için 'selector' gerekli."}
    from ..features.browser import browser_wait_for
    ok, msg = await browser_wait_for(
        body.selector,
        session_id=body.session_id,
        headless=body.headless,
        state=body.state,
        timeout=body.timeout,
    )
    logger.info(
        "browser/wait_for: selector=%r state=%s → %s",
        body.selector, body.state, "ok" if ok else "hata",
    )
    return {"ok": ok, "message": msg}


async def _handle_eval(body: BrowserRequest) -> dict:
    if not body.script:
        return {"ok": False, "message": "eval aksiyonu için 'script' gerekli."}
    from ..features.browser import browser_eval
    ok, msg, result_str = await browser_eval(
        body.script,
        session_id=body.session_id,
        headless=body.headless,
    )
    logger.info("browser/eval: session=%r → %s", body.session_id, "ok" if ok else "hata")
    return {"ok": ok, "message": msg, "text": result_str}


async def _handle_close(body: BrowserRequest) -> dict:
    from ..features.browser import browser_close
    ok, msg = await browser_close(body.session_id)
    logger.info("browser/close: session=%r → %s", body.session_id, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_close_all(body: BrowserRequest) -> dict:
    from ..features.browser import browser_close_all
    ok, msg = await browser_close_all()
    logger.info("browser/close_all → %s", "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_list_sessions(body: BrowserRequest) -> dict:
    from ..features.browser import browser_list_sessions
    sessions = await browser_list_sessions()
    logger.info("browser/list_sessions: %d açık session", len(sessions))
    return {"ok": True, "message": f"{len(sessions)} açık session.", "sessions": sessions}


async def _handle_save_session(body: BrowserRequest) -> dict:
    from ..features.browser import browser_save_session
    ok, msg = await browser_save_session(body.session_id)
    logger.info("browser/save_session: session=%r → %s", body.session_id, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_delete_saved_session(body: BrowserRequest) -> dict:
    from ..features.browser import browser_delete_saved_session
    ok, msg = await browser_delete_saved_session(body.session_id)
    logger.info(
        "browser/delete_saved_session: session=%r → %s",
        body.session_id, "ok" if ok else "hata",
    )
    return {"ok": ok, "message": msg}


async def _handle_list_saved_sessions(body: BrowserRequest) -> dict:
    from ..features.browser import browser_list_saved_sessions
    saved = await browser_list_saved_sessions()
    logger.info("browser/list_saved_sessions: %d kayıtlı session", len(saved))
    return {
        "ok": True,
        "message": f"{len(saved)} kayıtlı session.",
        "sessions": saved,
    }


async def _handle_session_info(body: BrowserRequest) -> dict:
    from ..features.browser import browser_session_info
    info = await browser_session_info(body.session_id)
    logger.info(
        "browser/session_info: session=%r active=%s saved=%s",
        body.session_id, info.get("active"), info.get("saved_state"),
    )
    return {"ok": True, "message": "Session bilgisi.", **info}


async def _handle_get_credential(body: BrowserRequest) -> dict:
    if not body.site_slug:
        return {"ok": False, "message": "get_credential için 'site_slug' gerekli."}
    if not body.field:
        return {"ok": False, "message": "get_credential için 'field' gerekli."}
    from ..features.credential_store import get_credential, _SECRET_FIELDS
    ok, msg, value = get_credential(body.site_slug, body.field)
    result: dict = {"ok": ok, "message": msg}
    if value is not None:
        result["value"] = value
    is_secret = body.field.lower() in _SECRET_FIELDS
    logger.info(
        "browser/get_credential: site=%r field=%r ok=%s value=%s",
        body.site_slug, body.field, ok,
        "***" if is_secret else (value[:20] + "…" if value and len(value) > 20 else value),
    )
    return result


async def _handle_list_credentials(body: BrowserRequest) -> dict:
    from ..features.credential_store import list_credentials
    slugs = list_credentials()
    logger.info("browser/list_credentials: %d site tanımlı", len(slugs))
    return {
        "ok": True,
        "message": f"{len(slugs)} site credential'ı tanımlı.",
        "sites": slugs,
    }


# ── BROWSER-1: DOM-first handler'lar ────────────────────────────────────────


async def _handle_select_option(body: BrowserRequest) -> dict:
    if not body.selector:
        return {"ok": False, "message": "select_option için 'selector' gerekli."}
    from ..features.browser import browser_select_option
    ok, msg = await browser_select_option(
        body.selector,
        value=body.value,
        label=body.label,
        index=body.index,
        session_id=body.session_id,
        headless=body.headless,
        timeout=body.timeout,
    )
    logger.info("browser/select_option: selector=%r → %s", body.selector, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_check(body: BrowserRequest) -> dict:
    if not body.selector:
        return {"ok": False, "message": "check için 'selector' gerekli."}
    from ..features.browser import browser_check
    ok, msg = await browser_check(
        body.selector,
        checked=body.checked,
        session_id=body.session_id,
        headless=body.headless,
        timeout=body.timeout,
    )
    logger.info("browser/check: selector=%r checked=%s → %s", body.selector, body.checked, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_type(body: BrowserRequest) -> dict:
    if not body.selector:
        return {"ok": False, "message": "type için 'selector' gerekli."}
    if body.value is None:
        return {"ok": False, "message": "type için 'value' gerekli."}
    from ..features.browser import browser_type
    ok, msg = await browser_type(
        body.selector,
        body.value,
        delay=body.delay,
        session_id=body.session_id,
        headless=body.headless,
        timeout=body.timeout,
    )
    logger.info("browser/type: selector=%r → %s", body.selector, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_press(body: BrowserRequest) -> dict:
    if not body.key:
        return {"ok": False, "message": "press için 'key' gerekli."}
    from ..features.browser import browser_press
    ok, msg = await browser_press(
        body.key,
        session_id=body.session_id,
        headless=body.headless,
    )
    logger.info("browser/press: key=%r → %s", body.key, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_hover(body: BrowserRequest) -> dict:
    if not body.selector:
        return {"ok": False, "message": "hover için 'selector' gerekli."}
    from ..features.browser import browser_hover
    ok, msg = await browser_hover(
        body.selector,
        session_id=body.session_id,
        headless=body.headless,
        timeout=body.timeout,
    )
    logger.info("browser/hover: selector=%r → %s", body.selector, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_get_attribute(body: BrowserRequest) -> dict:
    if not body.selector:
        return {"ok": False, "message": "get_attribute için 'selector' gerekli."}
    if not body.attribute:
        return {"ok": False, "message": "get_attribute için 'attribute' gerekli."}
    from ..features.browser import browser_get_attribute
    ok, msg, val = await browser_get_attribute(
        body.selector,
        body.attribute,
        session_id=body.session_id,
        headless=body.headless,
        timeout=body.timeout,
    )
    logger.info("browser/get_attribute: selector=%r attr=%r → %s", body.selector, body.attribute, "ok" if ok else "hata")
    result: dict = {"ok": ok, "message": msg}
    if val is not None:
        result["value"] = val
    return result


async def _handle_scroll(body: BrowserRequest) -> dict:
    from ..features.browser import browser_scroll
    ok, msg = await browser_scroll(
        direction=body.direction,
        amount=body.amount,
        selector=body.selector,
        session_id=body.session_id,
        headless=body.headless,
    )
    logger.info("browser/scroll: direction=%s amount=%d → %s", body.direction, body.amount, "ok" if ok else "hata")
    return {"ok": ok, "message": msg}


async def _handle_get_url(body: BrowserRequest) -> dict:
    from ..features.browser import browser_get_url
    ok, msg, url = await browser_get_url(
        session_id=body.session_id,
        headless=body.headless,
    )
    logger.info("browser/get_url: → %s", "ok" if ok else "hata")
    result: dict = {"ok": ok, "message": msg}
    if url is not None:
        result["url"] = url
    return result


# ── Dispatch tablosu — yeni aksiyon = yeni _handle_* + bir satır burada ──

_HANDLERS: dict[str, Callable[[BrowserRequest], Awaitable[dict]]] = {
    "goto":                 _handle_goto,
    "fill":                 _handle_fill,
    "click":                _handle_click,
    "cdp_click":            _handle_cdp_click,
    "screenshot":           _handle_screenshot,
    "get_text":             _handle_get_text,
    "get_content":          _handle_get_content,
    "wait_for":             _handle_wait_for,
    "eval":                 _handle_eval,
    "close":                _handle_close,
    "close_all":            _handle_close_all,
    "list_sessions":        _handle_list_sessions,
    "save_session":         _handle_save_session,
    "delete_saved_session": _handle_delete_saved_session,
    "list_saved_sessions":  _handle_list_saved_sessions,
    "session_info":         _handle_session_info,
    "get_credential":       _handle_get_credential,
    "list_credentials":     _handle_list_credentials,
    # BROWSER-1 — DOM-first genişletme
    "select_option":        _handle_select_option,
    "check":                _handle_check,
    "type":                 _handle_type,
    "press":                _handle_press,
    "hover":                _handle_hover,
    "get_attribute":        _handle_get_attribute,
    "scroll":               _handle_scroll,
    "get_url":              _handle_get_url,
}


# ── Endpoint ──────────────────────────────────────────────────────

@router.post("/internal/browser")
async def browser_action(body: BrowserRequest, request: Request):
    """
    Playwright tarayıcı aksiyonu çalıştır.
    Yalnızca localhost'tan erişilebilir.
    """
    if not is_localhost(request):
        logger.warning(
            "browser_action: yetkisiz IP reddedildi (host=%s)",
            request.client.host if request.client else "?",
        )
        return JSONResponse(status_code=403, content={"detail": "Yalnızca localhost erişimi"})

    if not settings.browser_enabled:
        return {"ok": False, "message": "Tarayıcı özelliği devre dışı (BROWSER_ENABLED=false)."}

    handler = _HANDLERS.get(body.action)
    if handler is None:
        # _ALLOWED_ACTIONS validator'ı bu durumu önler; savunma amaçlı
        return {"ok": False, "message": f"Bilinmeyen aksiyon: {body.action}"}
    return await handler(body)
