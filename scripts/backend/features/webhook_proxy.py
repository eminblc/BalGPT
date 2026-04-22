"""Webhook proxy yöneticisi — ngrok / cloudflared / external / none.

Startup'ta start_proxy() çağrılır; public URL'yi döndürür ve modül içi
_public_url değişkenine kaydeder. Diğer modüller get_public_url() ile okur.

Desteklenen modlar:
  ngrok       — pyngrok kütüphanesi ile tünel açar (ngrok kurulu olmalı)
  cloudflared — cloudflared CLI ile tünel açar (cloudflared kurulu olmalı)
  external    — PUBLIC_URL env değişkeninden URL alır
  none        — proxy başlatılmaz; URL None döner
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

_public_url: str | None = None
_active_mode: str = "none"
_cloudflared_proc: subprocess.Popen | None = None  # type: ignore[type-arg]


def get_public_url() -> str | None:
    """Başlatılan proxy'nin public URL'sini döndür. None = proxy yok."""
    return _public_url


def stop_proxy() -> None:
    """Çalışan proxy'yi durdur; process'leri temizle.

    start_proxy() ile başlatılan ngrok tünellerini veya cloudflared process'ini
    kapatır. Servis shutdown'unda çağrılmalıdır; aksi hâlde process'ler zombie kalır.
    """
    global _public_url, _active_mode, _cloudflared_proc

    if _active_mode == "ngrok":
        try:
            from pyngrok import ngrok  # type: ignore
            ngrok.kill()
            logger.info("ngrok tünelleri kapatıldı.")
        except Exception as exc:
            logger.warning("ngrok kapatma hatası: %s", exc)

    elif _active_mode == "cloudflared":
        if _cloudflared_proc is not None:
            try:
                _cloudflared_proc.terminate()
                _cloudflared_proc.wait(timeout=5)
                logger.info("cloudflared process sonlandırıldı.")
            except Exception as exc:
                logger.warning("cloudflared kapatma hatası: %s", exc)
            finally:
                _cloudflared_proc = None

    _public_url = None
    _active_mode = "none"


def start_proxy(mode: str, port: int) -> str | None:
    """Belirtilen modda proxy başlat; public URL'yi döndür.

    Args:
        mode: "ngrok" | "cloudflared" | "external" | "none"
        port: FastAPI'nin dinlediği yerel port (örn. 8010)

    Returns:
        Public HTTPS URL (https://...) veya None.
    """
    global _public_url, _active_mode
    mode = (mode or "none").strip().lower()
    _active_mode = mode

    if mode == "ngrok":
        _public_url = _start_ngrok(port)
    elif mode == "cloudflared":
        _public_url = _start_cloudflared(port)
    elif mode == "external":
        _public_url = _read_external_url()
    elif mode == "none":
        logger.info("Webhook proxy devre dışı (WEBHOOK_PROXY=none).")
        _public_url = None
    else:
        logger.warning("Bilinmeyen WEBHOOK_PROXY modu: %r — proxy başlatılmadı.", mode)
        _public_url = None

    if _public_url:
        logger.info("Webhook public URL: %s", _public_url)

    return _public_url


# ── ngrok ────────────────────────────────────────────────────────────────────

def _start_ngrok(port: int) -> str | None:
    try:
        from pyngrok import ngrok, conf  # type: ignore

        ngrok_token = os.environ.get("NGROK_AUTHTOKEN", "")
        if ngrok_token:
            conf.get_default().auth_token = ngrok_token

        tunnel = ngrok.connect(port, "http")
        url: str = tunnel.public_url  # type: ignore[attr-defined]
        # ngrok ücretsiz planda http → https yönlendirir; https'i tercih et
        if url.startswith("http://"):
            url = url.replace("http://", "https://", 1)
        logger.info("ngrok tüneli açıldı: %s → localhost:%d", url, port)
        return url
    except ImportError:
        logger.error(
            "pyngrok kurulu değil. Kur: pip install pyngrok  "
            "veya WEBHOOK_PROXY=none yap."
        )
    except Exception as e:
        logger.error("ngrok başlatılamadı: %s", e)
    return None


# ── cloudflared ──────────────────────────────────────────────────────────────

def _start_cloudflared(port: int) -> str | None:
    """cloudflared Quick Tunnel açar; stdout'tan URL'yi okur (en fazla 15 saniye bekler)."""
    global _cloudflared_proc
    try:
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", f"http://localhost:{port}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        _cloudflared_proc = proc
    except FileNotFoundError:
        logger.error(
            "cloudflared bulunamadı. Kur: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
        )
        return None

    url_pattern = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
    found_url: list[str] = []

    def _reader():
        assert proc.stdout
        for line in proc.stdout:
            logger.debug("cloudflared: %s", line.rstrip())
            m = url_pattern.search(line)
            if m and not found_url:
                found_url.append(m.group(0))

    t = threading.Thread(target=_reader, daemon=True)
    t.start()

    # En fazla 15 saniye bekle
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not found_url:
        time.sleep(0.2)

    if found_url:
        logger.info("cloudflared tüneli açıldı: %s → localhost:%d", found_url[0], port)
        return found_url[0]

    logger.error("cloudflared URL 15 saniyede alınamadı.")
    proc.terminate()
    return None


# ── external ─────────────────────────────────────────────────────────────────

def _read_external_url() -> str | None:
    url = os.environ.get("PUBLIC_URL", "").strip()
    if not url:
        logger.error(
            "WEBHOOK_PROXY=external ancak PUBLIC_URL tanımlı değil. "
            ".env'e PUBLIC_URL=https://... ekle."
        )
        return None
    if not url.startswith("https://"):
        logger.warning("PUBLIC_URL 'https://' ile başlamıyor: %r", url)
    logger.info("Harici webhook URL kullanılıyor: %s", url)
    return url


# ── Startup / Shutdown hook'ları (registry tarafından çağrılır) ──────────────

async def lifecycle_startup() -> None:
    import asyncio as _aio
    from ..config import settings
    await _aio.to_thread(start_proxy, settings.webhook_proxy, settings.port)


async def lifecycle_shutdown() -> None:
    import asyncio as _aio
    try:
        await _aio.to_thread(stop_proxy)
    except Exception as exc:
        logger.warning("Webhook proxy kapatma hatası: %s", exc)
