"""
Desktop otomasyon modülü — genel amaçlı facade.

Sorumluluk ayrımı (REFAC-4):
    desktop_common.py   — paylaşılan yardımcılar (_detect_display, _env, _xdotool*, _wmctrl)
    desktop_capture.py  — ekran görüntüsü ve OCR
    desktop_input.py    — klavye / fare girdisi (xdotool_*)
    desktop_vision.py   — Vision API sorgusu + cache (_BboxCache)
    desktop_atspi.py    — AT-SPI erişilebilirlik ağacı

Bu dosya geriye dönük uyumluluk için tüm public fonksiyonları re-export eder
ve sistem operasyonlarını (open_path, unlock_screen, sudo_exec, run_installer,
get_windows, focus_window) barındırır.

Kullanım:
    from backend.features.desktop import (
        open_path, run_installer, capture_screen, ocr_screen,
        xdotool_type, xdotool_key, xdotool_click, xdotool_move, xdotool_scroll,
        vision_query, get_windows, focus_window,
    )

Gereksinimler (sistem paketleri):
    sudo apt install scrot tesseract-ocr tesseract-ocr-tur xdg-utils xdotool wmctrl
    sudo apt install wine  # .exe dosyaları için (isteğe bağlı)

DISPLAY ayarı:
    X11 oturumu için DISPLAY=:0 gerekir.
    SSH üzerinden çalışıyorsan: DISPLAY=:0 ayarlı olmalı.
    Headless/Wayland: scrot ve xdotool çalışmaz — Xvfb gerekir.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional

from .desktop_common import (
    _detect_display, _env, _wmctrl, _xdotool, _xdotool_available,
    is_screen_locked, x11_lock,
)

# ── Private imports (thin wrapper'lar bu adları kullanır) ─────────────
from .desktop_capture import (
    capture_screen as _capture_screen,
    capture_screen_base64_fast as _capture_screen_base64_fast,
    capture_all_monitors as _capture_all_monitors,
    list_monitors as _list_monitors,
    ocr_screen as _ocr_screen,
    run_tesseract_on_file as _run_tesseract_on_file,
)
from .desktop_input import (
    net_active_window as _net_active_window,
    xdotool_click as _xdotool_click,
    xdotool_key as _xdotool_key,
    xdotool_move as _xdotool_move,
    xdotool_scroll as _xdotool_scroll,
    xdotool_type as _xdotool_type,
)
from .desktop_vision import (
    _bbox_cache_key,  # private yardımcı — doğrudan re-export
    check_vision_status as _check_vision_status,
    clear_bbox_cache as _clear_bbox_cache,
    get_bbox_cache_stats as _get_bbox_cache_stats,
    is_vision_available as _is_vision_available,
    vision_query as _vision_query,
)
from .desktop_atspi import (
    atspi_activate_element as _atspi_activate_element,
    atspi_find_element as _atspi_find_element,
    atspi_get_desktop_tree as _atspi_get_desktop_tree,
)
from .desktop_popup import (
    start_watch_popup as _start_watch_popup,
    stop_watch_popup as _stop_watch_popup,
    list_watch_popups as _list_watch_popups,
)

__all__ = [
    # Capture
    "capture_screen",
    "capture_screen_base64_fast",
    "capture_all_monitors",
    "list_monitors",
    "ocr_screen",
    "run_tesseract_on_file",
    # Input
    "xdotool_type",
    "xdotool_key",
    "xdotool_click",
    "xdotool_move",
    "xdotool_scroll",
    # Vision
    "vision_query",
    "is_vision_available",
    "check_vision_status",
    "clear_bbox_cache",
    "get_bbox_cache_stats",
    # AT-SPI
    "atspi_get_desktop_tree",
    "atspi_find_element",
    "atspi_activate_element",
    # System ops (bu dosya)
    "open_path",
    "unlock_screen",
    "sudo_exec",
    "run_installer",
    "get_windows",
    "focus_window",
    # Popup yönetimi (DESK-OPT-8)
    "start_watch_popup",
    "stop_watch_popup",
    "list_watch_popups",
]

logger = logging.getLogger(__name__)


# ── Thin Wrappers — Capture ───────────────────────────────────────────
# Her wrapper: DEBUG log girişi + Exception yakalama + ERROR log + güvenli fallback (ENC-V3)

async def capture_screen(
    output_path: Optional[str] = None,
    region: Optional[tuple[int, int, int, int]] = None,
) -> Optional[Path]:
    """Ekran görüntüsü al. Başarısızsa None döner."""
    logger.debug("desktop.capture_screen: output_path=%s region=%s", output_path, region)
    try:
        return await _capture_screen(output_path=output_path, region=region)
    except Exception as exc:
        logger.error("capture_screen hatası: %s", exc, exc_info=True)
        return None


async def capture_screen_base64_fast(
    region: Optional[tuple[int, int, int, int]] = None,
) -> Optional[str]:
    """Ekran görüntüsünü Base64 olarak döndür (disk I/O yok). Başarısızsa None döner."""
    logger.debug("desktop.capture_screen_base64_fast: region=%s", region)
    try:
        return await _capture_screen_base64_fast(region=region)
    except Exception as exc:
        logger.error("capture_screen_base64_fast hatası: %s", exc, exc_info=True)
        return None


async def capture_all_monitors(
    output_dir: Optional[str] = None,
) -> list[tuple[str, "Path"]]:
    """Her monitör için ayrı ekran görüntüsü al. Başarısızsa [] döner."""
    logger.debug("desktop.capture_all_monitors: output_dir=%s", output_dir)
    try:
        return await _capture_all_monitors(output_dir=output_dir)
    except Exception as exc:
        logger.error("capture_all_monitors hatası: %s", exc, exc_info=True)
        return []


async def list_monitors() -> list[dict]:
    """Monitör listesini döndür. Başarısızsa [] döner."""
    logger.debug("desktop.list_monitors called")
    try:
        return await _list_monitors()
    except Exception as exc:
        logger.error("list_monitors hatası: %s", exc, exc_info=True)
        return []


async def ocr_screen() -> str:
    """Ekrandan OCR metni çıkar. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.ocr_screen called")
    try:
        return await _ocr_screen()
    except Exception as exc:
        logger.error("ocr_screen hatası: %s", exc, exc_info=True)
        return f"❌ ocr_screen hatası: {exc}"


async def run_tesseract_on_file(image_path: str) -> str:
    """Dosya üzerinde Tesseract OCR çalıştır. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.run_tesseract_on_file: image_path=%s", image_path)
    try:
        return await _run_tesseract_on_file(image_path)
    except Exception as exc:
        logger.error("run_tesseract_on_file hatası: %s", exc, exc_info=True)
        return f"❌ run_tesseract_on_file hatası: {exc}"


# ── Thin Wrappers — Input ─────────────────────────────────────────────

async def xdotool_type(text: str, delay_ms: int = 12) -> str:
    """Aktif pencereye metin yaz. Başarısızsa hata mesajı döner."""
    # text loglanmaz — gizlilik
    logger.debug("desktop.xdotool_type: %d karakter, delay_ms=%d", len(text), delay_ms)
    try:
        return await _xdotool_type(text=text, delay_ms=delay_ms)
    except Exception as exc:
        logger.error("xdotool_type hatası: %s", exc, exc_info=True)
        return f"❌ xdotool_type hatası: {exc}"


async def xdotool_key(key: str) -> str:
    """Tuş/kombinasyon gönder. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.xdotool_key: key=%s", key)
    try:
        return await _xdotool_key(key=key)
    except Exception as exc:
        logger.error("xdotool_key hatası: %s", exc, exc_info=True)
        return f"❌ xdotool_key hatası: {exc}"


async def xdotool_click(x: int, y: int, button: int = 1) -> str:
    """Koordinata fare tıklaması. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.xdotool_click: x=%d y=%d button=%d", x, y, button)
    try:
        return await _xdotool_click(x=x, y=y, button=button)
    except Exception as exc:
        logger.error("xdotool_click hatası: %s", exc, exc_info=True)
        return f"❌ xdotool_click hatası: {exc}"


async def xdotool_move(x: int, y: int) -> str:
    """Fareyi koordinata taşı. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.xdotool_move: x=%d y=%d", x, y)
    try:
        return await _xdotool_move(x=x, y=y)
    except Exception as exc:
        logger.error("xdotool_move hatası: %s", exc, exc_info=True)
        return f"❌ xdotool_move hatası: {exc}"


async def xdotool_scroll(direction: str, amount: int = 3) -> str:
    """Fare tekerleği scroll. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.xdotool_scroll: direction=%s amount=%d", direction, amount)
    try:
        return await _xdotool_scroll(direction=direction, amount=amount)
    except Exception as exc:
        logger.error("xdotool_scroll hatası: %s", exc, exc_info=True)
        return f"❌ xdotool_scroll hatası: {exc}"


# ── Thin Wrappers — Vision ────────────────────────────────────────────

async def vision_query(
    question: str,
    model: str = "claude-haiku-4-5-20251001",
    region: Optional[tuple[int, int, int, int]] = None,
    use_cache: bool = True,
    session_id: Optional[str] = None,
) -> str:
    """Ekran görüntüsü + Vision API sorgusu. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.vision_query: model=%s region=%s use_cache=%s session=%s", model, region, use_cache, session_id)
    try:
        return await _vision_query(
            question=question, model=model, region=region, use_cache=use_cache, session_id=session_id,
        )
    except Exception as exc:
        logger.error("vision_query hatası: %s", exc, exc_info=True)
        return f"❌ vision_query hatası: {exc}"


def is_vision_available() -> bool:
    """Vision API (Anthropic key) mevcut mu? Görev başında proaktif kontrol için."""
    return _is_vision_available()


def check_vision_status() -> dict:
    """Vision API durumu + fallback önerisi. {"available": bool, "fallback": str|None, "message": str}"""
    return _check_vision_status()


def clear_bbox_cache() -> int:
    """Bbox cache'i temizle. Başarısızsa 0 döner."""
    logger.debug("desktop.clear_bbox_cache called")
    try:
        return _clear_bbox_cache()
    except Exception as exc:
        logger.error("clear_bbox_cache hatası: %s", exc, exc_info=True)
        return 0


def get_bbox_cache_stats() -> dict:
    """Bbox cache istatistiklerini döndür. Başarısızsa {} döner."""
    logger.debug("desktop.get_bbox_cache_stats called")
    try:
        return _get_bbox_cache_stats()
    except Exception as exc:
        logger.error("get_bbox_cache_stats hatası: %s", exc, exc_info=True)
        return {}


# ── Thin Wrappers — AT-SPI ────────────────────────────────────────────

async def atspi_get_desktop_tree(max_depth: int = 4) -> dict:
    """AT-SPI accessibility tree'yi döndür. Başarısızsa {} döner."""
    logger.debug("desktop.atspi_get_desktop_tree: max_depth=%d", max_depth)
    try:
        return await _atspi_get_desktop_tree(max_depth=max_depth)
    except Exception as exc:
        logger.error("atspi_get_desktop_tree hatası: %s", exc, exc_info=True)
        return {}


async def atspi_find_element(role: str = "", name: str = "") -> list[dict]:
    """AT-SPI'da element ara. Başarısızsa [] döner."""
    logger.debug("desktop.atspi_find_element: role=%r name=%r", role, name)
    try:
        return await _atspi_find_element(role=role, name=name)
    except Exception as exc:
        logger.error("atspi_find_element hatası: %s", exc, exc_info=True)
        return []


async def atspi_activate_element(role: str = "", name: str = "") -> str:
    """AT-SPI elementini aktive et. Başarısızsa hata mesajı döner."""
    logger.debug("desktop.atspi_activate_element: role=%r name=%r", role, name)
    try:
        return await _atspi_activate_element(role=role, name=name)
    except Exception as exc:
        logger.error("atspi_activate_element hatası: %s", exc, exc_info=True)
        return f"❌ atspi_activate_element hatası: {exc}"


# ── Dosya / Klasör Açma ──────────────────────────────────────────

async def open_path(path: str) -> str:
    """
    Dosyayı veya klasörü varsayılan uygulama ile aç (xdg-open).
    Döner: kullanıcıya gönderilecek durum mesajı.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"❌ Yol bulunamadı: {p}"

    if not shutil.which("xdg-open"):
        return "❌ xdg-open bulunamadı. `sudo apt install xdg-utils` çalıştır."

    proc = await asyncio.create_subprocess_exec(
        "xdg-open", str(p),
        env=_env(),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
    except asyncio.TimeoutError:
        # xdg-open genellikle hemen döner; timeout → açıldı sayılır
        return f"✅ Açıldı: {p}"

    if proc.returncode == 0:
        return f"✅ Açıldı: {p}"
    err = stderr.decode(errors="replace")[:200] if stderr else ""
    return f"❌ xdg-open başarısız (kod {proc.returncode}): {err}"


# ── Ekran Kilidi Açma ────────────────────────────────────────────

async def _dpms_wake() -> None:
    """Monitörü DPMS uyku modundan uyandır (xset dpms force on)."""
    if not shutil.which("xset"):
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "xset", "dpms", "force", "on",
            env=_env(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode == 0:
            logger.debug("_dpms_wake: xset dpms force on başarılı")
    except (asyncio.TimeoutError, OSError):
        logger.debug("_dpms_wake: xset dpms force on başarısız")


async def _verify_unlocked(method: str) -> str | None:
    """Kilit açıldı mı doğrula. Açıldıysa mesaj döner, değilse None."""
    await asyncio.sleep(0.3)  # logind'e zaman tanı
    if not await is_screen_locked():
        await _dpms_wake()
        logger.info("unlock_screen: %s — doğrulandı (kilit açık)", method)
        return f"✅ Ekran kilidi açıldı ({method})."
    logger.debug("unlock_screen: %s — komut başarılı ama ekran hâlâ kilitli", method)
    return None


async def unlock_screen() -> str:
    """
    Ekran kilidini aç.  (DESK-LOGIN-2)

    Üç yöntem sırasıyla denenir:
      1. loginctl unlock-session  (systemd-logind — en güvenilir)
      2. xdg-screensaver reset    (X11 genel)
      3. xdotool key super        (GNOME kilit ekranı fallback)

    Her yöntem sonrası ``is_screen_locked()`` ile doğrulama yapılır;
    komut başarılı dönüp ekran hâlâ kilitliyse bir sonraki yönteme geçilir.
    Kilit açıldığında ``xset dpms force on`` ile monitör uyandırılır.

    SYSTEM_PSSWRD ayarlanmamış olsa bile çalışır.
    Döner: durum mesajı.
    """
    # Ekran zaten açıksa gereksiz işlem yapma
    if not await is_screen_locked():
        await _dpms_wake()
        return "✅ Ekran zaten açık."

    # Yöntem 1 — loginctl unlock-session
    proc = await asyncio.create_subprocess_exec(
        "loginctl", "unlock-session",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
        if proc.returncode == 0:
            msg = await _verify_unlocked("loginctl")
            if msg:
                return msg
        else:
            err = stderr.decode(errors="replace")[:200] if stderr else ""
            logger.debug("loginctl unlock-session başarısız: %s", err)
    except asyncio.TimeoutError:
        logger.debug("loginctl unlock-session zaman aşımı")

    # Yöntem 2 — xdg-screensaver reset
    if shutil.which("xdg-screensaver"):
        _xdg_ok = False
        async with x11_lock:
            proc2 = await asyncio.create_subprocess_exec(
                "xdg-screensaver", "reset",
                env=_env(),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, _stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=10)
                _xdg_ok = proc2.returncode == 0
            except asyncio.TimeoutError:
                logger.debug("xdg-screensaver reset zaman aşımı")
                _stderr2 = None
        if _xdg_ok:
            msg = await _verify_unlocked("xdg-screensaver")
            if msg:
                return msg
        else:
            err = _stderr2.decode(errors="replace")[:200] if _stderr2 else ""
            logger.debug("xdg-screensaver reset başarısız: %s", err)

    # Yöntem 3 — xdotool key super (fallback)
    if _xdotool_available():
        async with x11_lock:
            code, err = await _xdotool("key", "super")
        if code == 0:
            msg = await _verify_unlocked("xdotool super")
            if msg:
                return msg
            logger.debug("xdotool key super başarısız: %s", err)

    return (
        "❌ Ekran kilidi açılamadı.\n"
        "Kontrol:\n"
        "  • loginctl, xdg-screensaver veya xdotool kurulu mu?\n"
        "  • X11 oturumu aktif mi?\n"
        "  • `is_locked` aksiyonuyla kilit durumunu kontrol et."
    )


# ── sudo ile Ayrıcalıklı Komut ───────────────────────────────────

async def sudo_exec(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """
    sudo -S ile ayrıcalıklı komut çalıştırır.
    SYSTEM_PSSWRD şifresi stdin üzerinden iletilir.

    Args:
        cmd:     Çalıştırılacak komut (liste — shell injection riski yok).
        timeout: Saniye cinsinden maksimum süre.

    Döner: (returncode, çıktı_metni)
    Hata durumunda returncode=-1 döner.
    """
    from ..config import settings
    password = settings.system_psswrd.get_secret_value()

    if not password:
        return -1, "❌ SYSTEM_PSSWRD ayarlanmamış — sudo_exec çalışamaz."

    full_cmd = ["sudo", "-S"] + cmd
    try:
        proc = await asyncio.create_subprocess_exec(
            *full_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        pwd_bytes = (password + "\n").encode()
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=pwd_bytes), timeout=timeout
        )
    except asyncio.TimeoutError:
        return -1, f"❌ sudo_exec zaman aşımı ({timeout}s): {' '.join(cmd)}"
    except Exception as exc:
        logger.error("sudo_exec hata: %s", exc)
        return -1, f"❌ sudo_exec istisna: {exc}"

    out = stdout.decode(errors="replace")[-800:] if stdout else ""
    err = stderr.decode(errors="replace")[-400:] if stderr else ""
    # stderr'de şifre promptu satırını gizle
    err_clean = "\n".join(
        line for line in err.splitlines()
        if "password" not in line.lower() and "[sudo]" not in line
    )

    combined = (out + err_clean).strip()[-800:]
    logger.info("sudo_exec: cmd=%s returncode=%s", cmd[:3], proc.returncode)
    return proc.returncode, combined


# ── Uygulama Kurma ───────────────────────────────────────────────

async def run_installer(path: str, timeout: int = 120) -> str:
    """
    Dosya uzantısına göre uygun kurulum komutunu çalıştırır.

    Desteklenen türler:
        .deb        → sudo dpkg -i
        .exe / .msi → wine
        .sh         → bash
        .AppImage   → doğrudan çalıştır (chmod +x)
        .rpm        → sudo rpm -i

    Döner: kullanıcıya gönderilecek durum mesajı.
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"❌ Dosya bulunamadı: {p}"

    ext = p.suffix.lower()

    if ext == ".deb":
        from ..config import settings as _settings
        if _settings.system_psswrd.get_secret_value():
            code, output = await sudo_exec(["dpkg", "-i", str(p)], timeout=timeout)
            if code == 0:
                return f"✅ Kurulum tamamlandı.\n\n{output[-300:]}" if output else "✅ Kurulum tamamlandı."
            return f"⚠️ Kurulum başarısız (kod {code})\n\n{output[-500:]}"
        cmd = ["sudo", "dpkg", "-i", str(p)]
    elif ext in (".exe", ".msi"):
        if not shutil.which("wine"):
            return (
                "❌ Wine kurulu değil.\n"
                "Kurulum: `sudo apt install wine`\n"
                "Sonra tekrar dene."
            )
        cmd = ["wine", str(p)]
    elif ext == ".sh":
        cmd = ["bash", str(p)]
    elif ext == ".appimage":
        # chmod +x gerekli
        p.chmod(p.stat().st_mode | 0o111)
        cmd = [str(p)]
    elif ext == ".rpm":
        if not shutil.which("rpm"):
            return "❌ rpm bulunamadı. Debian tabanlı sistemde .deb tercih et."
        from ..config import settings as _settings
        if _settings.system_psswrd.get_secret_value():
            code, output = await sudo_exec(["rpm", "-i", str(p)], timeout=timeout)
            if code == 0:
                return f"✅ Kurulum tamamlandı.\n\n{output[-300:]}" if output else "✅ Kurulum tamamlandı."
            return f"⚠️ Kurulum başarısız (kod {code})\n\n{output[-500:]}"
        cmd = ["sudo", "rpm", "-i", str(p)]
    else:
        return (
            f"❌ Desteklenmeyen dosya türü: {ext}\n"
            "Desteklenenler: .deb .exe .msi .sh .AppImage .rpm"
        )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        env=_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return (
            f"⏱️ Kurulum {timeout} saniyeyi aştı — arka planda çalışıyor olabilir.\n"
            f"Komut: {' '.join(cmd)}"
        )

    out = stdout.decode(errors="replace")[-600:] if stdout else ""
    err = stderr.decode(errors="replace")[-400:] if stderr else ""

    if proc.returncode == 0:
        summary = out[-300:] if out else "(çıktı yok)"
        return f"✅ Kurulum tamamlandı.\n\n{summary}"

    detail = err or out
    return (
        f"⚠️ Kurulum başarısız (kod {proc.returncode})\n\n"
        f"{detail[-500:]}"
    )


# ── Pencere Yönetimi ─────────────────────────────────────────────────

async def get_windows() -> str:
    """
    Açık pencereleri listeler.
    wmctrl varsa onu kullanır (daha temiz çıktı), yoksa xdotool'a döner.

    Döner: Pencere listesi metni veya hata mesajı.
    """
    if shutil.which("wmctrl"):
        async with x11_lock:
            proc = await asyncio.create_subprocess_exec(
                "wmctrl", "-l",
                env=_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            except asyncio.TimeoutError:
                return "❌ wmctrl zaman aşımı."

        if proc.returncode == 0 and stdout:
            lines = stdout.decode(errors="replace").strip().splitlines()
            windows = []
            for line in lines:
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    wid, desktop, _host, title = parts
                    windows.append(f"  {wid}  [masaüstü {desktop}]  {title}")
            if windows:
                logger.info("get_windows: %d pencere bulundu (wmctrl)", len(windows))
                return f"Açık pencereler ({len(windows)}):\n" + "\n".join(windows)
        return "(Görünür pencere bulunamadı)"

    # wmctrl yoksa xdotool ile dene
    if not _xdotool_available():
        return (
            "❌ wmctrl veya xdotool kurulu değil.\n"
            "Kurulum: `sudo apt install wmctrl` veya `sudo apt install xdotool`"
        )

    async with x11_lock:
        proc = await asyncio.create_subprocess_exec(
            "xdotool", "search", "--onlyvisible", "--name", "",
            env=_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            return "❌ xdotool zaman aşımı."

    if proc.returncode != 0 or not stdout:
        return "(Görünür pencere bulunamadı)"

    window_ids = stdout.decode(errors="replace").strip().splitlines()
    result_lines = []
    for wid in window_ids[:20]:  # max 20 pencere
        wid = wid.strip()
        if not wid:
            continue
        async with x11_lock:
            name_proc = await asyncio.create_subprocess_exec(
                "xdotool", "getwindowname", wid,
                env=_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                name_out, _ = await asyncio.wait_for(name_proc.communicate(), timeout=5)
                name = name_out.decode(errors="replace").strip()
            except asyncio.TimeoutError:
                name = "(bilinmiyor)"
        result_lines.append(f"  ID: {wid}  Başlık: {name}")

    if result_lines:
        logger.info("get_windows: %d pencere bulundu (xdotool)", len(result_lines))
        return f"Açık pencereler ({len(result_lines)}):\n" + "\n".join(result_lines)
    return "(Görünür pencere bulunamadı)"


async def focus_window(
    window_name: Optional[str] = None,
    window_id: Optional[str] = None,
) -> str:
    """
    Pencereyi öne getirir ve odaklar.

    Args:
        window_name: Pencere başlığı (kısmi eşleşme). wmctrl -a ile arar.
        window_id:   Pencere ID (hex, ör. "0x05000003"). wmctrl -i -a ile odaklar.

    En az biri gerekli. Her ikisi verilirse window_id önceliklidir.

    Odaklama öncelik sırası (DESK-OPT-6):
      window_id verildiğinde:
        1. python-xlib _NET_ACTIVE_WINDOW ClientMessage  ← Mutter/KWin güvenilir
        2. wmctrl -i -a                                  ← EWMH uyumlu WM'ler
        3. xdotool windowactivate                        ← son çare
      window_name verildiğinde:
        1. wmctrl -a (kısmi ad eşleşmesi)
        2. xdotool search → ID al → _NET_ACTIVE_WINDOW  ← ID bulununca xlib dene
        3. xdotool windowactivate (son çare)

    Döner: Durum mesajı.
    """
    if not window_name and not window_id:
        return "❌ window_name veya window_id parametrelerinden biri gerekli."

    # ── window_id yolu ──────────────────────────────────────────────────
    if window_id:
        _wid = window_id.strip()

        # 1. python-xlib _NET_ACTIVE_WINDOW (DESK-OPT-6)
        try:
            wid_int = int(_wid, 16) if _wid.startswith(("0x", "0X")) else int(_wid)
        except ValueError:
            wid_int = None

        if wid_int is not None:
            ok, _err = await _net_active_window(wid_int)
            if ok:
                return f"✅ Pencere odaklandı: {_wid}"
            logger.debug("_NET_ACTIVE_WINDOW başarısız (%s); wmctrl'e düşülüyor", _err)

        # 2. wmctrl -i -a
        if shutil.which("wmctrl"):
            async with x11_lock:
                code, err = await _wmctrl("-i", "-a", _wid)
            if code == 0:
                logger.info("focus_window: ID=%s odaklandı (wmctrl)", _wid)
                return f"✅ Pencere odaklandı: {_wid}"
            logger.debug("wmctrl -i -a %s başarısız (%d): %s", _wid, code, err)

        # 3. xdotool windowactivate
        if not _xdotool_available():
            return (
                "❌ Pencere odaklanamadı: python-xlib başarısız, "
                "wmctrl veya xdotool kurulu değil.\n"
                "Kurulum: `sudo apt install wmctrl xdotool`"
            )
        async with x11_lock:
            code, err = await _xdotool("windowactivate", "--sync", _wid)
        if code == 0:
            logger.info("focus_window: ID=%s odaklandı (xdotool)", _wid)
            return f"✅ Pencere odaklandı: {_wid}"
        return f"❌ xdotool windowactivate başarısız (kod {code}): {err}"

    # ── window_name yolu ────────────────────────────────────────────────
    _name = window_name.strip()  # type: ignore[union-attr]

    # 1. wmctrl -a (kısmi ad eşleşmesi — EWMH)
    if shutil.which("wmctrl"):
        async with x11_lock:
            code, err = await _wmctrl("-a", _name)
        if code == 0:
            logger.info("focus_window: name=%r odaklandı (wmctrl)", _name)
            return f"✅ Pencere odaklandı: {_name!r}"
        logger.debug("wmctrl -a %r başarısız (%d): %s", _name, code, err)

    if not _xdotool_available():
        return (
            "❌ wmctrl veya xdotool kurulu değil.\n"
            "Kurulum: `sudo apt install wmctrl` veya `sudo apt install xdotool`"
        )

    # 2. xdotool search → ID bul → _NET_ACTIVE_WINDOW dene
    async with x11_lock:
        search_proc = await asyncio.create_subprocess_exec(
            "xdotool", "search", "--name", _name,
            env=_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            search_out, _ = await asyncio.wait_for(search_proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            return "❌ xdotool search zaman aşımı."

    if search_proc.returncode != 0 or not search_out:
        return f"❌ '{_name}' adında pencere bulunamadı."

    first_id_str = search_out.decode(errors="replace").strip().splitlines()[0].strip()

    # ID bulundu — önce xlib dene (DESK-OPT-6)
    try:
        found_wid_int = int(first_id_str)
    except ValueError:
        found_wid_int = None

    if found_wid_int is not None:
        ok, _err = await _net_active_window(found_wid_int)
        if ok:
            logger.info(
                "focus_window: name=%r → ID=%s odaklandı (_NET_ACTIVE_WINDOW)",
                _name, first_id_str,
            )
            return f"✅ Pencere odaklandı: {_name!r} (ID: {first_id_str})"
        logger.debug("_NET_ACTIVE_WINDOW başarısız (%s); xdotool'a düşülüyor", _err)

    # 3. xdotool windowactivate (son çare)
    async with x11_lock:
        code, err = await _xdotool("windowactivate", "--sync", first_id_str)
    if code == 0:
        logger.info("focus_window: name=%r → ID=%s odaklandı (xdotool)", _name, first_id_str)
        return f"✅ Pencere odaklandı: {_name!r} (ID: {first_id_str})"
    return f"❌ xdotool windowactivate başarısız (kod {code}): {err}"


# ── Popup yönetimi (DESK-OPT-8) ──────────────────────────────────────

async def start_watch_popup(
    wm_class_patterns: list[str],
    timeout_s: float = 30.0,
    watcher_id: Optional[str] = None,
) -> tuple[bool, str, str]:
    """X11 MapNotify izleyiciyi başlatır. Döner: (ok, mesaj, watcher_id)."""
    logger.debug("desktop.start_watch_popup: patterns=%s timeout=%.0f", wm_class_patterns, timeout_s)
    try:
        return await _start_watch_popup(
            wm_class_patterns=wm_class_patterns,
            timeout_s=timeout_s,
            watcher_id=watcher_id,
        )
    except Exception as exc:
        logger.error("start_watch_popup hatası: %s", exc, exc_info=True)
        return False, f"❌ İzleyici başlatılamadı: {exc}", ""


async def stop_watch_popup(watcher_id: str) -> tuple[bool, str]:
    """Çalışan popup izleyiciyi durdurur. Döner: (ok, mesaj)."""
    logger.debug("desktop.stop_watch_popup: id=%s", watcher_id)
    try:
        return await _stop_watch_popup(watcher_id)
    except Exception as exc:
        logger.error("stop_watch_popup hatası: %s", exc, exc_info=True)
        return False, f"❌ İzleyici durdurulamadı: {exc}"


def list_watch_popups() -> list[dict]:
    """Aktif popup izleyicileri listeler."""
    try:
        return _list_watch_popups()
    except Exception as exc:
        logger.error("list_watch_popups hatası: %s", exc, exc_info=True)
        return []
