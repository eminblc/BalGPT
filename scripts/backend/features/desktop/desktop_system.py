"""Sistem operasyonları — dosya açma, ekran kilidi, sudo, kurulum, pencere yönetimi (SRP).

Sorumluluk: X11/systemd seviyesinde sistem kaynaklarını yönetmek.
Bu modül desktop.py facade'ının alt-modüllerinden biridir.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional

from .desktop_common import (
    _env, _wmctrl, _xdotool, _xdotool_available,
    is_screen_locked, x11_lock,
)

logger = logging.getLogger(__name__)


# ── Dosya / Yol Açma ─────────────────────────────────────────────

async def open_path(path: str) -> str:
    """Dosyayı veya klasörü varsayılan uygulama ile aç (xdg-open)."""
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
        return f"✅ Açıldı: {p}"
    if proc.returncode == 0:
        return f"✅ Açıldı: {p}"
    err = stderr.decode(errors="replace")[:200] if stderr else ""
    return f"❌ xdg-open başarısız (kod {proc.returncode}): {err}"


# ── Ekran Kilidi Açma ─────────────────────────────────────────────

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
    await asyncio.sleep(0.3)
    if not await is_screen_locked():
        await _dpms_wake()
        logger.info("unlock_screen: %s — doğrulandı (kilit açık)", method)
        return f"✅ Ekran kilidi açıldı ({method})."
    logger.debug("unlock_screen: %s — komut başarılı ama ekran hâlâ kilitli", method)
    return None


async def unlock_screen() -> str:
    """Ekran kilidini aç. (DESK-LOGIN-2)

    Üç yöntem sırasıyla: loginctl unlock-session → xdg-screensaver reset → xdotool key super.
    Her yöntem sonrası is_screen_locked() ile doğrulama yapılır.
    """
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


# ── sudo ile Ayrıcalıklı Komut ────────────────────────────────────

async def sudo_exec(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    """sudo -S ile ayrıcalıklı komut çalıştırır. SYSTEM_PSSWRD stdin üzerinden iletilir.

    Döner: (returncode, çıktı_metni). Hata durumunda returncode=-1.
    """
    from ...config import settings
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
    except OSError as exc:
        logger.error("sudo_exec hata: %s", exc)
        return -1, f"❌ sudo_exec istisna: {exc}"

    out = stdout.decode(errors="replace")[-800:] if stdout else ""
    err = stderr.decode(errors="replace")[-400:] if stderr else ""
    err_clean = "\n".join(
        line for line in err.splitlines()
        if "password" not in line.lower() and "[sudo]" not in line
    )
    combined = (out + err_clean).strip()[-800:]
    logger.info("sudo_exec: cmd=%s returncode=%s", cmd[:3], proc.returncode)
    return proc.returncode, combined


# ── Uygulama Kurma ────────────────────────────────────────────────

async def run_installer(path: str, timeout: int = 120) -> str:
    """Dosya uzantısına göre uygun kurulum komutunu çalıştırır.

    Desteklenen türler: .deb, .exe/.msi (wine), .sh, .AppImage, .rpm
    """
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return f"❌ Dosya bulunamadı: {p}"

    ext = p.suffix.lower()

    if ext == ".deb":
        from ...config import settings as _settings
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
        p.chmod(p.stat().st_mode | 0o111)
        cmd = [str(p)]
    elif ext == ".rpm":
        if not shutil.which("rpm"):
            return "❌ rpm bulunamadı. Debian tabanlı sistemde .deb tercih et."
        from ...config import settings as _settings
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
        return f"✅ Kurulum tamamlandı.\n\n{out[-300:] if out else '(çıktı yok)'}"
    return f"⚠️ Kurulum başarısız (kod {proc.returncode})\n\n{(err or out)[-500:]}"


# ── Pencere Yönetimi ──────────────────────────────────────────────

async def get_windows() -> str:
    """Açık pencereleri listeler. wmctrl varsa kullanır, yoksa xdotool'a döner."""
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
    for wid in window_ids[:20]:
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
    """Pencereyi öne getirir ve odaklar. window_id veya window_name gerekli.

    Odaklama öncelik sırası (DESK-OPT-6):
      ID ile: python-xlib _NET_ACTIVE_WINDOW → wmctrl -i -a → xdotool windowactivate
      Ad ile: wmctrl -a → xdotool search → _NET_ACTIVE_WINDOW → xdotool windowactivate
    """
    if not window_name and not window_id:
        return "❌ window_name veya window_id parametrelerinden biri gerekli."

    from .desktop_input import net_active_window as _net_active_window

    if window_id:
        _wid = window_id.strip()
        try:
            wid_int = int(_wid, 16) if _wid.startswith(("0x", "0X")) else int(_wid)
        except ValueError:
            wid_int = None

        if wid_int is not None:
            ok, _err = await _net_active_window(wid_int)
            if ok:
                return f"✅ Pencere odaklandı: {_wid}"
            logger.debug("_NET_ACTIVE_WINDOW başarısız (%s); wmctrl'e düşülüyor", _err)

        if shutil.which("wmctrl"):
            async with x11_lock:
                code, err = await _wmctrl("-i", "-a", _wid)
            if code == 0:
                logger.info("focus_window: ID=%s odaklandı (wmctrl)", _wid)
                return f"✅ Pencere odaklandı: {_wid}"
            logger.debug("wmctrl -i -a %s başarısız (%d): %s", _wid, code, err)

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

    _name = window_name.strip()  # type: ignore[union-attr]

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

    async with x11_lock:
        code, err = await _xdotool("windowactivate", "--sync", first_id_str)
    if code == 0:
        logger.info("focus_window: name=%r → ID=%s odaklandı (xdotool)", _name, first_id_str)
        return f"✅ Pencere odaklandı: {_name!r} (ID: {first_id_str})"
    return f"❌ xdotool windowactivate başarısız (kod {code}): {err}"
