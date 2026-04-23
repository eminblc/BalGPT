"""URL güvenlik doğrulaması, hassas site koruması ve Playwright locator yardımcıları (SRP).

Sorumluluk: Gelen URL/selector girdilerini doğrulamak; tehlikeli hedefleri engellemek.
"""
from __future__ import annotations

import urllib.parse
from typing import Any

# ── URL Doğrulama (RISK-1) ────────────────────────────────────────

_BLOCKED_SCHEMES = frozenset({"file", "ftp", "javascript", "data", "chrome", "about"})
_BLOCKED_HOSTS = frozenset({
    "169.254.169.254",          # AWS/GCP metadata
    "metadata.google.internal", # GCP metadata
    "100.100.100.200",          # Alibaba metadata
})


def _validate_url(url: str) -> str | None:
    """URL güvenlik kontrolü (RISK-1). Hata mesajı döner; geçerliyse None."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return "Geçersiz URL formatı"

    scheme = parsed.scheme.lower()
    if scheme in _BLOCKED_SCHEMES:
        return f"Yasaklı URL şeması: {scheme}://"
    if not scheme or scheme not in ("http", "https"):
        return f"Yalnızca http/https desteklenir (gelen: {scheme or 'boş'}://)"

    host = parsed.hostname or ""
    if host in _BLOCKED_HOSTS:
        return f"Yasaklı hedef: {host}"
    if host in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return f"Localhost erişimi yasaklı: {host}"

    return None


# ── Hassas Site Koruması (RISK-3) ────────────────────────────────

_SENSITIVE_DOMAINS = frozenset({
    "web.whatsapp.com",
    "web.telegram.org",
    "mail.google.com",
    "outlook.live.com",
    "outlook.office365.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "online.isbank.com.tr",
    "internet.yapikredi.com.tr",
    "ibank.akbank.com",
    "internet.garanti.com.tr",
})


def _check_sensitive_navigation(
    url: str,
    session_id: str,
    current_page_url: str | None = None,
) -> str | None:
    """Hassas siteye navigasyon uyarısı üret (RISK-3). Döner: uyarı mesajı veya None."""
    try:
        new_host = (urllib.parse.urlparse(url).hostname or "").lower()
    except Exception:
        return None

    if new_host in _SENSITIVE_DOMAINS:
        return (
            f"⚠️ Hassas site navigasyonu: {new_host} "
            f"(session={session_id!r}). Ayrı session önerilir."
        )

    if current_page_url:
        try:
            current_host = (urllib.parse.urlparse(current_page_url).hostname or "").lower()
        except Exception:
            return None
        if current_host in _SENSITIVE_DOMAINS and new_host != current_host:
            return (
                f"⚠️ Hassas siteden ({current_host}) farklı siteye ({new_host}) "
                f"navigasyon — oturum cookie'leri context'te kalıyor "
                f"(session={session_id!r})."
            )

    return None


# ── CSS Locator Yardımcısı ────────────────────────────────────────

def _make_locator(page: Any, selector: str) -> Any:
    """CSS seçiciler için ``css=`` ön eki ekleyerek Playwright Locator döndürür.

    XPath, text=, role= vb. özel motorlar olduğu gibi bırakılır.
    Açık ``css=`` motoru Accessibility Tree taramasını tamamen atlar (~1.5× hızlı).
    """
    _XPATH_OR_SPECIAL = ("//", "(//", "text=", "role=", "aria=", "css=", "xpath=", "id=")
    if any(selector.startswith(p) for p in _XPATH_OR_SPECIAL):
        return page.locator(selector)
    return page.locator(f"css={selector}")
