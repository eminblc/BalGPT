"""i18n — Türkçe / İngilizce lokalizasyon yardımcısı.

Kullanım:
    from backend.i18n import t

    msg = t("totp.invalid", lang, tries=2)
    # tr → "❌ Geçersiz TOTP kodu. (2 hak kaldı)"
    # en → "❌ Invalid TOTP code. (2 attempts left)"

Dil belirleme:
    lang = session.get("lang") or settings.default_language

Fallback zinciri:
    istenen dil → "tr" → key'in kendisi (asla crash etmez)
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCALE_DIR = Path(__file__).parent / "locales"
_SUPPORTED   = frozenset({"tr", "en"})
_FALLBACK    = "tr"


@lru_cache(maxsize=None)
def _load(lang: str) -> dict:
    """Locale JSON'ını yükler ve cache'e alır (uygulama ömrü boyunca tek seferlik)."""
    path = _LOCALE_DIR / f"{lang}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover
        logger.error("i18n: locale yüklenemedi lang=%s exc=%s", lang, exc)
        return {}


def _lookup(key: str, lang: str) -> str | None:
    """Nokta-notasyonlu key'i locale dict'ten arar. Bulamazsa None döner."""
    node: object = _load(lang)
    for part in key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node if isinstance(node, str) else None


def t(key: str, lang: str = _FALLBACK, **kwargs: object) -> str:
    """Lokalize string döndürür; bulamazsa tr fallback, sonra key'in kendisi.

    Args:
        key:    "totp.invalid" gibi nokta-notasyonlu key
        lang:   "tr" veya "en" (bilinmeyenler fallback'e düşer)
        kwargs: f-string şablonu parametreleri, örn. tries=2

    Returns:
        Lokalize ve interpolasyon uygulanmış string.
        Hiçbir durumda exception fırlatmaz.
    """
    if lang not in _SUPPORTED:
        lang = _FALLBACK

    val = _lookup(key, lang)

    # Bulunamadıysa tr fallback dene
    if val is None and lang != _FALLBACK:
        val = _lookup(key, _FALLBACK)

    # Hâlâ bulunamadıysa key'i döndür (sessiz — prod'da loglanır)
    if val is None:
        logger.warning("i18n: eksik key=%r lang=%s", key, lang)
        return key

    if not kwargs:
        return val

    try:
        return val.format_map(kwargs)
    except (KeyError, ValueError) as exc:
        logger.warning("i18n: interpolasyon hatası key=%r kwargs=%s exc=%s", key, kwargs, exc)
        return val


def supported_langs() -> list[str]:
    """Desteklenen dil kodlarını döndürür."""
    return sorted(_SUPPORTED)
