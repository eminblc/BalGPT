"""
Site-özel credential store (FEAT-16).

CREDENTIAL_<SITE_SLUG>_<FIELD> env var'larını okuyarak
browser otomasyon akışlarına kullanıcı adı / şifre / token sağlar.

Kullanım:
    from ..features.credential_store import get_credential, list_credentials

    ok, msg, value = get_credential("mercek_itu", "user")
    slugs = list_credentials()
"""
from __future__ import annotations

import logging

from ..config import settings  # REFAC-14: modül seviyesine taşındı

logger = logging.getLogger(__name__)

_SECRET_FIELDS = frozenset({"pass", "password", "secret", "token", "key", "pin"})


def get_credential(site_slug: str, field: str) -> tuple[bool, str, str | None]:
    """
    CREDENTIAL_<SITE_SLUG>_<FIELD> env var değerini döndürür.
    Döner: (ok, mesaj, değer|None)

    IMP-FEAT-15: ok=False olduğunda value=None'dur — çağırıcı mutlaka ok'u kontrol etmeli,
    değeri kullanmadan önce None kontrolü yapılmalıdır.
    Örnek:
        ok, msg, value = get_credential("site", "user")
        if not ok:
            # value is None here — do not use it
            return False, msg
        # value is a str here — safe to use

    Şifre/token alanları logda maskelenir (IMP-DESK-1).
    """
    value = settings.get_site_credential(site_slug, field)
    if value is None:
        return False, f"❌ Credential bulunamadı: {site_slug}/{field}", None
    is_secret = field.lower() in _SECRET_FIELDS
    log_val = "***" if is_secret else value
    logger.info(
        "credential_store/get: site=%r field=%r → %s",
        site_slug, field, log_val,
    )
    return True, f"✅ Credential alındı: {site_slug}/{field}", value


def list_credentials() -> list[str]:
    """Tanımlı credential site slug'larını döndürür."""
    return settings.list_site_credentials()
