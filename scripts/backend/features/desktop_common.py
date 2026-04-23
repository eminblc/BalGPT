"""
Desktop ortak yardımcılar — alt modüller tarafından paylaşılan düşük seviyeli araçlar.

Bu modül doğrudan kullanıcıya sunulmaz; yalnızca features/desktop_*.py alt modülleri
tarafından import edilir.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil

logger = logging.getLogger(__name__)

# ── X11 erişim kilidi ──────────────────────────────────────────────────
# Birden fazla coroutine aynı anda X11 soketine yazarsa "Expected reply for
# request N, but got N+1" hatası ve session çökmesi yaşanabilir.
# Tüm X11 subprocess çağrıları (xdotool, wmctrl, scrot, xrandr) bu kilit
# altında seri hale getirilmelidir.
x11_lock: asyncio.Lock = asyncio.Lock()

# ── DISPLAY tespiti ────────────────────────────────────────────────────


def _detect_display() -> str:
    """
    Aktif X11 display'i tespit eder.

    Öncelik sırası:
    1. /tmp/.X11-unix/ altındaki soketler (X0, X1, ...) — socket gerçekten varsa
    2. DISPLAY env değişkeni (socket bulunamazsa fallback)
    3. Varsayılan :0

    Not: DISPLAY env'e önce güvenilmez çünkü systemd servisi farklı display
    numarasıyla başlatılmış olabilir (ör. env=:0 ama aktif display :1).
    """
    x11_dir = "/tmp/.X11-unix"
    try:
        entries = sorted(os.listdir(x11_dir))
        for entry in entries:
            if entry.startswith("X"):
                num = entry[1:]
                if num.isdigit():
                    detected = f":{num}"
                    logger.debug("DISPLAY auto-detect: %s (from socket)", detected)
                    return detected
    except OSError:
        pass

    env_val = os.environ.get("DISPLAY", "").strip()
    if env_val:
        logger.debug("DISPLAY fallback to env: %s", env_val)
        return env_val

    return ":0"


def _detect_xauthority() -> str:
    """
    Aktif X11 Xauthority dosyasını tespit eder.

    Öncelik sırası:
    1. XAUTHORITY env değişkeni (varsa ve dosya gerçekten mevcutsa)
    2. /run/user/{uid}/gdm/Xauthority  — GDM oturumu (Ubuntu/GNOME varsayılanı)
    3. ~/.Xauthority                   — geleneksel fallback
    4. Boş string (set edilmez)

    Not: Systemd servisi XAUTHORITY ortam değişkeni olmadan başlar;
    bu nedenle dinamik tespit zorunludur.
    """
    # 1. Env'de açıkça set edilmişse ve dosya varsa kullan
    env_val = os.environ.get("XAUTHORITY", "").strip()
    if env_val and os.path.isfile(env_val):
        logger.debug("XAUTHORITY from env: %s", env_val)
        return env_val

    # 2. GDM oturumu — /run/user/{uid}/gdm/Xauthority
    uid = os.getuid()
    gdm_path = f"/run/user/{uid}/gdm/Xauthority"
    if os.path.isfile(gdm_path):
        logger.debug("XAUTHORITY auto-detect (GDM): %s", gdm_path)
        return gdm_path

    # 3. ~/.Xauthority — geleneksel X11 auth dosyası
    home = os.path.expanduser("~")
    home_path = os.path.join(home, ".Xauthority")
    if os.path.isfile(home_path):
        logger.debug("XAUTHORITY auto-detect (home): %s", home_path)
        return home_path

    logger.debug("XAUTHORITY tespit edilemedi — set edilmeyecek")
    return ""


def _env() -> dict:
    """DISPLAY ve XAUTHORITY set edilmiş environment — her çağrıda dinamik tespit eder."""
    base = {**os.environ, "DISPLAY": _detect_display()}
    xauth = _detect_xauthority()
    if xauth:
        base["XAUTHORITY"] = xauth
    return base


# ── xdotool yardımcıları ──────────────────────────────────────────────

def _xdotool_available() -> bool:
    return bool(shutil.which("xdotool"))


async def _xdotool(*args: str, timeout: int = 5) -> tuple[int, str]:
    """
    xdotool komutunu çalıştırır.
    Döner: (returncode, stderr_mesajı).
    """
    proc = await asyncio.create_subprocess_exec(
        "xdotool", *args,
        env=_env(),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return -1, f"xdotool zaman aşımı ({timeout}s)"

    err = stderr.decode(errors="replace")[:300] if stderr else ""
    return proc.returncode, err


async def _wmctrl(*args: str, timeout: int = 10) -> tuple[int, str]:
    """
    wmctrl komutunu çalıştırır.
    Döner: (returncode, stderr_mesajı).
    """
    proc = await asyncio.create_subprocess_exec(
        "wmctrl", *args,
        env=_env(),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return -1, f"wmctrl zaman aşımı ({timeout}s)"
    err = stderr.decode(errors="replace")[:300] if stderr else ""
    return proc.returncode, err


# ── Güvenli tuş adı validasyonu ────────────────────────────────────────

# İzin verilen karakter seti: harf, rakam, +, -, _, boşluk
# Örnekler: "ctrl+c", "Return", "F5", "super+l", "alt+F4"
_SAFE_KEY_RE = re.compile(r'^[A-Za-z0-9+\-_ ]{1,64}$')


def _validate_key(key: str) -> bool:
    """xdotool key argümanının güvenli olup olmadığını kontrol eder."""
    return bool(_SAFE_KEY_RE.match(key))


# ── xdotool scroll düğme numaraları ────────────────────────────────────

_SCROLL_BUTTON = {
    "up": "4",
    "down": "5",
    "left": "6",
    "right": "7",
}


# ── Ekran kilit tespiti ─────────────────────────────────────────────────

async def is_screen_locked() -> bool:
    """
    Ekranın kilitli olup olmadığını tespit eder.

    loginctl show-session --value -p LockedHint komutuyla kontrol eder.
    Komut bulunamazsa veya hata alınırsa güvenli tarafta kalır (False döner).
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "loginctl", "show-session", "--value", "-p", "LockedHint",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        result = stdout.decode().strip().lower()
        return result == "yes"
    except (FileNotFoundError, OSError, asyncio.TimeoutError):
        return False
