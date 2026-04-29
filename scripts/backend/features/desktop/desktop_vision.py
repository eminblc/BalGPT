"""
Desktop vision modülü — ekran görüntüsü + Claude Vision API sorgusu ve cache.

Public API:
    vision_query(question, model, region, use_cache) -> str
    is_vision_available() -> bool
    check_vision_status() -> dict
    clear_bbox_cache() -> int
    get_bbox_cache_stats() -> dict
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Optional

from .desktop_capture import capture_screen
from .desktop_common import _detect_display, _env, _xdotool_available, x11_lock
from ...config import get_settings
from ...store.repositories import token_stat_repo

logger = logging.getLogger(__name__)


# ── Bounding Box Cache (OPT-3) ────────────────────────────────────────


class _BboxCache:
    """
    vision_query sonuçlarını TTL bazlı bellekte tutan singleton.

    Modül düzeyinde ham dict yerine bu sınıf kullanılır; global mutable
    state CLAUDE.md kuralına aykırı olduğundan encapsulation zorunludur.
    """

    TTL: float = 60.0  # saniye

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float]] = {}

    def make_key(
        self,
        question: str,
        window_title: str,
        region: Optional[tuple[int, int, int, int]],
    ) -> str:
        """Cache anahtarı: soru hash'i + pencere başlığı + region."""
        q_hash = hashlib.md5(question.lower().strip().encode()).hexdigest()[:8]
        title_slug = re.sub(r"[^a-z0-9]", "_", window_title.lower())[:30]
        region_str = f"_{region[0]}_{region[1]}_{region[2]}_{region[3]}" if region else ""
        return f"{q_hash}_{title_slug}{region_str}"

    def get(self, key: str) -> tuple[str, float] | None:
        return self._data.get(key)

    def set(self, key: str, answer: str) -> None:
        self._data[key] = (answer, time.monotonic())

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> int:
        count = len(self._data)
        self._data.clear()
        logger.info("bbox_cache temizlendi: %d girdi silindi", count)
        return count

    def stats(self) -> dict:
        now = time.monotonic()
        active = sum(1 for _, ts in self._data.values() if now - ts < self.TTL)
        return {
            "total": len(self._data),
            "active": active,
            "expired": len(self._data) - active,
            "ttl_seconds": self.TTL,
        }


_bbox_cache = _BboxCache()


# ── Vision Availability Check (DESK-LOGIN-3) ─────────────────────────


def is_vision_available() -> bool:
    """Anthropic API key tanımlı mı kontrol eder. Görev başında proaktif kullanım için."""
    from ..config import get_settings
    try:
        key = get_settings().anthropic_api_key.get_secret_value()
        return bool(key)
    except Exception:
        return False


def check_vision_status() -> dict:
    """
    Vision API durumunu yapılandırılmış şekilde döndürür.

    Döner:
        {"available": bool, "fallback": str | None, "message": str}
        - available=True  → Vision API kullanılabilir
        - available=False → API key yok; fallback önerisi ve açıklayıcı mesaj içerir
    """
    if is_vision_available():
        return {
            "available": True,
            "fallback": None,
            "message": "✅ Vision API kullanılabilir.",
        }
    return {
        "available": False,
        "fallback": "playwright",
        "message": (
            "⚠️ Vision API kullanılamıyor (ANTHROPIC_API_KEY tanımlı değil).\n"
            "Playwright (/internal/browser) ile DOM tabanlı navigasyona geçebilirsin — "
            "selector ile click/fill/get_text işlemleri Vision gerektirmez."
        ),
    }


# ── Vision Query Rate Limiter (5 dk sliding window) ───────────────────


class _VisionLimiter:
    """Session bazlı sliding window sayaç — aşırı vision_query'yi engeller."""

    WINDOW_SEC: float = 300.0  # 5 dk

    def __init__(self) -> None:
        # session_id → list[timestamp]
        self._hits: dict[str, list[float]] = {}

    def check_and_record(self, session_id: str, max_per_window: int) -> tuple[bool, int]:
        """
        Aşıldı mı kontrol et, aşılmadıysa +1 kaydet.
        Döner: (izin_ver, pencere_içi_sayaç)
        """
        now = time.monotonic()
        hits = [t for t in self._hits.get(session_id, []) if now - t < self.WINDOW_SEC]
        if len(hits) >= max_per_window:
            self._hits[session_id] = hits
            return False, len(hits)
        hits.append(now)
        self._hits[session_id] = hits
        return True, len(hits)

    def reset(self, session_id: str | None = None) -> None:
        if session_id is None:
            self._hits.clear()
        else:
            self._hits.pop(session_id, None)


_vision_limiter = _VisionLimiter()


def reset_vision_limiter(session_id: str | None = None) -> None:
    """Vision limiter sayacını sıfırlar (test ve manuel reset için)."""
    _vision_limiter.reset(session_id)


def _bbox_cache_key(question: str, window_title: str, region: Optional[tuple[int, int, int, int]]) -> str:
    """Cache anahtarı: soru hash'i + pencere başlığı + region. (Geriye dönük uyumluluk için)"""
    return _bbox_cache.make_key(question, window_title, region)


def clear_bbox_cache() -> int:
    """Tüm bounding box cache'ini temizler. Temizlenen girdi sayısını döndürür."""
    return _bbox_cache.clear()


def get_bbox_cache_stats() -> dict:
    """Cache istatistiklerini döndürür."""
    return _bbox_cache.stats()


async def _get_active_window_title() -> str:
    """
    Aktif pencere başlığını döndürür (cache key için).
    xdotool varsa kullanır; yoksa boş string döner.
    """
    if not _xdotool_available():
        return ""
    try:
        async with x11_lock:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "getactivewindow", "getwindowname",
                env=_env(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=3)
        if proc.returncode == 0 and stdout:
            return stdout.decode(errors="replace").strip()
    except (asyncio.TimeoutError, Exception):
        pass
    return ""


async def vision_query(
    question: str,
    model: str = "claude-haiku-4-5-20251001",
    region: Optional[tuple[int, int, int, int]] = None,
    use_cache: bool = True,
    session_id: Optional[str] = None,
) -> str:
    """
    Ekran görüntüsü alır ve Claude Vision API'sine sorgu gönderir.

    Args:
        question: Ekran hakkında sorulacak soru (ör. "Hangi uygulama açık?", "Ekranda ne yazıyor?").
        region: (x, y, w, h) — yalnızca bu bölgeyi Vision API'ye gönder. None ise tüm ekran.
        model: Kullanılacak Claude modeli. Varsayılan: claude-haiku-4-5-20251001.
        use_cache: True ise aynı pencerede aynı soru 60s içinde tekrar sorulursa cache'den döner.

    Döner: Claude'un yanıtı veya hata mesajı.
    """
    import base64
    import tempfile
    from pathlib import Path as _Path

    from ..adapters.llm.llm_factory import get_llm

    if not question or not question.strip():
        return "❌ Soru (question) boş olamaz."

    # ── Session rate limit (5 dk sliding window) ─────────────────
    _settings = get_settings()
    sid = session_id or "default"
    allowed, count = _vision_limiter.check_and_record(sid, _settings.desktop_vision_max_per_session)
    if not allowed:
        logger.warning(
            "vision_query limit aşıldı: session=%s, sayaç=%d/%d",
            sid, count, _settings.desktop_vision_max_per_session,
        )
        return (
            f"⚠️ Vision query limiti aşıldı ({count}/{_settings.desktop_vision_max_per_session} — 5 dk penceresi).\n"
            "DOM/xdotool ile körlemesine navigasyonla devam et veya pencerenin dolması için bekle.\n"
            "Görev başına çok fazla vision çağrısı context'i doldurur ve API boyut limitini aşar."
        )

    # Erken API key kontrolü — key yoksa Playwright fallback öner (DESK-LOGIN-3)
    if not get_settings().anthropic_api_key.get_secret_value():
        logger.warning("vision_query: ANTHROPIC_API_KEY tanımlı değil — Playwright fallback öneriliyor")
        return (
            "⚠️ Vision API kullanılamıyor (ANTHROPIC_API_KEY tanımlı değil).\n"
            "Playwright (/internal/browser) ile DOM tabanlı navigasyona geç:\n"
            "  • goto → fill → click → get_text ile form/sayfa kontrolü\n"
            "  • Selector bulamazsan get_content ile HTML'i çek\n"
            "Vision gerektirmeden devam edebilirsin."
        )

    # ── Cache kontrolü (OPT-3) ────────────────────────────────────
    if use_cache:
        window_title = await _get_active_window_title()
        cache_key = _bbox_cache.make_key(question, window_title, region)
        cached = _bbox_cache.get(cache_key)
        if cached is not None:
            cached_answer, cached_ts = cached
            now = time.monotonic()
            if now - cached_ts < _bbox_cache.TTL:
                logger.info(
                    "vision_query [CACHE HIT]: soru=%r, pencere=%r, kalan_ttl=%.1fs",
                    question[:60], window_title[:30], _bbox_cache.TTL - (now - cached_ts),
                )
                return cached_answer
            else:
                _bbox_cache.delete(cache_key)
    else:
        window_title = ""
        cache_key = ""

    # Geçici dosya
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir="/tmp") as f:
        tmp_img = f.name

    screenshot = await capture_screen(tmp_img, region=region)
    if screenshot is None:
        _Path(tmp_img).unlink(missing_ok=True)
        return (
            "❌ Ekran görüntüsü alınamadı.\n"
            f"DISPLAY={_detect_display()}\n"
            "Kontrol:\n"
            "  • X11 oturumu açık mı?\n"
            "  • `sudo apt install scrot` kurulu mu?"
        )

    try:
        img_bytes = _Path(str(screenshot)).read_bytes()
        img_b64 = base64.standard_b64encode(img_bytes).decode("ascii")
    except OSError as exc:
        _Path(tmp_img).unlink(missing_ok=True)
        return f"❌ Ekran görüntüsü okunamadı: {exc}"
    finally:
        _Path(tmp_img).unlink(missing_ok=True)

    try:
        llm = get_llm(backend="anthropic")
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": question,
                    },
                ],
            }
        ]
        completion = await llm.complete(messages, model=model, max_tokens=1024)
        answer = completion.text
        logger.info("vision_query: model=%s, soru=%r, yanıt=%d karakter", model, question[:60], len(answer))
        try:
            await token_stat_repo.add_usage(
                completion.model_id, completion.model_name, completion.backend,
                completion.input_tokens, completion.output_tokens,
                context="desktop_vision",
            )
        except Exception:
            pass

        # Cache'e yaz (OPT-3)
        if use_cache and cache_key:
            _bbox_cache.set(cache_key, answer)
            logger.debug("vision_query [CACHE WRITE]: key=%s, pencere=%r", cache_key, window_title[:30])

        return answer
    except Exception as exc:
        logger.error("vision_query hata: %s", exc)
        return f"❌ Vision API hatası: {exc}"
