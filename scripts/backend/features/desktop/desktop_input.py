"""
Desktop klavye / fare giriş modülü — XTEST (python-xlib) öncelikli kullanıcı girdisi.

Public API:
    xdotool_type(text, delay_ms) -> str
    xdotool_key(key) -> str
    xdotool_click(x, y, button) -> str
    xdotool_move(x, y) -> str
    xdotool_scroll(direction, amount) -> str
    net_active_window(wid_int) -> tuple[bool, str]

DESK-OPT-2: xdotool_type() artık subprocess yerine python-xlib XTEST kullanır.
Faydaları:
  - fork/exec overhead yok → hız artışı
  - Türkçe/Unicode karakterlerde X server donması yok
  - --clearmodifiers senkronizasyon maliyeti yok
xdotool fallback: python-xlib yoksa veya XTEST extension eksikse otomatik devreye girer.

DESK-OPT-6: net_active_window() — python-xlib ile root pencereye _NET_ACTIVE_WINDOW
ClientMessage + SubstructureRedirectMask gönderir. Modern pencere yöneticileri
(Mutter/KWin) odak çalma koruması uyguladığında xdotool windowfocus sessizce
başarısız olabilir; bu yol pencere yöneticisine EWMH odak isteği iletir.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from .desktop_common import (
    _SCROLL_BUTTON,
    _detect_display,
    _detect_xauthority,
    _validate_key,
    _xdotool,
    _xdotool_available,
    x11_lock,
)

logger = logging.getLogger(__name__)

# ── python-xlib XTEST yardımcıları (DESK-OPT-2) ─────────────────────────

_xlib_import_ok: bool | None = None  # None = henüz denenmedi


def _xlib_type_available() -> bool:
    """python-xlib ve Xlib.ext.xtest import edilebilir mi?"""
    global _xlib_import_ok
    if _xlib_import_ok is None:
        try:
            from Xlib import display as _d, X as _X  # noqa: F401
            from Xlib.ext import xtest as _xt  # noqa: F401
            _xlib_import_ok = True
        except ImportError:
            _xlib_import_ok = False
    return _xlib_import_ok


def _char_to_keysym(char: str) -> int:
    """
    Tek karakteri X11 keysym değerine çevirir.

    Kural:
      - ASCII 0x20-0x7E → keysym = codepoint (X11 legacy form)
      - Latin-1 0xA0-0xFF → keysym = codepoint (X11 legacy form)
      - Geri kalanlar (ğ, ş, İ, ı ...) → keysym = 0x01000000 | codepoint (Unicode form)
    """
    cp = ord(char)
    if (0x20 <= cp <= 0x7E) or (0xA0 <= cp <= 0xFF):
        return cp
    return 0x01000000 | cp


def _find_scratch_keycode(d) -> int:
    """
    Hiçbir keysym'e eşlenmemiş boş bir keycode bulur (geçici remap için).
    Yüksek keycode aralığı (243-253) taranır; bulunamazsa 243 döner.
    """
    try:
        keymap = d.get_keyboard_mapping(8, 248)  # keycode 8..255
        for i in range(243, 254):
            idx = i - 8
            if idx < len(keymap) and all(s == 0 for s in keymap[idx]):
                return i
    except Exception:
        pass
    return 243


def _xlib_type_sync(text: str, delay_ms: int, display_str: str, xauth: str) -> tuple[bool, str]:
    """
    python-xlib XTEST ile in-process metin girişi.

    Subprocess yok: fork/exec overhead yok, Unicode karakterler (ğ, ş, ö, ü ...)
    X server'ı dondurmaz.

    Bu fonksiyon senkron; asyncio executor thread'inde çağrılır.
    Döner: (başarı, hata_mesajı).
    """
    if xauth:
        os.environ["XAUTHORITY"] = xauth  # XAUTHORITY python-xlib'e API ile geçirilemiyor

    try:
        from Xlib import display as xdisplay, X  # noqa: PLC0415
        from Xlib.ext import xtest as xtestmod   # noqa: PLC0415

        d = xdisplay.Display(display_str or None)
        try:
            if d.query_extension("XTEST") is None:
                return False, "XTEST extension mevcut değil"

            scratch = _find_scratch_keycode(d)
            delay_s = delay_ms / 1000.0
            # Keysym → keycode önbelleği (tekrarlı XGetKeyboardMapping önler)
            ks_cache: dict[int, int] = {}

            for char in text:
                keysym = _char_to_keysym(char)

                if keysym in ks_cache:
                    keycode = ks_cache[keysym]
                else:
                    keycode = d.keysym_to_keycode(keysym)
                    ks_cache[keysym] = keycode

                needs_remap = keycode == 0
                if needs_remap:
                    # Unicode keysym için geçici keycode tahsisi
                    d.change_keyboard_mapping(scratch, [[keysym, keysym]])
                    d.sync()
                    keycode = scratch

                xtestmod.fake_input(d, X.KeyPress, keycode)
                d.flush()
                xtestmod.fake_input(d, X.KeyRelease, keycode)
                d.flush()

                if needs_remap:
                    d.change_keyboard_mapping(scratch, [[0, 0]])
                    d.flush()

                if delay_ms > 0:
                    time.sleep(delay_s)

            d.sync()
        finally:
            d.close()

        return True, ""

    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


# ── _NET_ACTIVE_WINDOW ClientMessage (DESK-OPT-6) ────────────────────────

def _net_active_window_sync(
    wid_int: int,
    display_str: str,
    xauth: str,
) -> tuple[bool, str]:
    """
    python-xlib ile pencereye _NET_ACTIVE_WINDOW ClientMessage gönderir.

    Modern pencere yöneticileri (Mutter/KWin) focus-stealing koruması uygular;
    xdotool windowfocus/windowactivate sessizce başarısız olabilir.
    Bu fonksiyon root pencereye SubstructureRedirectMask ile EWMH isteği gönderir —
    pencere yöneticisi bunu zorunlu odak isteği olarak işler.

    Args:
        wid_int:     Pencere ID (tam sayı, ör. 0x05000003 → 83886083).
        display_str: DISPLAY değeri (ör. ":0").
        xauth:       XAUTHORITY dosya yolu (boş bırakılabilir).

    Döner: (başarı, hata_mesajı).
    Senkron; asyncio executor thread'inde çağrılır.
    """
    if xauth:
        os.environ["XAUTHORITY"] = xauth  # XAUTHORITY python-xlib'e API ile geçirilemiyor

    try:
        from Xlib import display as xdisplay, X  # noqa: PLC0415
        from Xlib.protocol import event as xevent  # noqa: PLC0415

        d = xdisplay.Display(display_str or None)
        try:
            screen = d.screen()
            root = screen.root

            net_active_window = d.intern_atom("_NET_ACTIVE_WINDOW")
            target = d.create_resource_object("window", wid_int)

            ev = xevent.ClientMessage(
                window=target,
                client_type=net_active_window,
                data=(32, [
                    1,  # source indication: 1 = application, 2 = pager
                    X.CurrentTime,  # timestamp (0 = use current server time)
                    0,  # currently active window (0 = none / unknown)
                    0,
                    0,
                ]),
            )
            mask = X.SubstructureRedirectMask | X.SubstructureNotifyMask
            root.send_event(ev, event_mask=mask)
            d.sync()
        finally:
            d.close()

        return True, ""

    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


async def net_active_window(wid_int: int) -> tuple[bool, str]:
    """
    _NET_ACTIVE_WINDOW ClientMessage'ı asyncio-uyumlu şekilde gönderir.

    Args:
        wid_int: Pencere ID (tam sayı).

    Döner: (başarı, hata_mesajı).
    python-xlib import edilemiyorsa (False, hata) döner.
    """
    if not _xlib_type_available():
        return False, "python-xlib mevcut değil"

    display_str = _detect_display()
    xauth = _detect_xauthority()
    loop = asyncio.get_event_loop()
    async with x11_lock:
        ok, err = await loop.run_in_executor(
            None, _net_active_window_sync, wid_int, display_str, xauth
        )
    if ok:
        logger.info("_NET_ACTIVE_WINDOW: pencere %#x odaklandı", wid_int)
    else:
        logger.debug("_NET_ACTIVE_WINDOW başarısız (%s)", err)
    return ok, err


# ── Public API ────────────────────────────────────────────────────────────

async def xdotool_type(text: str, delay_ms: int = 12, window_id: str | None = None) -> str:
    """
    Metin yazar.

    window_id verilirse xdotool type --window ile hedefli yazma yapılır —
    kullanıcı başka bir pencereye geçse bile metin doğru yere gider.
    window_id verilmezse o an klavye odağındaki pencereye yazar (güvensiz).

    Args:
        text: Yazılacak metin.
        delay_ms: Tuşlar arası gecikme (ms). Varsayılan 12ms.
        window_id: Hedef pencere ID (hex ör. "0x05000003"). None → aktif pencere.

    Döner: Durum mesajı.
    """
    if not text:
        return "❌ Yazılacak metin boş olamaz."
    if len(text) > 2000:
        return "❌ Metin çok uzun (max 2000 karakter)."

    preview = text[:60] + ("…" if len(text) > 60 else "")

    # ── window_id verilmişse: xdotool --window ile hedefli yaz ───────────
    # XTEST odak bağımlıdır; pencere hedeflemesi için xdotool zorunlu.
    if window_id:
        if not _xdotool_available():
            return "❌ window_id ile hedefli yazma için xdotool gerekli. `sudo apt install xdotool` çalıştır."
        async with x11_lock:
            code, err = await _xdotool(
                "type", "--window", window_id,
                "--clearmodifiers", "--delay", str(delay_ms), "--", text,
            )
        if code == 0:
            logger.info("xdotool type --window %s: %d karakter yazıldı", window_id, len(text))
            return f"✅ Metin yazıldı (pencere {window_id}): {preview!r}"
        return f"❌ xdotool type --window başarısız (kod {code}): {err}"

    # ── window_id yok: XTEST (hızlı, Unicode) → xdotool fallback ─────────
    if _xlib_type_available():
        display_str = _detect_display()
        xauth = _detect_xauthority()
        loop = asyncio.get_event_loop()
        async with x11_lock:
            ok, err = await loop.run_in_executor(
                None, _xlib_type_sync, text, delay_ms, display_str, xauth
            )
        if ok:
            logger.info("xlib XTEST type: %d karakter yazıldı", len(text))
            return f"✅ Metin yazıldı: {preview!r}"
        logger.warning("xlib XTEST type başarısız (%s); xdotool'a düşülüyor", err)

    if not _xdotool_available():
        return (
            "❌ Metin girilemedi: python-xlib XTEST başarısız ve "
            "xdotool kurulu değil. `sudo apt install xdotool` çalıştır."
        )

    async with x11_lock:
        code, err = await _xdotool(
            "type", "--clearmodifiers", "--delay", str(delay_ms), "--", text
        )
    if code == 0:
        logger.info("xdotool type (fallback): %d karakter yazıldı", len(text))
        return f"✅ Metin yazıldı: {preview!r}"
    return f"❌ xdotool type başarısız (kod {code}): {err}"


async def xdotool_key(key: str) -> str:
    """
    Tuş veya tuş kombinasyonu gönderir (xdotool key).

    Args:
        key: Tuş adı — ör. "ctrl+c", "Return", "alt+F4", "super+l".

    Döner: Durum mesajı.
    """
    if not _xdotool_available():
        return "❌ xdotool kurulu değil. `sudo apt install xdotool` çalıştır."
    if not _validate_key(key):
        return (
            f"❌ Geçersiz tuş adı: {key!r}\n"
            "İzin verilenler: harf, rakam, +, -, _, boşluk (max 64 karakter).\n"
            "Örnek: 'ctrl+c', 'Return', 'alt+F4', 'super+l'"
        )

    async with x11_lock:
        code, err = await _xdotool("key", "--clearmodifiers", key)
    if code == 0:
        logger.info("xdotool key: %s", key)
        return f"✅ Tuş basıldı: {key}"
    return f"❌ xdotool key başarısız (kod {code}): {err}"


async def xdotool_click(x: int, y: int, button: int = 1) -> str:
    """
    Verilen koordinata fareyi taşır ve tıklar (xdotool mousemove + click).

    Args:
        x, y: Ekran koordinatları (piksel).
        button: 1=sol, 2=orta, 3=sağ. Varsayılan 1.

    Döner: Durum mesajı.
    """
    if not _xdotool_available():
        return "❌ xdotool kurulu değil. `sudo apt install xdotool` çalıştır."
    if button not in (1, 2, 3):
        return "❌ button 1 (sol), 2 (orta) veya 3 (sağ) olmalı."
    if not (0 <= x <= 9999 and 0 <= y <= 9999):
        return "❌ Koordinatlar 0–9999 arasında olmalı."

    # mousemove + click atomik olmalı: aralarda başka coroutine fareyi
    # kaydırmasın diye ikisi birlikte tek lock altında çalıştırılır.
    async with x11_lock:
        move_code, move_err = await _xdotool("mousemove", "--sync", str(x), str(y))
        if move_code != 0:
            return f"❌ Fare taşıma başarısız (kod {move_code}): {move_err}"
        click_code, click_err = await _xdotool("click", str(button))
    if click_code == 0:
        btn_name = {1: "sol", 2: "orta", 3: "sağ"}[button]
        logger.info("xdotool click: (%d, %d) button=%d", x, y, button)
        return f"✅ {btn_name.capitalize()} tıklandı: ({x}, {y})"
    return f"❌ xdotool click başarısız (kod {click_code}): {click_err}"


async def xdotool_move(x: int, y: int) -> str:
    """
    Fareyi verilen koordinata taşır (xdotool mousemove).

    Args:
        x, y: Ekran koordinatları (piksel).

    Döner: Durum mesajı.
    """
    if not _xdotool_available():
        return "❌ xdotool kurulu değil. `sudo apt install xdotool` çalıştır."
    if not (0 <= x <= 9999 and 0 <= y <= 9999):
        return "❌ Koordinatlar 0–9999 arasında olmalı."

    async with x11_lock:
        code, err = await _xdotool("mousemove", "--sync", str(x), str(y))
    if code == 0:
        logger.info("xdotool move: (%d, %d)", x, y)
        return f"✅ Fare taşındı: ({x}, {y})"
    return f"❌ xdotool mousemove başarısız (kod {code}): {err}"


async def xdotool_scroll(direction: str, amount: int = 3) -> str:
    """
    Fare tekerleği scroll yapar (xdotool click button 4/5/6/7).

    Args:
        direction: "up", "down", "left", "right".
        amount: Kaç adım scroll yapılacak (1–20). Varsayılan 3.

    Döner: Durum mesajı.
    """
    if not _xdotool_available():
        return "❌ xdotool kurulu değil. `sudo apt install xdotool` çalıştır."

    button = _SCROLL_BUTTON.get(direction.lower())
    if button is None:
        return (
            f"❌ Geçersiz yön: {direction!r}\n"
            "Geçerliler: up, down, left, right"
        )
    if not (1 <= amount <= 20):
        return "❌ amount 1–20 arasında olmalı."

    # amount kadar tekrarlı click
    args = ["click", "--repeat", str(amount), "--delay", "50", button]
    async with x11_lock:
        code, err = await _xdotool(*args)
    if code == 0:
        logger.info("xdotool scroll: %s × %d", direction, amount)
        return f"✅ Scroll: {direction} × {amount}"
    return f"❌ xdotool scroll başarısız (kod {code}): {err}"
