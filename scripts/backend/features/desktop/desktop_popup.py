"""
DESK-OPT-8 — X11 MapNotify tabanlı popup izleyici.

Polling döngüsü yerine SubstructureNotifyMask ile root pencereye kayıt:
  - MapNotify → yeni pencere belirdi
  - WM_CLASS eşleşiyorsa → _NET_CLOSE_WINDOW (önce) / window.destroy() (fallback)
  - ~0ms gecikme, CPU harcanmaz (select + 200ms timeout)

Public API:
    start_watch_popup(wm_class_patterns, timeout_s, watcher_id) -> (ok, msg, watcher_id)
    stop_watch_popup(watcher_id) -> (ok, msg)
    list_watch_popups() -> list[dict]
"""
from __future__ import annotations

import asyncio
import logging
import os
import select
import threading
import time
import uuid
from typing import Optional

from .desktop_common import _detect_display, _detect_xauthority

logger = logging.getLogger(__name__)

# ── Aktif izleyici tablosu ────────────────────────────────────────────
# watcher_id → {"thread": Thread, "stop": Event, "patterns": list[str], "started_at": float}
_watchers: dict[str, dict] = {}
_watchers_lock = threading.Lock()


# ── Sync çekirdek (ayrı thread'de çalışır) ───────────────────────────

def _watch_popup_sync(
    wm_class_patterns: list[str],
    timeout_s: float,
    stop_event: threading.Event,
    display_str: str,
    xauth: str,
    watcher_id: str,
) -> None:
    """
    X11 root pencereye SubstructureNotifyMask ile kayıt olur.

    MapNotify geldiğinde pencere WM_CLASS'ını kontrol eder;
    eşleşirse önce _NET_CLOSE_WINDOW ile kapatmayı dener,
    başarısız olursa window.destroy() kullanır.

    Bu fonksiyon bloklayıcıdır; daemon thread'de çalışır.
    stop_event set edildiğinde veya timeout dolduğunda çıkar.

    Args:
        wm_class_patterns: Büyük-küçük harf duyarsız WM_CLASS arama kalıpları.
        timeout_s:          Maksimum izleme süresi (saniye).
        stop_event:         Dışarıdan durdurma sinyali.
        display_str:        DISPLAY değeri (ör. ":0").
        xauth:              XAUTHORITY dosya yolu.
        watcher_id:         Log/izleme için benzersiz ID.
    """
    if xauth:
        os.environ["XAUTHORITY"] = xauth  # XAUTHORITY python-xlib'e API ile geçirilemiyor

    try:
        from Xlib import display as xdisplay, X  # noqa: PLC0415
        from Xlib.protocol import event as xevent  # noqa: PLC0415
    except ImportError:
        logger.error("watch_popup[%s]: python-xlib yüklenemedi", watcher_id)
        return

    try:
        d = xdisplay.Display(display_str or None)
    except Exception as exc:
        logger.error("watch_popup[%s]: Display() açılamadı: %s", watcher_id, exc)
        return

    try:
        screen = d.screen()
        root = screen.root

        # Yalnızca bu istemcinin event maskesi etkilenir — diğer istemciler (WM) etkilenmez
        root.change_attributes(event_mask=X.SubstructureNotifyMask)
        d.flush()
        logger.info(
            "watch_popup[%s]: izleme başladı patterns=%s timeout=%.0fs",
            watcher_id, wm_class_patterns, timeout_s,
        )

        fd = d.fileno()
        deadline = time.monotonic() + timeout_s
        closed_count = 0

        while not stop_event.is_set() and time.monotonic() < deadline:
            # select ile 200ms blok — CPU harcamaz, stop_event'i düzenli kontrol eder
            try:
                readable, _, _ = select.select([fd], [], [], 0.2)
            except Exception:
                break
            if not readable:
                continue

            # Bekleyen olayları tüket
            while d.pending_events() > 0:
                try:
                    ev = d.next_event()
                except Exception:
                    break

                if ev.type != X.MapNotify:
                    continue

                win = ev.window

                # WM_CLASS kontrolü
                try:
                    wm_class = win.get_wm_class()  # (instance_name, class_name) veya None
                except Exception:
                    continue

                if wm_class is None:
                    continue

                # Eşleşme: instance veya class adı kalıplardan birini içeriyorsa
                wm_str = " ".join(str(s).lower() for s in wm_class if s)
                patterns_lower = [p.lower() for p in wm_class_patterns]
                if not any(p in wm_str for p in patterns_lower):
                    continue

                logger.info(
                    "watch_popup[%s]: eşleşme — wm_class=%s, kapatılıyor…",
                    watcher_id, wm_class,
                )

                # 1. _NET_CLOSE_WINDOW — WM aracılığıyla nazik kapatma
                closed = False
                try:
                    net_close = d.intern_atom("_NET_CLOSE_WINDOW")
                    close_ev = xevent.ClientMessage(
                        window=win,
                        client_type=net_close,
                        data=(32, [X.CurrentTime, 2, 0, 0, 0]),
                    )
                    mask = X.SubstructureRedirectMask | X.SubstructureNotifyMask
                    root.send_event(close_ev, event_mask=mask)
                    d.flush()
                    closed = True
                    logger.debug(
                        "watch_popup[%s]: _NET_CLOSE_WINDOW gönderildi wm_class=%s",
                        watcher_id, wm_class,
                    )
                except Exception as exc:
                    logger.debug(
                        "watch_popup[%s]: _NET_CLOSE_WINDOW başarısız (%s); destroy'a geçiliyor",
                        watcher_id, exc,
                    )

                # 2. window.destroy() — zorunlu kapatma (fallback)
                if not closed:
                    try:
                        win.destroy()
                        d.flush()
                        logger.debug(
                            "watch_popup[%s]: window.destroy() çalıştı wm_class=%s",
                            watcher_id, wm_class,
                        )
                    except Exception as exc:
                        logger.warning(
                            "watch_popup[%s]: destroy başarısız wm_class=%s: %s",
                            watcher_id, wm_class, exc,
                        )

                closed_count += 1

    finally:
        # Yalnızca bu istemcinin maskesini sıfırla
        try:
            root.change_attributes(event_mask=0)
            d.flush()
        except Exception:
            pass
        try:
            d.close()
        except Exception:
            pass

        with _watchers_lock:
            _watchers.pop(watcher_id, None)

        logger.info(
            "watch_popup[%s]: izleme sona erdi (kapatılan=%d)",
            watcher_id, closed_count,
        )


# ── Async public API ──────────────────────────────────────────────────

async def start_watch_popup(
    wm_class_patterns: list[str],
    timeout_s: float = 30.0,
    watcher_id: Optional[str] = None,
) -> tuple[bool, str, str]:
    """
    X11 MapNotify izleyiciyi arka planda başlatır.

    Args:
        wm_class_patterns: WM_CLASS için arama kalıpları (büyük-küçük harf duyarsız).
                           Boş liste tüm yeni pencereleri kapatır — dikkatli kullanın.
        timeout_s:         Otomatik durdurma süresi (saniye, 1–600). Varsayılan 30.
        watcher_id:        İsteğe bağlı ID; belirtilmezse UUID üretilir.

    Döner: (ok, mesaj, watcher_id)
    """
    if not (1.0 <= timeout_s <= 600.0):
        return False, "timeout_s 1–600 arasında olmalı.", ""

    if not wm_class_patterns:
        return (
            False,
            "wm_class en az bir kalıp içermeli. "
            "Boş liste tüm pencereleri kapatacağından izin verilmez.",
            "",
        )

    try:
        from Xlib import display as xdisplay  # noqa: PLC0415 — import kontrolü
        _ = xdisplay
    except ImportError:
        return (
            False,
            "python-xlib yüklü değil. "
            "`pip install python-xlib` ile yükleyin.",
            "",
        )

    _id = watcher_id or str(uuid.uuid4())[:8]

    with _watchers_lock:
        if _id in _watchers:
            return False, f"'{_id}' ID'li izleyici zaten çalışıyor.", _id

    stop_event = threading.Event()
    display_str = _detect_display()
    xauth = _detect_xauthority()

    thread = threading.Thread(
        target=_watch_popup_sync,
        args=(wm_class_patterns, timeout_s, stop_event, display_str, xauth, _id),
        daemon=True,
        name=f"popup-watcher-{_id}",
    )

    with _watchers_lock:
        _watchers[_id] = {
            "thread": thread,
            "stop": stop_event,
            "patterns": list(wm_class_patterns),
            "started_at": time.time(),
            "timeout_s": timeout_s,
        }

    thread.start()
    logger.info("start_watch_popup: id=%s patterns=%s timeout=%.0fs", _id, wm_class_patterns, timeout_s)
    return (
        True,
        f"✅ Popup izleyici başlatıldı (id={_id}, patterns={wm_class_patterns}, timeout={timeout_s:.0f}s).",
        _id,
    )


async def stop_watch_popup(watcher_id: str) -> tuple[bool, str]:
    """
    Çalışan popup izleyiciyi durdurur.

    Args:
        watcher_id: start_watch_popup'tan dönen ID.

    Döner: (ok, mesaj)
    """
    with _watchers_lock:
        entry = _watchers.get(watcher_id)

    if entry is None:
        return False, f"'{watcher_id}' ID'li aktif izleyici bulunamadı."

    entry["stop"].set()

    # Thread'in bitmesini kısa süre bekle (non-blocking — asyncio thread'ini bloklamaz)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: entry["thread"].join(timeout=1.5))

    with _watchers_lock:
        _watchers.pop(watcher_id, None)

    logger.info("stop_watch_popup: id=%s durduruldu", watcher_id)
    return True, f"✅ Popup izleyici durduruldu (id={watcher_id})."


def list_watch_popups() -> list[dict]:
    """
    Aktif popup izleyicileri listeler.

    Döner: Her izleyici için {"id", "patterns", "started_at", "timeout_s", "elapsed_s"} dict'leri.
    """
    now = time.time()
    with _watchers_lock:
        return [
            {
                "id": wid,
                "patterns": entry["patterns"],
                "started_at": entry["started_at"],
                "timeout_s": entry["timeout_s"],
                "elapsed_s": round(now - entry["started_at"], 1),
                "alive": entry["thread"].is_alive(),
            }
            for wid, entry in _watchers.items()
        ]
