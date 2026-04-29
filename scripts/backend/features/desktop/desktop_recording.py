"""
Desktop ekran video kaydı modülü — ffmpeg ile X11 ekran kaydı.

Public API:
    record_screen(output_path, duration, region) -> Optional[Path]
    record_all_monitors(output_dir, duration) -> list[tuple[str, Path]]

Gereksinimler:
    sudo apt install ffmpeg

Config (config.py / .env):
    DESKTOP_RECORDING=true/false       — kaydı etkinleştir (varsayılan: false)
    DESKTOP_RECORDING_MAX_MB=16        — WhatsApp boyut limiti MB cinsinden (varsayılan: 16)

FEAT-DESK-REC-1 + FEAT-DESK-MULTIMON-1
"""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional

from .desktop_common import _detect_display, _env
from .desktop_capture import list_monitors

logger = logging.getLogger(__name__)

# ffmpeg komutu: X11 ekranını yakala ve H.264 olarak kodla (hafif, hızlı)
# -framerate 15: CPU dostu kare hızı
# -preset ultrafast: encode gecikmesi minimumda
# -pix_fmt yuv420p: geniş oynatıcı uyumluluğu
_FFMPEG_BASE_ARGS = [
    "-y",                    # mevcut dosyanın üzerine yaz
    "-f", "x11grab",
    "-framerate", "15",
    "-c:v", "libx264",
    "-preset", "ultrafast",
    "-pix_fmt", "yuv420p",
]


def _recording_enabled() -> bool:
    """DESKTOP_RECORDING config flag'ini kontrol eder."""
    from ...config import settings
    return settings.desktop_recording


def _max_mb() -> int:
    """WhatsApp boyut limiti (MB)."""
    from ...config import settings
    return settings.desktop_recording_max_mb


async def record_screen(
    output_path: str,
    duration: int,
    region: Optional[tuple[int, int, int, int]] = None,
) -> Optional[Path]:
    """
    X11 ekranını ffmpeg ile kaydeder.

    Args:
        output_path: Kayıt dosyası yolu (.mp4).
        duration:    Kayıt süresi saniye cinsinden (1–300).
        region:      (x, y, w, h) — sadece bu bölgeyi kaydet. None ise tüm ekran.

    Döner: Kayıt dosyası Path veya başarısızsa None.
    """
    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg bulunamadı. `sudo apt install ffmpeg` ile kur.")
        return None

    display = _detect_display()

    if region is not None:
        x, y, w, h = region
        # H.264 genişlik/yükseklik çift sayı olmalı
        w = w if w % 2 == 0 else w - 1
        h = h if h % 2 == 0 else h - 1
        video_size = f"{w}x{h}"
        input_src = f"{display}+{x},{y}"
    else:
        # Tüm ekran — boyutu xdpyinfo'dan veya varsayılandan al
        video_size = await _get_screen_resolution(display)
        input_src = f"{display}+0,0"

    cmd = [
        "ffmpeg",
        "-video_size", video_size,
        "-i", input_src,
        *_FFMPEG_BASE_ARGS,
        "-t", str(duration),
        output_path,
    ]

    env = _env()
    logger.info(
        "record_screen: başlıyor — region=%s video_size=%s duration=%ds → %s",
        region, video_size, duration, output_path,
    )

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    timeout = duration + 30  # kayda ek süre toleransı
    try:
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        logger.warning("record_screen: zaman aşımı (%ds)", timeout)
        return None

    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[-300:] if stderr else ""
        logger.warning("record_screen: ffmpeg başarısız (kod %d): %s", proc.returncode, err)
        return None

    p = Path(output_path)
    if p.exists() and p.stat().st_size > 0:
        size_mb = p.stat().st_size / (1024 * 1024)
        logger.info("record_screen: tamamlandı → %s (%.1f MB)", output_path, size_mb)
        return p

    logger.warning("record_screen: çıktı dosyası oluşturulamadı: %s", output_path)
    return None


async def record_all_monitors(
    output_dir: str,
    duration: int,
) -> list[tuple[str, Path]]:
    """
    Her monitör için ayrı video kaydı alır.

    Args:
        output_dir: Kayıt dizini.
        duration:   Kayıt süresi saniye (1–300).

    Döner: [(monitor_name, video_path), ...] listesi.
    """
    monitors = await list_monitors()

    # Tek / sıfır monitör → tüm ekranı kaydet
    if len(monitors) <= 1:
        out_path = f"{output_dir}/recording_primary.mp4"
        rec = await record_screen(out_path, duration)
        if rec:
            name = monitors[0]["name"] if monitors else "primary"
            return [(name, rec)]
        return []

    results: list[tuple[str, Path]] = []
    for i, mon in enumerate(monitors):
        region = (mon["x"], mon["y"], mon["w"], mon["h"])
        out_path = f"{output_dir}/recording_{i}_{mon['name']}.mp4"
        rec = await record_screen(out_path, duration, region=region)
        if rec:
            results.append((mon["name"], rec))
            logger.debug("record_all_monitors: %s → %s", mon["name"], rec)
        else:
            logger.warning(
                "record_all_monitors: %s kayıt başarısız (region=%s)",
                mon["name"], region,
            )

    return results


def check_size_mb(path: Path) -> float:
    """Dosya boyutunu MB cinsinden döndürür."""
    return path.stat().st_size / (1024 * 1024)


async def _get_screen_resolution(display: str) -> str:
    """
    xdpyinfo ile ekran çözünürlüğünü alır.
    Başarısızsa güvenli varsayılan '1920x1080' döner.
    """
    if not shutil.which("xdpyinfo"):
        return "1920x1080"

    import re
    proc = await asyncio.create_subprocess_exec(
        "xdpyinfo",
        env={**__import__("os").environ, "DISPLAY": display},
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
    except asyncio.TimeoutError:
        return "1920x1080"

    if stdout:
        m = re.search(r"dimensions:\s+(\d+x\d+)", stdout.decode(errors="replace"))
        if m:
            return m.group(1)

    return "1920x1080"
