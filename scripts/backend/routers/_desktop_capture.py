"""Screen capture aksiyonları — desktop_router.py'den SRP ayrımı (SOLID-v2-6).

Handler'lar:
    screenshot    — Ekran görüntüsü (tek/çoklu monitör, opsiyonel OCR)
    ocr           — Ekran görüntüsü + Tesseract OCR (yalnızca metin)
    record_screen — Ekran video kaydı (tek/çoklu monitör)
"""
from __future__ import annotations

import logging
import time
from pathlib import Path as _Path
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from .desktop_router import DesktopRequest

logger = logging.getLogger(__name__)


# ── Handler'lar ───────────────────────────────────────────────────────

async def _handle_ocr(body: DesktopRequest) -> dict:
    from ..features.desktop import ocr_screen
    text = await ocr_screen()
    ok = not text.startswith("❌")
    logger.info("desktop/ocr: %d karakter okundu", len(text))
    return {"ok": ok, "message": "OCR tamamlandı." if ok else text, "text": text}


async def _handle_screenshot(body: DesktopRequest) -> dict:
    from ..features.desktop import capture_screen
    from ..features.desktop import capture_all_monitors

    region = tuple(body.region) if body.region else None  # type: ignore[arg-type]

    # region belirtilmişse → tek bölge yakalama (eski davranış)
    if region is not None:
        out_path = body.output_path or "/tmp/wa_internal_shot.png"
        screenshot = await capture_screen(out_path, region=region)

        if screenshot is None:
            msg = (
                "❌ Ekran görüntüsü alınamadı. "
                "X11 oturumu açık mı? DISPLAY ayarlı mı? "
                "`sudo apt install scrot` kurulu mu?"
            )
            logger.warning("desktop/screenshot: başarısız (region=%s)", region)
            return {"ok": False, "message": msg}

        result: dict = {"ok": True, "message": "Ekran görüntüsü alındı.", "path": str(screenshot)}
        if body.ocr:
            from ..features.desktop import run_tesseract_on_file
            text = await run_tesseract_on_file(str(screenshot))
            result["text"] = text
            result["message"] = "Ekran görüntüsü alındı ve OCR uygulandı."
        logger.info("desktop/screenshot (region): %s ocr=%s", screenshot, body.ocr)
        return result

    # region yok → çoklu monitör kontrolü
    shots = await capture_all_monitors(output_dir="/tmp")

    if not shots:
        msg = (
            "❌ Ekran görüntüsü alınamadı. "
            "X11 oturumu açık mı? DISPLAY ayarlı mı? "
            "`sudo apt install scrot` kurulu mu?"
        )
        logger.warning("desktop/screenshot: capture_all_monitors başarısız")
        return {"ok": False, "message": msg}

    if len(shots) == 1:
        # Tek monitör — geriye dönük uyumlu tekil yanıt
        mon_name, screenshot = shots[0]
        result = {"ok": True, "message": "Ekran görüntüsü alındı.", "path": str(screenshot)}
        if body.ocr:
            from ..features.desktop import run_tesseract_on_file
            text = await run_tesseract_on_file(str(screenshot))
            result["text"] = text
            result["message"] = "Ekran görüntüsü alındı ve OCR uygulandı."
        logger.info("desktop/screenshot (single-mon %s): %s ocr=%s", mon_name, screenshot, body.ocr)
        return result

    # Birden fazla monitör → paths listesi döner; OCR tek dosya yerine metin birleştirilir
    paths = [str(p) for _, p in shots]
    monitor_names = [n for n, _ in shots]
    result = {
        "ok": True,
        "message": f"{len(shots)} monitörden ekran görüntüsü alındı: {', '.join(monitor_names)}",
        "paths": paths,
        "path": paths[0],  # geriye dönük uyumluluk için
        "monitor_count": len(shots),
    }
    if body.ocr:
        from ..features.desktop import run_tesseract_on_file
        ocr_texts = []
        for mon_name, shot_path in shots:
            text = await run_tesseract_on_file(str(shot_path))
            ocr_texts.append(f"[{mon_name}]\n{text}")
        result["text"] = "\n\n".join(ocr_texts)
        result["message"] = f"{len(shots)} monitörden ekran görüntüsü alındı ve OCR uygulandı."
    logger.info(
        "desktop/screenshot (multi-mon %d): %s ocr=%s",
        len(shots), monitor_names, body.ocr,
    )
    return result


async def _handle_record_screen(body: DesktopRequest) -> dict:
    """
    Ekran video kaydı alır (FEAT-DESK-REC-1 + FEAT-DESK-MULTIMON-1).

    - region belirtilmişse sadece o bölgeyi kaydeder.
    - region yok → çoklu monitör tespiti:
        * Tek monitör: tüm ekranı kaydeder.
        * Çok monitör: her monitör için ayrı kayıt, her biri ayrı yanıtta döner.
    """
    from ..config import settings

    if not settings.desktop_recording:
        return {
            "ok": False,
            "message": (
                "❌ Ekran video kaydı devre dışı. "
                "Etkinleştirmek için: DESKTOP_RECORDING=true (.env)"
            ),
        }

    from ..features.desktop import (
        record_screen, record_all_monitors, check_size_mb,
    )

    region = tuple(body.region) if body.region else None  # type: ignore[arg-type]
    max_mb = settings.desktop_recording_max_mb
    ts = int(time.time())

    # Kayıt dizini oluştur — mutlak yol (99-root/data/media/desktop_recordings)
    _ROOT = _Path(__file__).parent.parent.parent.parent
    recordings_dir = _ROOT / "data" / "media" / "desktop_recordings"
    recordings_dir.mkdir(parents=True, exist_ok=True)

    if region is not None:
        # Bölge belirtilmiş — tek kayıt
        out_path = str(recordings_dir / f"recording_{ts}.mp4")
        rec = await record_screen(out_path, body.duration, region=region)

        if rec is None:
            logger.warning("desktop/record_screen: kayıt başarısız (region=%s)", region)
            return {
                "ok": False,
                "message": (
                    "❌ Ekran kaydı başarısız. "
                    "ffmpeg kurulu mu? X11 oturumu açık mı? "
                    "`sudo apt install ffmpeg` gerekiyor."
                ),
            }

        size_mb = check_size_mb(rec)
        within_limit = size_mb <= max_mb
        logger.info(
            "desktop/record_screen (region): %s %.1f MB within_limit=%s",
            rec, size_mb, within_limit,
        )
        return {
            "ok": True,
            "message": f"Ekran kaydı tamamlandı ({size_mb:.1f} MB, {body.duration}s).",
            "path": str(rec),
            "size_mb": round(size_mb, 2),
            "within_limit": within_limit,
        }

    # Region yok → çoklu monitör
    recs = await record_all_monitors(str(recordings_dir), body.duration)

    if not recs:
        logger.warning("desktop/record_screen: record_all_monitors başarısız")
        return {
            "ok": False,
            "message": (
                "❌ Ekran kaydı başarısız. "
                "ffmpeg kurulu mu? X11 oturumu açık mı? "
                "`sudo apt install ffmpeg` gerekiyor."
            ),
        }

    if len(recs) == 1:
        mon_name, rec = recs[0]
        size_mb = check_size_mb(rec)
        within_limit = size_mb <= max_mb
        logger.info(
            "desktop/record_screen (single-mon %s): %s %.1f MB",
            mon_name, rec, size_mb,
        )
        return {
            "ok": True,
            "message": f"Ekran kaydı tamamlandı ({size_mb:.1f} MB, {body.duration}s).",
            "path": str(rec),
            "size_mb": round(size_mb, 2),
            "within_limit": within_limit,
        }

    # Çok monitör
    entries = []
    for mon_name, rec in recs:
        size_mb = check_size_mb(rec)
        within_limit = size_mb <= max_mb
        entries.append({
            "monitor": mon_name,
            "path": str(rec),
            "size_mb": round(size_mb, 2),
            "within_limit": within_limit,
        })

    monitor_names = [e["monitor"] for e in entries]
    logger.info(
        "desktop/record_screen (multi-mon %d): %s",
        len(entries), monitor_names,
    )
    return {
        "ok": True,
        "message": f"{len(entries)} monitör kaydedildi: {', '.join(monitor_names)}",
        "paths": [e["path"] for e in entries],
        "path": entries[0]["path"],
        "recordings": entries,
        "monitor_count": len(entries),
    }


# ── Export ────────────────────────────────────────────────────────────

HANDLERS: dict[str, Callable[..., Awaitable[dict]]] = {
    "ocr":           _handle_ocr,
    "screenshot":    _handle_screenshot,
    "record_screen": _handle_record_screen,
}

PARAM_EXTRACTORS: dict[str, Callable] = {
    "screenshot":    lambda b: {"ocr": b.ocr, "region": b.region, "output_path": b.output_path},
    "ocr":           lambda b: {"ocr": b.ocr, "region": b.region, "output_path": b.output_path},
    "record_screen": lambda b: {"duration": b.duration, "region": b.region},
}
