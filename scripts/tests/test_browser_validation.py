"""Browser _validation.py — SSRF koruması testleri (SEC-SCAN2-D5).

_is_ssrf_risk() fonksiyonu IP tabanlı SSRF risklerini tespit etmeli;
_validate_url() ise localhost/private URL'leri doğrudan engellemelidir.
"""
from __future__ import annotations

import pytest


# ── _is_ssrf_risk doğrudan testleri ─────────────────────────────────────────

def test_ssrf_loopback_127_0_0_1():
    """127.0.0.1 → loopback → SSRF riski."""
    from backend.features.browser._validation import _is_ssrf_risk
    assert _is_ssrf_risk("127.0.0.1") is True


def test_ssrf_loopback_127_0_0_2():
    """127.0.0.2 → loopback aralığı (127.0.0.0/8) → SSRF riski."""
    from backend.features.browser._validation import _is_ssrf_risk
    assert _is_ssrf_risk("127.0.0.2") is True


def test_ssrf_ipv4_mapped_loopback():
    """::ffff:127.0.0.1 → IPv4-mapped loopback → SSRF riski."""
    from backend.features.browser._validation import _is_ssrf_risk
    assert _is_ssrf_risk("::ffff:127.0.0.1") is True


def test_ssrf_ipv6_loopback():
    """::1 → IPv6 loopback → SSRF riski."""
    from backend.features.browser._validation import _is_ssrf_risk
    assert _is_ssrf_risk("::1") is True


def test_ssrf_unspecified_0_0_0_0():
    """0.0.0.0 → unspecified → SSRF riski."""
    from backend.features.browser._validation import _is_ssrf_risk
    assert _is_ssrf_risk("0.0.0.0") is True


def test_ssrf_private_rfc1918_10_x():
    """10.0.0.1 → private RFC1918 → SSRF riski."""
    from backend.features.browser._validation import _is_ssrf_risk
    assert _is_ssrf_risk("10.0.0.1") is True


def test_ssrf_private_rfc1918_192_168():
    """192.168.1.100 → private RFC1918 → SSRF riski."""
    from backend.features.browser._validation import _is_ssrf_risk
    assert _is_ssrf_risk("192.168.1.100") is True


def test_ssrf_link_local_169_254():
    """169.254.0.1 → link-local → SSRF riski."""
    from backend.features.browser._validation import _is_ssrf_risk
    assert _is_ssrf_risk("169.254.0.1") is True


def test_ssrf_public_ip_google_dns_not_risk():
    """8.8.8.8 → public IP → SSRF riski değil."""
    from backend.features.browser._validation import _is_ssrf_risk
    assert _is_ssrf_risk("8.8.8.8") is False


def test_ssrf_hostname_not_detected_as_risk():
    """example.com → hostname (IP değil) → _is_ssrf_risk False döner (DNS-based check ayrı)."""
    from backend.features.browser._validation import _is_ssrf_risk
    assert _is_ssrf_risk("example.com") is False


# ── _validate_url ile SSRF URL engelleme ─────────────────────────────────────

def test_validate_url_blocks_127_0_0_1():
    """http://127.0.0.1:8080 → _validate_url hata mesajı döner (engellenir)."""
    from backend.features.browser._validation import _validate_url
    error = _validate_url("http://127.0.0.1:8080")
    assert error is not None, "127.0.0.1 URL'i hata döndürmeli"
    lower = error.lower()
    assert "localhost" in lower or "private" in lower or "127" in lower


def test_validate_url_blocks_localhost_string():
    """http://localhost/ → localhost string → _validate_url hata döner."""
    from backend.features.browser._validation import _validate_url
    error = _validate_url("http://localhost/")
    assert error is not None, "localhost URL'i hata döndürmeli"


def test_validate_url_blocks_private_10_x():
    """http://10.0.0.1/ → private → _validate_url hata döner."""
    from backend.features.browser._validation import _validate_url
    error = _validate_url("http://10.0.0.1/")
    assert error is not None, "10.x.x.x URL'i hata döndürmeli"


def test_validate_url_blocks_link_local():
    """http://169.254.169.254/ → link-local (AWS metadata) → hata döner."""
    from backend.features.browser._validation import _validate_url
    error = _validate_url("http://169.254.169.254/latest/meta-data/")
    assert error is not None, "link-local URL'i hata döndürmeli"


def test_validate_url_allows_public_https():
    """https://example.com → public HTTPS → hata yok (None döner)."""
    from backend.features.browser._validation import _validate_url
    error = _validate_url("https://example.com")
    assert error is None, f"Public URL hata döndürmemeli, döndürdü: {error}"


def test_validate_url_allows_public_http():
    """http://example.com/path → public HTTP → hata yok (None döner)."""
    from backend.features.browser._validation import _validate_url
    error = _validate_url("http://example.com/path?q=1")
    assert error is None, f"Public URL hata döndürmemeli, döndürdü: {error}"


def test_validate_url_blocks_file_scheme():
    """file:///etc/passwd → yasaklı şema → hata döner."""
    from backend.features.browser._validation import _validate_url
    error = _validate_url("file:///etc/passwd")
    assert error is not None, "file:// URL'i hata döndürmeli"


def test_validate_url_blocks_javascript_scheme():
    """javascript:alert(1) → yasaklı şema → hata döner."""
    from backend.features.browser._validation import _validate_url
    error = _validate_url("javascript:alert(1)")
    assert error is not None, "javascript: URL'i hata döndürmeli"
