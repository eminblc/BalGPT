"""
Desktop ekran yakalama modülü — screenshot ve OCR.

Public API:
    capture_screen(output_path, region) -> Optional[Path]
    capture_screen_base64_fast(region) -> Optional[str]   # disk I/O yok
    ocr_screen() -> str
    list_monitors() -> list[dict]          # xrandr ile monitör geometri listesi
    capture_all_monitors(output_dir) -> list[tuple[str, Path]]  # her monitör için screenshot
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from ...config import settings
from .desktop_common import _detect_display, _detect_xauthority, _env, x11_lock  # _detect_display: ocr_screen hata mesajında kullanılır

logger = logging.getLogger(__name__)


def _resize_png_bytes(png: bytes, max_w: int) -> bytes:
    """Vision API boyut limiti için PNG'yi max_w piksel genişliğe ölçekle."""
    if max_w <= 0:
        return png
    try:
        from io import BytesIO
        from PIL import Image
    except ImportError:
        logger.debug("Pillow yok; resize atlandı")
        return png
    try:
        img = Image.open(BytesIO(png))
        if img.width <= max_w:
            return png
        ratio = max_w / img.width
        new_size = (max_w, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)
        buf = BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    except Exception as e:
        logger.warning("Resize başarısız: %s", e)
        return png


def _resize_png_file(path: Path, max_w: int) -> None:
    """Disk'teki PNG'yi yerinde resize et (best effort)."""
    if max_w <= 0 or not path.exists():
        return
    try:
        original = path.read_bytes()
        resized = _resize_png_bytes(original, max_w)
        if resized is not original and len(resized) != len(original):
            path.write_bytes(resized)
    except Exception as e:
        logger.debug("Disk resize atlandı (%s): %s", path, e)


# ── mss yardımcıları (executor thread'de çalışır) ─────────────────────────


def _mss_monitor_dict(
    sct,  # mss.MSSBase instance
    region: Optional[tuple[int, int, int, int]],
) -> dict:
    """mss için monitor dict oluşturur."""
    if region is not None:
        x, y, w, h = region
        return {"left": x, "top": y, "width": w, "height": h}
    # monitors[0] = tüm ekranları kapsayan birleşik sanal monitör
    return sct.monitors[0]


def _mss_capture_to_bytes_sync(
    display: str,
    xauth: str,
    region: Optional[tuple[int, int, int, int]],
) -> Optional[bytes]:
    """
    mss ile ekran yakalar, bellekte PNG bytes döndürür (disk I/O yok).
    x11_lock altında, executor thread'de çalıştırılır.
    """
    try:
        import mss
        import mss.tools
    except ImportError:
        logger.debug("mss kurulu değil — scrot fallback kullanılacak")
        return None

    # mss DISPLAY/XAUTHORITY'yi yalnızca os.environ'dan okur; Display() API'si yok.
    # x11_lock bu blok boyunca serialize ettiği için thread-safety sağlanır.
    os.environ["DISPLAY"] = display
    if xauth:
        os.environ["XAUTHORITY"] = xauth

    try:
        with mss.mss() as sct:
            monitor = _mss_monitor_dict(sct, region)
            img = sct.grab(monitor)
            return mss.tools.to_png(img.rgb, img.size)
    except Exception as exc:
        logger.debug("mss yakalama başarısız: %s", exc)
        return None


async def _capture_with_mss(
    output_path: str,
    region: Optional[tuple[int, int, int, int]],
) -> Optional[Path]:
    """
    mss ile ekran görüntüsü al ve dosyaya yaz.
    Başarısızsa (mss yoksa veya hata varsa) None döner → scrot fallback devreye girer.
    """
    display = _detect_display()
    xauth = _detect_xauthority()
    loop = asyncio.get_running_loop()

    async with x11_lock:
        png_bytes = await loop.run_in_executor(
            None,
            _mss_capture_to_bytes_sync,
            display, xauth, region,
        )

    if png_bytes is None:
        return None

    png_bytes = _resize_png_bytes(png_bytes, settings.desktop_screenshot_max_width)
    p = Path(output_path)
    p.write_bytes(png_bytes)
    if p.exists() and p.stat().st_size > 0:
        logger.debug("Ekran görüntüsü alındı: mss (%s)", output_path)
        return p
    return None


async def capture_screen(
    output_path: Optional[str] = None,
    region: Optional[tuple[int, int, int, int]] = None,
) -> Optional[Path]:
    """
    Ekran görüntüsü al.

    Öncelik sırası: python-mss (X11 SHM, ~50ms) → scrot → import (ImageMagick).
    python-mss kurulu değilse veya başarısız olursa subprocess fallback devreye girer.

    Args:
        output_path: Kaydedilecek dosya yolu. None ise /tmp/wa_screenshot.png kullanılır.
        region: (x, y, w, h) — yalnızca bu bölgeyi yakala. None ise tüm ekran.
                Örnek: (0, 0, 800, 600) → sol üst 800×600 piksel.

    Döner: kayıt yolu (Path) veya başarısızsa None.
    """
    if output_path is None:
        output_path = "/tmp/wa_screenshot.png"

    # 1. python-mss (in-process, X11 SHM — en hızlı)
    result = await _capture_with_mss(output_path, region)
    if result is not None:
        return result

    # 2. subprocess fallback: scrot → import (ImageMagick)
    # gnome-screenshot D-Bus ile ekrana eriştiğinden systemd servislerde siyah görüntü verir.
    tools: list[tuple[str, list[str]]] = []
    if shutil.which("scrot"):
        if region is not None:
            x, y, w, h = region
            tools.append(("scrot", ["-a", f"{x},{y},{w},{h}", output_path]))
        else:
            tools.append(("scrot", [output_path]))
    if shutil.which("import"):  # ImageMagick
        if region is not None:
            x, y, w, h = region
            tools.append(("import", ["-window", "root", "-crop", f"{w}x{h}+{x}+{y}", output_path]))
        else:
            tools.append(("import", ["-window", "root", output_path]))

    if not tools:
        logger.error(
            "Ekran görüntüsü aracı bulunamadı. "
            "`pip install mss` veya `sudo apt install scrot` ile kur."
        )
        return None

    for tool, args in tools:
        async with x11_lock:
            proc = await asyncio.create_subprocess_exec(
                tool, *args,
                env=_env(),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            except asyncio.TimeoutError:
                logger.warning("%s zaman aşımı", tool)
                continue

        if proc.returncode == 0:
            p = Path(output_path)
            if p.exists() and p.stat().st_size > 0:
                _resize_png_file(p, settings.desktop_screenshot_max_width)
                logger.debug("Ekran görüntüsü alındı: %s (%s)", tool, output_path)
                return p
        else:
            err = stderr.decode(errors="replace")[:200] if stderr else ""
            logger.debug("%s başarısız: %s", tool, err)

    return None


async def capture_screen_base64_fast(
    region: Optional[tuple[int, int, int, int]] = None,
) -> Optional[str]:
    """
    Ekran görüntüsünü doğrudan Base64 string olarak döndürür (disk I/O yok).

    python-mss kullanır; kurulu değilse capture_screen() ile geçici dosyaya fallback yapar.

    Args:
        region: (x, y, w, h) bölgesi; None ise tüm ekran.

    Döner: Base64 PNG string veya başarısızsa None.
    """
    display = _detect_display()
    xauth = _detect_xauthority()
    loop = asyncio.get_running_loop()

    async with x11_lock:
        png_bytes = await loop.run_in_executor(
            None,
            _mss_capture_to_bytes_sync,
            display, xauth, region,
        )

    if png_bytes is not None:
        png_bytes = _resize_png_bytes(png_bytes, settings.desktop_screenshot_max_width)
        return base64.b64encode(png_bytes).decode()

    # Fallback: geçici dosya üzerinden
    logger.debug("capture_screen_base64_fast: mss başarısız, dosya fallback")
    import tempfile as _tmp
    with _tmp.NamedTemporaryFile(suffix=".png", delete=False, dir="/tmp") as f:
        tmp = f.name
    shot = await capture_screen(tmp, region=region)
    if shot is None:
        Path(tmp).unlink(missing_ok=True)
        return None
    data = shot.read_bytes()
    shot.unlink(missing_ok=True)
    data = _resize_png_bytes(data, settings.desktop_screenshot_max_width)
    return base64.b64encode(data).decode()


async def ocr_screen() -> str:
    """
    Ekran görüntüsü al ve tesseract ile OCR çalıştır.

    Döner: okunan metin veya hata mesajı.
    """
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir="/tmp") as f:
        tmp_img = f.name

    screenshot = await capture_screen(tmp_img)

    if screenshot is None:
        Path(tmp_img).unlink(missing_ok=True)
        return (
            "❌ Ekran görüntüsü alınamadı.\n\n"
            f"DISPLAY={_detect_display()}\n"
            "Kontrol:\n"
            "  • X11 oturumu açık mı?\n"
            "  • `pip install mss` veya `sudo apt install scrot` kurulu mu?\n"
            "  • SSH üzerindeysen: `export DISPLAY=:1`"
        )

    if not shutil.which("tesseract"):
        return (
            f"❌ Tesseract kurulu değil.\n"
            "Kurulum: `sudo apt install tesseract-ocr tesseract-ocr-tur`\n\n"
            f"(Görüntü kaydedildi: {screenshot})"
        )

    ocr_base = tmp_img.replace(".png", "_ocr")
    proc = await asyncio.create_subprocess_exec(
        "tesseract", str(screenshot), ocr_base, "-l", "tur+eng",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=30)
    except asyncio.TimeoutError:
        Path(tmp_img).unlink(missing_ok=True)
        return "❌ OCR zaman aşımı (30s)."

    Path(tmp_img).unlink(missing_ok=True)

    ocr_txt = Path(ocr_base + ".txt")
    if ocr_txt.exists():
        text = ocr_txt.read_text(encoding="utf-8").strip()
        ocr_txt.unlink(missing_ok=True)
        return text if text else "(Ekranda okunabilir metin bulunamadı)"

    return "❌ OCR başarısız — çıktı dosyası oluşturulamadı."


async def list_monitors() -> list[dict]:
    """
    xrandr --listmonitors çıktısını parse ederek monitör geometri listesi döndürür.

    Döner: Her monitör için dict listesi:
        [{"name": "HDMI-0", "x": 0, "y": 0, "w": 1920, "h": 1080}, ...]

    xrandr yoksa veya parse başarısız olursa boş liste döner.
    """
    if not shutil.which("xrandr"):
        logger.debug("xrandr bulunamadı — monitör listesi alınamıyor")
        return []

    async with x11_lock:
        proc = await asyncio.create_subprocess_exec(
            "xrandr", "--listmonitors",
            env=_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
        except asyncio.TimeoutError:
            logger.warning("xrandr --listmonitors zaman aşımı")
            return []

    if proc.returncode != 0 or not stdout:
        return []

    output = stdout.decode(errors="replace")
    # Satır formatı: " 0: +*HDMI-0 1920/527x1080/296+0+0  HDMI-0"
    # Geometry pattern: <w>/<mm>x<h>/<mm>+<x>+<y>
    pattern = re.compile(
        r'^\s*\d+:\s+\S+\s+(\d+)/\d+x(\d+)/\d+\+(-?\d+)\+(-?\d+)\s+(\S+)',
        re.MULTILINE,
    )
    monitors = []
    for match in pattern.finditer(output):
        w, h, x, y, name = (
            int(match.group(1)),
            int(match.group(2)),
            int(match.group(3)),
            int(match.group(4)),
            match.group(5),
        )
        monitors.append({"name": name, "x": x, "y": y, "w": w, "h": h})

    logger.debug("list_monitors: %d monitör bulundu: %s", len(monitors), monitors)
    return monitors


async def capture_all_monitors(
    output_dir: Optional[str] = None,
) -> list[tuple[str, Path]]:
    """
    Her monitör için ayrı ekran görüntüsü alır.

    Args:
        output_dir: Kayıt dizini. None ise /tmp kullanılır.

    Döner: [(monitor_name, screenshot_path), ...] listesi.
           Başarısız monitörler listeye dahil edilmez.
           Monitör listesi boşsa veya tek monitörse mevcut capture_screen() davranışı korunur.
    """
    monitors = await list_monitors()

    # Tek / sıfır monitör → eski davranış
    if len(monitors) <= 1:
        out_path = "/tmp/wa_screenshot.png" if output_dir is None else f"{output_dir}/monitor_0.png"
        shot = await capture_screen(out_path)
        if shot:
            name = monitors[0]["name"] if monitors else "primary"
            return [(name, shot)]
        return []

    out_base = output_dir or "/tmp"
    results: list[tuple[str, Path]] = []
    for i, mon in enumerate(monitors):
        region = (mon["x"], mon["y"], mon["w"], mon["h"])
        out_path = f"{out_base}/monitor_{i}_{mon['name']}.png"
        shot = await capture_screen(out_path, region=region)
        if shot:
            results.append((mon["name"], shot))
            logger.debug("capture_all_monitors: %s → %s", mon["name"], shot)
        else:
            logger.warning("capture_all_monitors: %s yakalama başarısız (region=%s)", mon["name"], region)

    return results


async def run_tesseract_on_file(image_path: str) -> str:
    """
    Verilen PNG dosyası üzerinde tesseract OCR çalıştırır, metni döndürür.

    Router'dan ayrı alındı (REFAC-5) — bu mantık feature katmanına aittir.
    """
    if not shutil.which("tesseract"):
        return (
            "❌ Tesseract kurulu değil. "
            "Kurulum: `sudo apt install tesseract-ocr tesseract-ocr-tur`"
        )

    ocr_base = image_path.replace(".png", "_ocr_internal")
    proc = await asyncio.create_subprocess_exec(
        "tesseract", image_path, ocr_base, "-l", "tur+eng",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        await asyncio.wait_for(proc.wait(), timeout=30)
    except asyncio.TimeoutError:
        return "❌ OCR zaman aşımı (30s)."

    ocr_txt = Path(ocr_base + ".txt")
    if ocr_txt.exists():
        text = ocr_txt.read_text(encoding="utf-8").strip()
        ocr_txt.unlink(missing_ok=True)
        return text if text else "(Ekranda okunabilir metin bulunamadı)"

    return "❌ OCR başarısız — çıktı dosyası oluşturulamadı."
