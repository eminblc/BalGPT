"""Disk yolu çözümleme yardımcıları — session storage state dosyaları (SRP).

Sorumluluk: session_id'den güvenli dosya yolu üretmek.
"""
from __future__ import annotations

from pathlib import Path

_BROWSER_ROOT = Path(__file__).parent.parent.parent.parent.parent  # 99-root/
_MAX_SESSION_ID_LEN = 128


def _resolve_sessions_dir() -> Path:
    """browser_sessions_dir göreceli ise 99-root'a göre çözümler, mutlak ise olduğu gibi döner."""
    from ...config import settings
    p = Path(settings.browser_sessions_dir)
    return p if p.is_absolute() else _BROWSER_ROOT / p


def _get_storage_state_path(session_id: str) -> Path:
    """Verilen session_id için disk storage state dosya yolunu döndürür. Dizin yoksa oluşturur."""
    stripped = session_id.strip()
    if not stripped:
        raise ValueError("session_id boş olamaz")
    if len(stripped) > _MAX_SESSION_ID_LEN:
        raise ValueError(
            f"session_id çok uzun ({len(stripped)} > {_MAX_SESSION_ID_LEN})"
        )
    sessions_dir = _resolve_sessions_dir()
    sessions_dir.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in stripped)
    if not safe_id:
        safe_id = "_empty_"
    return sessions_dir / f"{safe_id}.json"
