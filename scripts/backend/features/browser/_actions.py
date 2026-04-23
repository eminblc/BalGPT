"""Playwright aksiyonları — goto, fill, click, screenshot ve diğerleri (SRP).

Sorumluluk: Kullanıcı talep eden aksiyonları Playwright API üzerinden gerçekleştirmek.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import tempfile
from pathlib import Path
from typing import Optional

from ._lifecycle import _get_or_create_session
from ._validation import _validate_url, _check_sensitive_navigation, _make_locator

logger = logging.getLogger(__name__)

_RISKY_JS_PATTERNS = ("fetch(", "XMLHttpRequest", "window.open", "document.write", "eval(")


async def browser_goto(
    url: str,
    session_id: str = "default",
    headless: bool = True,
    timeout: int = 30_000,
    wait_until: str = "domcontentloaded",
) -> tuple[bool, str]:
    """URL'ye git. wait_until: domcontentloaded | load | commit (networkidle kullanma)."""
    err = _validate_url(url)
    if err:
        logger.warning("browser/goto: URL reddedildi: %s → %s", url, err)
        return False, f"❌ {err}"
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        page = sess["page"]
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
    """CSS/XPath selector ile input alanını doldur."""
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
    """CSS/XPath selector ile elemente tıkla."""
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
    """Mevcut sayfanın ekran görüntüsünü al. Döner: (ok, mesaj, base64_png_or_none)"""
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        page = sess["page"]
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name
        await page.screenshot(path=tmp_path, full_page=full_page)
        raw = Path(tmp_path).read_bytes()
        Path(tmp_path).unlink(missing_ok=True)
        b64 = base64.b64encode(raw).decode()
        logger.info("browser/screenshot: %d bytes, session=%r", len(raw), session_id)
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
    """Elementin görünür metin içeriğini döndür. Selector boş → tüm sayfa metni."""
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
    """Element belirli duruma gelene kadar bekle. state: attached | detached | visible | hidden"""
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


async def browser_eval(
    script: str,
    session_id: str = "default",
    headless: bool = True,
) -> tuple[bool, str, Optional[str]]:
    """Sayfada JavaScript çalıştır. Yalnızca localhost'tan erişilebilir."""
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
    """CDP ile hızlı tıklama — Playwright actionability kontrollerini atlar.

    fallback=True: CDP başarısız olursa otomatik loc.click()'e düşer.
    """
    try:
        sess = await _get_or_create_session(session_id, headless=headless)
        page = sess["page"]
        context = sess["context"]
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
        cdp = await context.new_cdp_session(page)
        try:
            _mouse_event = {"x": x, "y": y, "button": "left", "clickCount": 1, "modifiers": 0}
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
                logger.info("browser/cdp_click[fallback]: selector=%r (session=%r)", selector, session_id)
                return True, f"✅ Tıklandı (fallback): {selector}"
            except Exception as e2:
                return False, f"❌ Tıklanamadı ({selector}): {e2}"
        return False, f"❌ CDP tıklama başarısız ({selector}): {e}"


async def browser_select_option(
    selector: str,
    value: str | None = None,
    label: str | None = None,
    index: int | None = None,
    session_id: str = "default",
    headless: bool = True,
    timeout: int = 10_000,
) -> tuple[bool, str]:
    """``<select>`` elementinde seçim yap. value, label veya index ile."""
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
    """Karakter karakter yazma — keydown/keyup event'leri tetikler (fill'den farklı)."""
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
    """Klavye tuşu/kombinasyonu gönder. Örnekler: Enter, Tab, Control+a, ArrowDown"""
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
    """Sayfa veya element scroll. direction: up | down | left | right"""
    _deltas = {"down": (0, amount), "up": (0, -amount), "right": (amount, 0), "left": (-amount, 0)}
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
