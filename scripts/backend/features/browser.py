"""
Playwright tabanlı tarayıcı otomasyon modülü (FEAT-13 / FEAT-15).

Desktop screenshot+vision döngüsüne (15-30s, 5-8 API call) kıyasla
web görevleri için 3-5s ve 0-1 API call ile tamamlanır.

Oturum yönetimi (FEAT-15):
    - Her session_id için bağımsız Playwright browser+context+page
    - Varsayılan session_id: "default"
    - Browser instance'ları bellekte tutulur — servis restart'a kadar açık kalır
    - Disk kalıcılığı: save_session() → storage_state (cookies+localStorage) diske yazılır
    - Yeni session açılırken kayıtlı state varsa otomatik yüklenir (login gerekmez)
    - close() veya lifespan shutdown ile bellekten temizlenir

Desteklenen aksiyonlar:
    goto              → URL'ye git
    fill              → Input alanını doldur (selector + value)
    click             → Elemente tıkla (selector)
    screenshot        → Sayfanın ekran görüntüsünü al (base64 PNG döner)
    get_text          → Elementin metin içeriğini al (selector)
    get_content       → Tüm sayfa HTML içeriğini al
    wait_for          → Element görünür/etkin/gizli olana kadar bekle
    eval              → JavaScript çalıştır
    close             → Session'ı kapat (browser + context + page)
    close_all         → Tüm açık session'ları kapat
    save_session      → Mevcut cookies+localStorage'ı diske kaydet (FEAT-15)
    delete_saved_session → Kaydedilmiş disk state'ini sil (FEAT-15)
    list_saved_sessions  → Diskteki kayıtlı session'ları listele (FEAT-15)
    session_info      → Session hakkında detaylı bilgi (FEAT-15)

Kurulum:
    pip install playwright
    playwright install chromium
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import tempfile
import urllib.parse
from pathlib import Path
from typing import Any, Optional, TypedDict

logger = logging.getLogger(__name__)

# ── Tip tanımları ────────────────────────────────────────────────


class BrowserSession(TypedDict):
    """Tek bir Playwright browser oturumunun bileşenlerini tutan TypedDict.

    playwright: async_playwright() ile başlatılan Playwright örneği
    browser:    Chromium browser instance
    context:    BrowserContext (cookie/localStorage izolasyonu)
    page:       Aktif Page nesnesi
    """

    playwright: Any  # playwright.async_api.Playwright
    browser: Any     # playwright.async_api.Browser
    context: Any     # playwright.async_api.BrowserContext
    page: Any        # playwright.async_api.Page


# ── Session deposu ────────────────────────────────────────────────


class _BrowserSessionStore:
    """
    Playwright session'larını ve erişim kilidini tek yerde tutan singleton.

    Modül düzeyinde ham dict + Lock yerine bu sınıf kullanılır; global
    mutable state CLAUDE.md kuralına aykırı olduğundan encapsulation zorunludur.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def get(self, session_id: str) -> BrowserSession | None:
        return self._sessions.get(session_id)

    def set(self, session_id: str, sess: BrowserSession) -> None:
        self._sessions[session_id] = sess

    def pop(self, session_id: str) -> BrowserSession | None:
        return self._sessions.pop(session_id, None)

    def keys(self) -> list[str]:
        return list(self._sessions.keys())

    def items(self) -> list[tuple[str, BrowserSession]]:
        return list(self._sessions.items())

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._sessions


_session_store = _BrowserSessionStore()


# ── Yardımcılar ──────────────────────────────────────────────────

_BROWSER_ROOT = Path(__file__).parent.parent.parent.parent  # 99-root/


def _resolve_sessions_dir() -> Path:
    """browser_sessions_dir göreceli ise 99-root'a göre çözümler, mutlak ise olduğu gibi döner."""
    from ..config import settings
    p = Path(settings.browser_sessions_dir)
    return p if p.is_absolute() else _BROWSER_ROOT / p


_MAX_SESSION_ID_LEN = 128


def _get_storage_state_path(session_id: str) -> Path:
    """
    Verilen session_id için disk storage state dosya yolunu döndürür.
    Dizin yoksa oluşturur.
    """
    stripped = session_id.strip()
    if not stripped:
        raise ValueError("session_id boş olamaz")
    if len(stripped) > _MAX_SESSION_ID_LEN:
        raise ValueError(
            f"session_id çok uzun ({len(stripped)} > {_MAX_SESSION_ID_LEN})"
        )
    sessions_dir = _resolve_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    # Dosya adı: session_id'deki özel karakterleri güvenli hale getir
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in stripped)
    if not safe_id:
        safe_id = "_empty_"
    return sessions_dir / f"{safe_id}.json"


async def _get_or_create_session(session_id: str, headless: bool = True) -> BrowserSession:
    """
    Mevcut session'ı döndürür; yoksa yeni Playwright browser açar.
    Eğer diskte kayıtlı storage state varsa context'e yüklenir (FEAT-15).
    Thread-safe: _session_store.lock ile korunur.
    """
    async with _session_store.lock:
        if session_id in _session_store:
            sess = _session_store.get(session_id)
            # Sayfa hâlâ açık mı kontrol et
            try:
                _ = sess["page"].url
                return sess
            except Exception:
                # Sayfa kapanmış — session'ı temizle ve yeniden aç
                logger.warning("browser: session %r geçersiz, yeniden başlatılıyor", session_id)
                await _close_session_internal(session_id)

        # RISK-6: Eş zamanlı session limiti
        from ..config import settings
        max_sess = settings.browser_max_sessions
        active_count = len(_session_store.keys())
        if active_count >= max_sess:
            raise RuntimeError(
                f"Maksimum browser session sayısına ulaşıldı ({max_sess}). "
                f"Mevcut session'lardan birini kapatın (close aksiyonu)."
            )

        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        browser = None
        context = None
        try:
            browser = await pw.chromium.launch(headless=headless)

            # FEAT-15: Kayıtlı storage state varsa yükle
            storage_path = _get_storage_state_path(session_id)
            context_kwargs: dict = {
                "viewport": {"width": 1280, "height": 800},
                "user_agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
            }
            if storage_path.exists():
                context_kwargs["storage_state"] = str(storage_path)
                logger.info(
                    "browser: kayıtlı storage state yüklendi: %r (%d bytes)",
                    session_id, storage_path.stat().st_size,
                )

            context = await browser.new_context(**context_kwargs)
            page = await context.new_page()
        except Exception:
            # Kaynak sızıntısını önle: hata durumunda tüm kaynakları temizle
            if context is not None:
                try:
                    await context.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass
            try:
                await pw.stop()
            except Exception:
                pass
            raise

        sess: BrowserSession = {"playwright": pw, "browser": browser, "context": context, "page": page}
        _session_store.set(session_id, sess)
        logger.info(
            "browser: yeni session açıldı: %r (headless=%s, saved_state=%s)",
            session_id, headless, storage_path.exists(),
        )
        return sess


async def _close_session_internal(session_id: str) -> None:
    """Lock dışından veya içinden çağrılır — lock almaz."""
    sess = _session_store.pop(session_id)
    if not sess:
        return
    try:
        await sess["browser"].close()
    except Exception as e:
        logger.debug("browser close hata: %s", e)
    try:
        await sess["playwright"].stop()
    except Exception as e:
        logger.debug("playwright stop hata: %s", e)
    logger.info("browser: session kapatıldı: %r", session_id)


# ── Yardımcı: CSS locator ────────────────────────────────────────


def _make_locator(page: Any, selector: str) -> Any:
    """
    CSS seçiciler için ``css=`` ön eki ekleyerek Playwright Locator döndürür.
    XPath, text=, role= vb. özel motorlar olduğu gibi bırakılır.

    Neden: ön ek olmayan Locator, Playwright'ın dahili selector router'ını
    çalıştırır; bu router Accessibility Tree'yi de tarayabilir (getByRole
    benzeri davranış, ~1.5× daha yavaş). Açık ``css=`` motoru AT taramasını
    tamamen atlar.
    """
    _XPATH_OR_SPECIAL = ("//", "(//", "text=", "role=", "aria=", "css=", "xpath=", "id=")
    if any(selector.startswith(p) for p in _XPATH_OR_SPECIAL):
        return page.locator(selector)
    return page.locator(f"css={selector}")


# ── URL Doğrulama (RISK-1) ────────────────────────────────────────

_BLOCKED_SCHEMES = frozenset({"file", "ftp", "javascript", "data", "chrome", "about"})
_BLOCKED_HOSTS = frozenset({
    "169.254.169.254",          # AWS/GCP metadata
    "metadata.google.internal", # GCP metadata
    "100.100.100.200",          # Alibaba metadata
})


def _validate_url(url: str) -> str | None:
    """URL güvenlik kontrolü (RISK-1). Hata mesajı döner; geçerliyse None."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return "Geçersiz URL formatı"

    scheme = parsed.scheme.lower()
    if scheme in _BLOCKED_SCHEMES:
        return f"Yasaklı URL şeması: {scheme}://"
    if not scheme or scheme not in ("http", "https"):
        return f"Yalnızca http/https desteklenir (gelen: {scheme or 'boş'}://)"

    host = parsed.hostname or ""
    if host in _BLOCKED_HOSTS:
        return f"Yasaklı hedef: {host}"
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return f"Localhost erişimi yasaklı: {host}"

    return None


# ── Hassas Site Koruması (RISK-3) ────────────────────────────────

_SENSITIVE_DOMAINS = frozenset({
    # Mesajlaşma — yanlış kişiye mesaj gönderme riski
    "web.whatsapp.com",
    "web.telegram.org",
    # E-posta
    "mail.google.com",
    "outlook.live.com",
    "outlook.office365.com",
    # Sosyal medya
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    # Finansal
    "online.isbank.com.tr",
    "internet.yapikredi.com.tr",
    "ibank.akbank.com",
    "internet.garanti.com.tr",
})


def _check_sensitive_navigation(
    url: str,
    session_id: str,
    current_page_url: str | None = None,
) -> str | None:
    """
    Hassas siteye navigasyon uyarısı üret (RISK-3).

    İki senaryo:
    1. Hedef URL hassas bir site → uyarı logla (engelleme yok)
    2. Mevcut sayfa hassas site ve yeni hedef farklı domain → cookie sızıntısı uyarısı
    Döner: uyarı mesajı (log amaçlı) veya None.
    """
    try:
        new_host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return None

    # Senaryo 1: hassas siteye gidiş
    if new_host in _SENSITIVE_DOMAINS:
        return (
            f"⚠️ Hassas site navigasyonu: {new_host} "
            f"(session={session_id!r}). Ayrı session önerilir."
        )

    # Senaryo 2: hassas siteden farklı siteye geçiş
    if current_page_url:
        try:
            current_host = (urllib.parse.urlparse(current_page_url).hostname or "").lower()
        except Exception:
            return None
        if current_host in _SENSITIVE_DOMAINS and new_host != current_host:
            return (
                f"⚠️ Hassas siteden ({current_host}) farklı siteye ({new_host}) "
                f"navigasyon — oturum cookie'leri context'te kalıyor "
                f"(session={session_id!r})."
            )

    return None


# ── Aksiyonlar ───────────────────────────────────────────────────

async def browser_goto(
    url: str,
    session_id: str = "default",
    headless: bool = True,
    timeout: int = 30_000,
    wait_until: str = "domcontentloaded",
) -> tuple[bool, str]:
    """
    URL'ye git.
    Döner: (ok, mesaj)

    wait_until:
        "domcontentloaded" — DOM hazır; SPA'larda güvenli, hızlı (varsayılan)
        "load"             — tüm alt kaynaklar yüklendi
        "commit"           — ilk byte alındı
        "networkidle"      — SPA'larda asla bitmeyebilir; kullanma
    """
    err = _validate_url(url)
    if err:
        logger.warning("browser/goto: URL reddedildi: %s → %s", url, err)
        return False, f"❌ {err}"
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        page = sess["page"]

        # RISK-3: Hassas site navigasyon kontrolü
        try:
            current_url = page.url
        except Exception:
            current_url = None
        sensitive_warning = _check_sensitive_navigation(url, session_id, current_url)
        if sensitive_warning:
            logger.warning("browser/goto: %s", sensitive_warning)

        response = await page.goto(url, timeout=timeout, wait_until=wait_until)
        status = response.status if response else 0
        logger.info("browser/goto: %s → HTTP %d (session=%r)", url, status, session_id)
        if status and status >= 400:
            return False, f"❌ HTTP {status}: {url}"
        msg = f"✅ Sayfa yüklendi: {url} (HTTP {status})"
        if sensitive_warning:
            msg += f"\n{sensitive_warning}"
        return True, msg
    except Exception as e:
        logger.warning("browser/goto hata: %s", e)
        return False, f"❌ Sayfa yüklenemedi: {e}"


async def browser_fill(
    selector: str,
    value: str,
    session_id: str = "default",
    headless: bool = True,
    timeout: int = 10_000,
) -> tuple[bool, str]:
    """
    CSS/XPath selector ile input alanını doldur.

    Locator API kullanılır: tek çağrıda actionability kontrolü (visible +
    stable) + fill. Önceki iki adımlı ``wait_for_selector`` + ``fill``
    yerine daha hızlı ve Accessibility Tree'yi taramaz.
    """
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        loc = _make_locator(sess["page"], selector)
        await loc.fill(value, timeout=timeout)
        logger.info("browser/fill: selector=%r, len=%d (session=%r)", selector, len(value), session_id)
        return True, f"✅ Alan dolduruldu: {selector}"
    except Exception as e:
        logger.warning("browser/fill hata: selector=%r, %s", selector, e)
        return False, f"❌ Alan doldurulamadı ({selector}): {e}"


async def browser_click(
    selector: str,
    session_id: str = "default",
    headless: bool = True,
    timeout: int = 10_000,
) -> tuple[bool, str]:
    """
    CSS/XPath selector ile elemente tıkla.

    Locator API: auto-wait (visible + stable + enabled) + click tek adımda.
    """
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        loc = _make_locator(sess["page"], selector)
        await loc.click(timeout=timeout)
        logger.info("browser/click: selector=%r (session=%r)", selector, session_id)
        return True, f"✅ Tıklandı: {selector}"
    except Exception as e:
        logger.warning("browser/click hata: selector=%r, %s", selector, e)
        return False, f"❌ Tıklanamadı ({selector}): {e}"


async def browser_screenshot(
    session_id: str = "default",
    headless: bool = True,
    full_page: bool = False,
) -> tuple[bool, str, Optional[str]]:
    """
    Mevcut sayfanın ekran görüntüsünü al.
    Döner: (ok, mesaj, base64_png_or_none)
    """
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        page = sess["page"]
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        await page.screenshot(path=tmp_path, full_page=full_page)
        raw = Path(tmp_path).read_bytes()
        Path(tmp_path).unlink(missing_ok=True)
        b64 = base64.b64encode(raw).decode()
        logger.info(
            "browser/screenshot: %d bytes, session=%r",
            len(raw), session_id,
        )
        return True, "✅ Ekran görüntüsü alındı.", b64
    except Exception as e:
        logger.warning("browser/screenshot hata: %s", e)
        return False, f"❌ Ekran görüntüsü alınamadı: {e}", None


async def browser_get_text(
    selector: str,
    session_id: str = "default",
    headless: bool = True,
    timeout: int = 10_000,
) -> tuple[bool, str, Optional[str]]:
    """
    Elementin görünür metin içeriğini döndür.
    Selector boş string → tüm sayfa metni (body).
    Döner: (ok, mesaj, metin_or_none)

    Locator API: visible beklemesi + inner_text tek adımda.
    """
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        target = selector or "body"
        loc = _make_locator(sess["page"], target)
        text = await loc.inner_text(timeout=timeout)
        logger.info(
            "browser/get_text: selector=%r, %d karakter, session=%r",
            target, len(text), session_id,
        )
        return True, "✅ Metin alındı.", text
    except Exception as e:
        logger.warning("browser/get_text hata: selector=%r, %s", selector, e)
        return False, f"❌ Metin alınamadı ({selector}): {e}", None


async def browser_get_content(
    session_id: str = "default",
    headless: bool = True,
) -> tuple[bool, str, Optional[str]]:
    """Tüm sayfa HTML içeriğini döndür."""
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        page = sess["page"]
        html = await page.content()
        logger.info("browser/get_content: %d bytes, session=%r", len(html), session_id)
        return True, "✅ Sayfa içeriği alındı.", html
    except Exception as e:
        logger.warning("browser/get_content hata: %s", e)
        return False, f"❌ Sayfa içeriği alınamadı: {e}", None


async def browser_wait_for(
    selector: str,
    session_id: str = "default",
    headless: bool = True,
    state: str = "visible",
    timeout: int = 15_000,
) -> tuple[bool, str]:
    """
    Element belirli duruma gelene kadar bekle.
    state: "attached" | "detached" | "visible" | "hidden"

    Locator.wait_for() ile CSS motoruna kilitli bekleme.
    """
    valid_states = {"attached", "detached", "visible", "hidden"}
    if state not in valid_states:
        return False, f"❌ Geçersiz state: {state!r}. Geçerliler: {', '.join(sorted(valid_states))}"
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        loc = _make_locator(sess["page"], selector)
        await loc.wait_for(state=state, timeout=timeout)  # type: ignore[arg-type]
        logger.info("browser/wait_for: selector=%r state=%s (session=%r)", selector, state, session_id)
        return True, f"✅ Element beklendi: {selector} (state={state})"
    except Exception as e:
        logger.warning("browser/wait_for hata: selector=%r, %s", selector, e)
        return False, f"❌ Element bulunamadı ({selector}, state={state}): {e}"


_RISKY_JS_PATTERNS = ("fetch(", "XMLHttpRequest", "window.open", "document.write", "eval(")


async def browser_eval(
    script: str,
    session_id: str = "default",
    headless: bool = True,
) -> tuple[bool, str, Optional[str]]:
    """
    Sayfada JavaScript çalıştır.
    Döner: (ok, mesaj, sonuç_string_or_none)
    Güvenlik: Bu endpoint yalnızca localhost'tan erişilebilir.
    """
    script_hash = hashlib.sha256(script.encode()).hexdigest()[:12]

    if any(p in script for p in _RISKY_JS_PATTERNS):
        logger.warning(
            "browser/eval: RISKY pattern detected — hash=%s len=%d session=%r",
            script_hash, len(script), session_id,
        )

    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        page = sess["page"]
        result = await page.evaluate(script)
        result_str = str(result) if result is not None else "null"
        logger.info(
            "browser/eval: hash=%s len=%d script=%r → %r (session=%r)",
            script_hash, len(script), script[:120], result_str[:120], session_id,
        )
        return True, "✅ JS çalıştırıldı.", result_str
    except Exception as e:
        logger.warning("browser/eval hata: hash=%s %s", script_hash, e)
        return False, f"❌ JS çalıştırılamadı: {e}", None


async def browser_cdp_click(
    selector: str,
    session_id: str = "default",
    headless: bool = True,
    fallback: bool = True,
) -> tuple[bool, str]:
    """
    CDP ile hızlı tıklama — Playwright actionability kontrollerini atlar.

    Normal ``page.click()`` ~20-100 ms'lik actionability döngüsü (visible +
    stable + enabled) çalıştırır. Bu fonksiyon:
      1. ``locator.bounding_box()`` ile element konumunu alır (actionability yok).
      2. Playwright context CDP session'ı üzerinden ``Input.dispatchMouseEvent``
         (mousePressed + mouseReleased) gönderir — C++ tarayıcı motoruna direkt.

    Hız kritik aksiyonlar için kullan (ör. WhatsApp Web mesaj gönder tuşu).
    Görünür olmayan elementler için davranış tanımsızdır.

    fallback=True (varsayılan): CDP başarısız olursa otomatik ``loc.click()``'e düşer.
    """
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        page = sess["page"]
        context = sess["context"]

        # Adım 1: element konumunu al (actionability check yok)
        loc = _make_locator(page, selector)
        bbox = await loc.bounding_box()
        if bbox is None:
            if fallback:
                logger.debug(
                    "browser/cdp_click: bounding_box None, fallback → loc.click() (selector=%r)",
                    selector,
                )
                await loc.click()
                logger.info("browser/cdp_click[fallback]: selector=%r (session=%r)", selector, session_id)
                return True, f"✅ Tıklandı (fallback): {selector}"
            return False, f"❌ Element görünür değil veya bulunamadı: {selector}"

        x = bbox["x"] + bbox["width"] / 2
        y = bbox["y"] + bbox["height"] / 2

        # Adım 2: CDP session aç + mousePressed + mouseReleased gönder
        cdp = await context.new_cdp_session(page)
        try:
            _mouse_event = {
                "x": x,
                "y": y,
                "button": "left",
                "clickCount": 1,
                "modifiers": 0,
            }
            await cdp.send("Input.dispatchMouseEvent", {**_mouse_event, "type": "mousePressed"})
            await cdp.send("Input.dispatchMouseEvent", {**_mouse_event, "type": "mouseReleased"})
        finally:
            await cdp.detach()

        logger.info(
            "browser/cdp_click: selector=%r x=%.1f y=%.1f (session=%r)",
            selector, x, y, session_id,
        )
        return True, f"✅ CDP tıklama: {selector}"

    except Exception as e:
        logger.warning("browser/cdp_click hata: selector=%r, %s", selector, e)
        if fallback:
            try:
                sess = await _get_or_create_session(session_id, headless=headless)
                loc = _make_locator(sess["page"], selector)
                await loc.click()
                logger.info(
                    "browser/cdp_click[fallback]: selector=%r (session=%r)", selector, session_id,
                )
                return True, f"✅ Tıklandı (fallback): {selector}"
            except Exception as e2:
                return False, f"❌ Tıklanamadı ({selector}): {e2}"
        return False, f"❌ CDP tıklama başarısız ({selector}): {e}"


async def browser_close(session_id: str = "default") -> tuple[bool, str]:
    """Belirli bir session'ı kapat."""
    async with _session_store.lock:
        if session_id not in _session_store:
            return False, f"❌ Session bulunamadı: {session_id!r}"
        await _close_session_internal(session_id)
    return True, f"✅ Session kapatıldı: {session_id}"


async def browser_close_all() -> tuple[bool, str]:
    """Tüm açık session'ları kapat. FastAPI lifespan shutdown'ında çağrılır."""
    async with _session_store.lock:
        ids = _session_store.keys()
        for sid in ids:
            await _close_session_internal(sid)
    count = len(ids)
    if count:
        logger.info("browser: %d session kapatıldı", count)
    return True, f"✅ {count} session kapatıldı."


async def browser_list_sessions() -> list[dict]:
    """Açık session'ları ve mevcut URL'lerini listele."""
    result = []
    async with _session_store.lock:
        for sid, sess in _session_store.items():
            try:
                url = sess["page"].url
            except Exception:
                url = "(bilinmiyor)"
            saved = _get_storage_state_path(sid).exists()
            result.append({"session_id": sid, "url": url, "saved_state": saved})
    return result


# ── FEAT-15: Disk kalıcılığı aksiyonları ─────────────────────────

async def browser_save_session(session_id: str = "default") -> tuple[bool, str]:
    """
    Mevcut session'ın cookies ve localStorage'ını diske kaydet.
    Kaydedilen state servis yeniden başlatıldığında otomatik yüklenir.
    """
    async with _session_store.lock:
        sess = _session_store.get(session_id)
        if not sess:
            return False, f"❌ Aktif session bulunamadı: {session_id!r}. Önce oturum açın."
        context = sess["context"]
        storage_path = _get_storage_state_path(session_id)
        try:
            await context.storage_state(path=str(storage_path))
            size = storage_path.stat().st_size
            logger.info(
                "browser/save_session: session=%r → %s (%d bytes)",
                session_id, storage_path, size,
            )
            return True, f"✅ Oturum kaydedildi: {session_id!r} ({size} bytes)"
        except Exception as e:
            logger.warning("browser/save_session hata: session=%r, %s", session_id, e)
            return False, f"❌ Oturum kaydedilemedi: {e}"


async def browser_delete_saved_session(session_id: str = "default") -> tuple[bool, str]:
    """
    Diskteki kayıtlı storage state'ini sil.
    Bellekteki aktif session'ı kapatmaz.
    """
    storage_path = _get_storage_state_path(session_id)
    if not storage_path.exists():
        return False, f"❌ Kayıtlı oturum bulunamadı: {session_id!r}"
    try:
        storage_path.unlink()
        logger.info("browser/delete_saved_session: session=%r silindi", session_id)
        return True, f"✅ Kayıtlı oturum silindi: {session_id!r}"
    except Exception as e:
        logger.warning("browser/delete_saved_session hata: %s", e)
        return False, f"❌ Silinemedi: {e}"


async def browser_list_saved_sessions() -> list[dict]:
    """
    Diskteki kayıtlı session dosyalarını listele.
    Bellekteki aktif session'larla bağımsızdır.
    """
    sessions_dir = _resolve_sessions_dir()
    if not sessions_dir.exists():
        return []
    result = []
    async with _session_store.lock:
        active_ids = set(_session_store.keys())
    for f in sorted(sessions_dir.glob("*.json")):
        # Güvenli dosya adından session_id'yi geri al
        sid = f.stem  # dosya adı (uzantısız) — kayıt sırasında safe_id olarak yazılmıştı
        stat = f.stat()
        result.append({
            "session_id": sid,
            "size_bytes": stat.st_size,
            "active": sid in active_ids,
        })
    return result


async def browser_session_info(session_id: str = "default") -> dict:
    """
    Bir session hakkında detaylı bilgi döndür.
    Bellekte aktif mi, URL'si, title'ı, kayıtlı state var mı.
    """
    storage_path = _get_storage_state_path(session_id)
    saved = storage_path.exists()
    saved_size = storage_path.stat().st_size if saved else 0

    async with _session_store.lock:
        sess = _session_store.get(session_id)

    if not sess:
        return {
            "session_id": session_id,
            "active": False,
            "url": None,
            "title": None,
            "saved_state": saved,
            "saved_size_bytes": saved_size,
        }

    page = sess["page"]
    try:
        url = page.url
        title = await page.title()
    except Exception:
        url = "(bilinmiyor)"
        title = "(bilinmiyor)"

    return {
        "session_id": session_id,
        "active": True,
        "url": url,
        "title": title,
        "saved_state": saved,
        "saved_size_bytes": saved_size,
    }


# ── BROWSER-1: Ek DOM-first aksiyonlar ──────────────────────────────────────


async def browser_select_option(
    selector: str,
    value: str | None = None,
    label: str | None = None,
    index: int | None = None,
    session_id: str = "default",
    headless: bool = True,
    timeout: int = 10_000,
) -> tuple[bool, str]:
    """
    ``<select>`` elementinde seçim yap.
    Üç yoldan biriyle: value, label veya index.
    """
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        loc = _make_locator(sess["page"], selector)
        if value is not None:
            await loc.select_option(value=value, timeout=timeout)
        elif label is not None:
            await loc.select_option(label=label, timeout=timeout)
        elif index is not None:
            await loc.select_option(index=index, timeout=timeout)
        else:
            return False, "❌ select_option için value, label veya index gerekli."
        logger.info("browser/select_option: selector=%r (session=%r)", selector, session_id)
        return True, f"✅ Seçim yapıldı: {selector}"
    except Exception as e:
        logger.warning("browser/select_option hata: selector=%r, %s", selector, e)
        return False, f"❌ Seçim yapılamadı ({selector}): {e}"


async def browser_check(
    selector: str,
    checked: bool = True,
    session_id: str = "default",
    headless: bool = True,
    timeout: int = 10_000,
) -> tuple[bool, str]:
    """Checkbox işaretle veya kaldır."""
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        loc = _make_locator(sess["page"], selector)
        if checked:
            await loc.check(timeout=timeout)
        else:
            await loc.uncheck(timeout=timeout)
        logger.info("browser/check: selector=%r checked=%s (session=%r)", selector, checked, session_id)
        return True, f"✅ Checkbox {'işaretlendi' if checked else 'kaldırıldı'}: {selector}"
    except Exception as e:
        logger.warning("browser/check hata: selector=%r, %s", selector, e)
        return False, f"❌ Checkbox değiştirilemedi ({selector}): {e}"


async def browser_type(
    selector: str,
    text: str,
    delay: int = 0,
    session_id: str = "default",
    headless: bool = True,
    timeout: int = 10_000,
) -> tuple[bool, str]:
    """
    Karakter karakter yazma (fill'den farklı — keydown/keyup event'leri tetikler).
    Autocomplete veya JS event listener'lara bağlı formlar için gerekli.
    delay: ms cinsinden tuşlar arası bekleme.
    """
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        loc = _make_locator(sess["page"], selector)
        await loc.type(text, delay=delay, timeout=timeout)
        logger.info("browser/type: selector=%r len=%d (session=%r)", selector, len(text), session_id)
        return True, f"✅ Metin yazıldı: {selector}"
    except Exception as e:
        logger.warning("browser/type hata: selector=%r, %s", selector, e)
        return False, f"❌ Metin yazılamadı ({selector}): {e}"


async def browser_press(
    key: str,
    session_id: str = "default",
    headless: bool = True,
) -> tuple[bool, str]:
    """
    Klavye tuşu/kombinasyonu gönder (sayfa düzeyinde).
    Örnekler: "Enter", "Tab", "Escape", "Control+a", "ArrowDown"
    """
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        await sess["page"].keyboard.press(key)
        logger.info("browser/press: key=%r (session=%r)", key, session_id)
        return True, f"✅ Tuş gönderildi: {key}"
    except Exception as e:
        logger.warning("browser/press hata: key=%r, %s", key, e)
        return False, f"❌ Tuş gönderilemedi ({key}): {e}"


async def browser_hover(
    selector: str,
    session_id: str = "default",
    headless: bool = True,
    timeout: int = 10_000,
) -> tuple[bool, str]:
    """Element üzerine fare ile gel (hover). Dropdown menüler için yararlı."""
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        loc = _make_locator(sess["page"], selector)
        await loc.hover(timeout=timeout)
        logger.info("browser/hover: selector=%r (session=%r)", selector, session_id)
        return True, f"✅ Hover: {selector}"
    except Exception as e:
        logger.warning("browser/hover hata: selector=%r, %s", selector, e)
        return False, f"❌ Hover başarısız ({selector}): {e}"


async def browser_get_attribute(
    selector: str,
    attribute: str,
    session_id: str = "default",
    headless: bool = True,
    timeout: int = 10_000,
) -> tuple[bool, str, Optional[str]]:
    """Element attribute değerini al (href, src, class, data-* vb.)."""
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        loc = _make_locator(sess["page"], selector)
        val = await loc.get_attribute(attribute, timeout=timeout)
        logger.info(
            "browser/get_attribute: selector=%r attr=%r val=%r (session=%r)",
            selector, attribute, (val[:60] + "…") if val and len(val) > 60 else val, session_id,
        )
        return True, f"✅ Attribute alındı: {attribute}", val
    except Exception as e:
        logger.warning("browser/get_attribute hata: selector=%r attr=%r, %s", selector, attribute, e)
        return False, f"❌ Attribute alınamadı ({selector}@{attribute}): {e}", None


async def browser_scroll(
    direction: str = "down",
    amount: int = 500,
    selector: str | None = None,
    session_id: str = "default",
    headless: bool = True,
) -> tuple[bool, str]:
    """
    Sayfa veya element scroll.
    direction: "up" | "down" | "left" | "right"
    amount: piksel cinsinden scroll miktarı.
    selector: belirtilirse o element scroll edilir; yoksa sayfa.
    """
    _deltas = {
        "down":  (0, amount),
        "up":    (0, -amount),
        "right": (amount, 0),
        "left":  (-amount, 0),
    }
    if direction not in _deltas:
        return False, f"❌ Geçersiz direction: {direction!r}. Geçerliler: up, down, left, right"
    dx, dy = _deltas[direction]
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        page = sess["page"]
        if selector:
            loc = _make_locator(page, selector)
            await loc.evaluate(f"el => el.scrollBy({dx}, {dy})")
        else:
            await page.evaluate(f"window.scrollBy({dx}, {dy})")
        logger.info(
            "browser/scroll: direction=%s amount=%d selector=%r (session=%r)",
            direction, amount, selector, session_id,
        )
        return True, f"✅ Scroll: {direction} {amount}px"
    except Exception as e:
        logger.warning("browser/scroll hata: %s", e)
        return False, f"❌ Scroll başarısız: {e}"


async def browser_get_url(
    session_id: str = "default",
    headless: bool = True,
) -> tuple[bool, str, Optional[str]]:
    """Mevcut sayfanın URL'sini döndür (redirect kontrolü için)."""
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        url = sess["page"].url
        logger.info("browser/get_url: %s (session=%r)", url, session_id)
        return True, "✅ URL alındı.", url
    except Exception as e:
        logger.warning("browser/get_url hata: %s", e)
        return False, f"❌ URL alınamadı: {e}", None


# ── Shutdown hook (registry tarafından çağrılır) ────────────────────────────

async def lifecycle_shutdown() -> None:
    try:
        await browser_close_all()
    except Exception as exc:
        logger.warning("Browser session kapatma hatası: %s", exc)


