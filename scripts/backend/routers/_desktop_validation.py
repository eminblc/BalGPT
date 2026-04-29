"""
Desktop aksiyon doğrulama yardımcıları — SRP-V1.

DesktopRequest field_validator'larının delege ettiği saf fonksiyonlar.
Yeni aksiyon eklendiğinde yalnızca ALLOWED_ACTIONS güncellenir; router değişmez.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

# output_path yalnızca bu dizinler altında kabul edilir (path traversal koruması)
_ALLOWED_OUTPUT_PREFIXES: tuple[str, ...] = ("/tmp/", "/var/tmp/")

# vision_query'de kullanılabilecek model izin listesi (finansal DoS + API injection koruması)
ALLOWED_VISION_MODELS: frozenset[str] = frozenset({
    "claude-haiku-4-5-20251001",
    "claude-haiku-4-5",
    "claude-sonnet-4-6",
    "claude-sonnet-4-5",
    "claude-opus-4-6",
})

ALLOWED_ACTIONS: frozenset[str] = frozenset({
    "open", "run", "screenshot", "ocr", "type", "key",
    "click", "move", "scroll", "vision_query", "check_vision", "get_windows", "focus_window",
    "unlock_screen", "is_locked", "sudo_exec", "clear_bbox_cache", "bbox_cache_stats",
    # FEAT-17 — AT-SPI accessibility tree
    "get_desktop_tree", "find_element", "activate_element",
    # FEAT-DESK-REC-1 — ekran video kaydı
    "record_screen",
    # DESK-OPT-8 — X11 MapNotify tabanlı popup yönetimi
    "watch_popup", "stop_watch_popup", "list_watch_popup",
})


def validate_action(v: str) -> str:
    if v not in ALLOWED_ACTIONS:
        raise ValueError(
            f"Geçersiz aksiyon: {v!r}. "
            f"Geçerliler: {', '.join(sorted(ALLOWED_ACTIONS))}"
        )
    return v


def validate_timeout(v: int) -> int:
    if not (5 <= v <= 600):
        raise ValueError("timeout 5–600 saniye arasında olmalı.")
    return v


def validate_region(v: Optional[list[int]]) -> Optional[list[int]]:
    if v is not None:
        if len(v) != 4:
            raise ValueError("region [x, y, w, h] formatında 4 tam sayı olmalı.")
        if any(n < 0 for n in v):
            raise ValueError("region değerleri negatif olamaz.")
        if v[2] <= 0 or v[3] <= 0:
            raise ValueError("region genişlik (w) ve yükseklik (h) sıfırdan büyük olmalı.")
    return v


def validate_delay_ms(v: int) -> int:
    if not (0 <= v <= 500):
        raise ValueError("delay_ms 0–500 ms arasında olmalı.")
    return v


def validate_duration(v: int) -> int:
    if not (1 <= v <= 300):
        raise ValueError("duration 1–300 saniye arasında olmalı.")
    return v


def validate_output_path(v: Optional[str]) -> Optional[str]:
    """output_path yalnızca /tmp/ veya /var/tmp/ altında olabilir (path traversal koruması)."""
    if v is None:
        return v
    try:
        resolved = str(Path(v).resolve())
    except Exception:
        raise ValueError("output_path geçersiz yol.")
    # Sembolik link çözümlendikten sonra da izin verilen dizin altında olmalı
    if not any(resolved.startswith(prefix) for prefix in _ALLOWED_OUTPUT_PREFIXES):
        raise ValueError(
            f"output_path yalnızca {' veya '.join(_ALLOWED_OUTPUT_PREFIXES)} "
            "altında olabilir."
        )
    return v


def validate_vision_model(v: str) -> str:
    """vision_model izin listesinde olmalı (finansal DoS + API injection koruması)."""
    if v not in ALLOWED_VISION_MODELS:
        raise ValueError(
            f"Geçersiz vision_model: {v!r}. "
            f"Geçerliler: {', '.join(sorted(ALLOWED_VISION_MODELS))}"
        )
    return v
